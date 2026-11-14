"""Archive migration safety: dry-run immutability, ledger integrity, drift detection and refusals.

All tests use local SQLite databases. They prove behaviour from recorded SQL statements and before-and-after
schema inventories, not from log messages. No network, no Turso, no production credentials.
"""

from __future__ import annotations

import re

import pytest

from database import migrate as runner
from database.archive_migrations import archive_gate as gate
from database.connection import DatabaseConfigError, SQLiteDatabase
from database.migrate import MigrationError

WRITE = re.compile(
    r"^\s*(CREATE|INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE|REINDEX|VACUUM|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE)
APPROVED = {gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}


class RecordingDB(SQLiteDatabase):
    """Records every statement that reaches the database, so tests can prove what did and did not run."""

    def __init__(self, path=":memory:"):
        super().__init__(path)
        self.statements: list[str] = []
        self.role = "archive"

    def batch(self, statements, *, transactional=True, rollback=False):
        stmts = list(statements)
        self.statements.extend(s for s, _ in stmts)
        return super().batch(stmts, transactional=transactional, rollback=rollback)


def _raw_objects(db) -> list[tuple]:
    return sorted(tuple(r) for r in db.execute(
        "SELECT type, name, tbl_name, COALESCE(sql,'') FROM sqlite_master"))


def _ledger(db) -> list[tuple]:
    if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"):
        return []
    return [tuple(r) for r in db.execute("SELECT version, name, checksum, result FROM schema_migrations "
                                         "ORDER BY version")]


def _migrated(upto: int | None = None) -> RecordingDB:
    d = RecordingDB()
    for m in gate._migrations(upto):
        for s in m.statements():
            d.execute(s)
        d.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, "
                  "name TEXT NOT NULL, "
                  "checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL, result TEXT NOT NULL)")
        d.execute("INSERT INTO schema_migrations VALUES (?,?,?,?,?)",
                  (m.version, m.name, m.checksum, "2026-11-10T00:00:00Z", "applied"))
    d.statements.clear()
    return d


# ------------------------------------------------------------------ dry run is genuinely read-only

@pytest.mark.parametrize("state", [0, 2, 4])
def test_archive_dry_run_executes_no_write_statement_and_changes_nothing(state):
    d = _migrated(state) if state else RecordingDB()
    before_objects, before_ledger = _raw_objects(d), _ledger(d)
    d.statements.clear()
    out = gate.apply(d, dry_run=True)
    assert [s for s in d.statements if WRITE.match(s)] == [], "a dry run must issue no write or DDL statement"
    assert _raw_objects(d) == before_objects, "dry run changed schema objects"
    assert _ledger(d) == before_ledger, "dry run changed the migration ledger"
    assert len(out["pending"]) == 8 - state
    assert all(len(p["checksum"]) == 64 for p in out["pending"])


def test_runner_dry_run_creates_no_ledger_and_no_objects():
    d = RecordingDB()
    log = runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)
    assert all(s.startswith("would apply") for s in log)
    assert [s for s in d.statements if WRITE.match(s)] == []
    assert _raw_objects(d) == []


def test_runner_dry_run_does_not_touch_existing_checksums():
    d = _migrated(2)
    before = _ledger(d)
    runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)
    assert _ledger(d) == before


# ------------------------------------------------------------------ ledger integrity (fail closed)

def test_recorded_migration_name_must_match_the_repository():
    d = _migrated(1)
    d.execute("UPDATE schema_migrations SET name = 'renamed' WHERE version = 1")  # ledger edit for the test
    with pytest.raises(MigrationError, match="recorded as 'renamed'"):
        runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)


def test_tampered_checksum_is_refused_not_accepted():
    d = _migrated(1)
    d.execute("UPDATE schema_migrations SET checksum = ? WHERE version = 1", ("0" * 64,))
    with pytest.raises(MigrationError, match="changed after it was applied"):
        runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)


def test_ledger_gap_is_refused():
    d = _migrated(2)
    d.execute("DELETE FROM schema_migrations WHERE version = 1")  # the test forges a gap on purpose
    with pytest.raises(MigrationError, match="gap or is out of order"):
        runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)


def test_unknown_ledger_version_is_refused():
    d = _migrated(1)
    d.execute("INSERT INTO schema_migrations VALUES (9, 'foreign', ?, '2026-11-10', 'applied')", ("9" * 64,))
    with pytest.raises(MigrationError, match="not in the repository"):
        runner.migrate(d, dry_run=True, directory=gate.ARCHIVE_DIR)


# ------------------------------------------------------------------ unknown and modified objects

def test_unknown_trigger_or_index_refuses_the_database():
    d = RecordingDB()
    d.execute("CREATE TABLE foreign_marker (x INTEGER)")
    with pytest.raises(DatabaseConfigError, match="unknown schema objects"):
        gate.apply(d, dry_run=True)
    d2 = _migrated(4)
    d2.execute("CREATE INDEX ix_foreign ON archive_reports(company_id)")
    with pytest.raises(DatabaseConfigError, match="ix_foreign"):
        gate.apply(d2, dry_run=True)


def test_a_missing_trigger_is_detected_as_drift_and_blocks_apply():
    d = _migrated(4)
    d.execute("DROP TRIGGER trg_archive_tuples_no_update")
    p = gate.probe(d)
    assert p["fully_migrated"] is False
    assert "trg_archive_tuples_no_update" in p["structure_drift_for_ledger_state"]["triggers"]["missing"]
    with pytest.raises(gate.SchemaDrift, match="pre-state drift"):
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)


def test_partial_migration_without_ledger_row_is_detected():
    d = RecordingDB()
    for s in gate._migrations(1)[0].statements():  # objects of 0001 exist, ledger does not record them
        d.execute(s)
    with pytest.raises(gate.SchemaDrift, match="pre-state drift"):
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)


def test_post_apply_drift_stops_and_does_not_retry(monkeypatch):
    d = RecordingDB()

    def only_first(adb, directory):  # simulate an interrupted run that applies only 0001
        m = gate._migrations(1)[0]
        for s in m.statements():
            adb.execute(s)
        return ["apply  0001 (interrupted after one migration)"]

    monkeypatch.setattr(gate, "migrate", only_first)
    with pytest.raises(gate.SchemaDrift, match="post-state drift"):
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)


# ------------------------------------------------------------------ approval, purpose and role

@pytest.mark.parametrize("env", [
    {}, {gate.DDL_OPT_IN_VAR: "yes"}, {gate.DDL_OPT_IN_VAR: " yes-execute-archive-migration-ddl"},
    {gate.DDL_OPT_IN_VAR: "YES-EXECUTE-ARCHIVE-MIGRATION-DDL"},
    {"PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL": "yes-execute-migration-ddl"},  # the operational approval
])
def test_only_the_exact_archive_approval_string_permits_ddl(env):
    d = RecordingDB()
    with pytest.raises(gate.ArchiveDDLRefused):
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=env)
    assert _raw_objects(d) == []
    assert not any(WRITE.match(x) for x in d.statements)


def test_ddl_needs_an_explicit_archive_purpose_and_role():
    d = RecordingDB()
    with pytest.raises(gate.ArchiveDDLRefused, match="purpose"):
        gate.apply(d, dry_run=False, purpose="", env=APPROVED)
    d.role = "main"
    with pytest.raises(gate.ArchiveDDLRefused, match="archive role"):
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)
    assert _raw_objects(d) == []


def test_approval_value_is_never_echoed_in_a_refusal():
    d = RecordingDB()
    with pytest.raises(gate.ArchiveDDLRefused) as exc:
        gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: "nope-secret-value"})
    assert "nope-secret-value" not in str(exc.value) and gate.DDL_OPT_IN_VALUE not in str(exc.value)


def test_approved_apply_on_a_clean_database_migrates_and_is_idempotent():
    d = RecordingDB()
    out = gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)
    assert out["mode"] == "applied" and len(out["log"]) == 8
    assert gate.probe(d)["fully_migrated"] is True
    d.statements.clear()
    again = gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env=APPROVED)
    assert again["log"] == [] and not any(WRITE.match(x) for x in d.statements)
