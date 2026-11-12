"""A2 rehearsal harness: retire foreign migration version 11 (extraction_reviews), then run 0011-0014.

Two legs, same assertions:
* sqlite : always runs (CI). Uses the repository's own migration runner on an in-memory SQLite database.
* turso  : runs only against a FRESH disposable Turso database (PSXNI_TURSO_DISPOSABLE_*;
  tests/turso_guard.py refuses production by host, marker and token). The database must be empty: this
  module builds the colliding state itself (migrations 1-10, then the foreign version 11). Do NOT run it on
  the database used by the other gate-3 modules. Delete the database afterwards.

Tests are ordered and stateful (the same database moves through the scenario): run the module as a whole.
The negative tests run inside batches that always fail and roll back, so they leave nothing behind.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3

import pytest

from database.connection import Database, DatabaseError, SQLiteDatabase, TursoHTTPDatabase
from database.migrate import MIGRATIONS_DIR, MigrationError, migrate, split_statements
from engines import integrity
from scripts import remediate_migration_collision_a2 as a2
from tests.turso_guard import DISPOSABLE_TOKEN_VAR, DISPOSABLE_URL_VAR, disposable_config_status

_STATUS, _REASON = disposable_config_status(os.environ)
FOREIGN_APPLIED_AT = "2026-11-09T14:28:47Z"
# Independent pin of the checksum recorded in production for version 11. Do not "fix" a failure by editing it:
# a change here or in the script means the migration being retired is no longer the one that was applied.
RECORDED_CHECKSUM = "a9b55ef930503e72fa6cf8ff86f9611683f76c4c60767cdd6ccbb582ebc04c39"
NOW = "2026-11-09T00:00:00Z"

# The foreign migration, verbatim as it was applied (its SHA-256 is asserted below).
FOREIGN_SQL = """-- PROPOSED (not applied to production): records human review decisions on model candidates.
-- event_extractions is append-only by trigger, so decisions cannot be stored on the candidate row itself.
-- Statements are separated by the marker line below so the runner can send them one by one (trigger bodies contain ';').
CREATE TABLE extraction_reviews (
    review_id       INTEGER PRIMARY KEY,
    extraction_id   INTEGER NOT NULL REFERENCES event_extractions(extraction_id),
    decision        TEXT NOT NULL CHECK (decision IN ('accept','reject','needs_more_evidence')),
    reviewer        TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes           TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    event_id        INTEGER REFERENCES events(event_id),
    decided_at_utc  TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    CHECK ((decision = 'accept') = (event_id IS NOT NULL))
);
-- statement-break

CREATE INDEX ix_extraction_reviews_extraction ON extraction_reviews(extraction_id, review_id);
-- statement-break

CREATE TRIGGER trg_extraction_reviews_no_update BEFORE UPDATE ON extraction_reviews
BEGIN SELECT RAISE(ABORT, 'extraction_reviews are append-only: record a new decision instead'); END;
-- statement-break

CREATE TRIGGER trg_extraction_reviews_no_delete BEFORE DELETE ON extraction_reviews
BEGIN SELECT RAISE(ABORT, 'extraction_reviews are append-only'); END;
-- statement-break

CREATE VIEW v_review_queue AS
SELECT e.extraction_id, e.source_item_id, e.created_at_utc, e.model, e.schema_version, e.confidence, e.extracted_json
FROM event_extractions e
WHERE e.needs_human_review = 1
  AND COALESCE((SELECT r.decision FROM extraction_reviews r WHERE r.extraction_id = e.extraction_id
                ORDER BY r.review_id DESC LIMIT 1), 'needs_more_evidence') = 'needs_more_evidence';
"""  # noqa: E501


def _migrations_1_to_10(tmp_path):
    for p in MIGRATIONS_DIR.glob("*.sql"):
        if int(p.name[:4]) <= 10:
            shutil.copy(p, tmp_path / p.name)
    return tmp_path


def _build_collision_state(d: Database, directory) -> None:
    """Production-equivalent state: migrations 1-10, then the foreign version 11 and its ledger row."""
    migrate(d, directory=_migrations_1_to_10(directory))
    ledger_row = ("INSERT INTO schema_migrations(version, name, checksum, applied_at_utc, result) "
                  "VALUES (11, 'extraction_reviews', ?, ?, 'applied')",
                  (a2.FOREIGN_CHECKSUM, FOREIGN_APPLIED_AT))
    d.batch([(s, ()) for s in split_statements(FOREIGN_SQL)] + [ledger_row])


@pytest.fixture(scope="module", params=["sqlite", "turso"])
def db(request, tmp_path_factory) -> Database:
    if request.param == "sqlite":
        d: Database = SQLiteDatabase(":memory:")
    else:
        if _STATUS == "skip":
            pytest.skip(_REASON)
        if _STATUS != "ok":
            pytest.fail(_REASON)
        refusal = a2.target_problem("disposable", os.environ)    # allow-list: psxni-migration-rehearsal-*
        if refusal:
            pytest.fail(refusal)
        d = TursoHTTPDatabase(os.environ[DISPOSABLE_URL_VAR].strip(),
                              os.environ[DISPOSABLE_TOKEN_VAR].strip())
        if d.execute("SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table'")[0]["n"]:
            pytest.fail("the A2 rehearsal needs a FRESH, empty disposable database "
                        "(see the module docstring)")
    _build_collision_state(d, tmp_path_factory.mktemp("migrations_1_10"))
    return d


def _decision_row_statements():
    """A valid source -> item -> candidate -> decision chain (foreign keys are enforced on both legs)."""
    return [
        ("INSERT INTO sources(source_id, name, source_type, created_at_utc, updated_at_utc) "
         "VALUES ('rehearsal_src', 'rehearsal', 'other', ?, ?)", (NOW, NOW)),
        ("INSERT INTO source_items(source_id, external_id, collected_at_utc, content_sha256) "
         "VALUES ('rehearsal_src', 'r1', ?, ?)", (NOW, "a" * 64)),
        ("INSERT INTO event_extractions(source_item_id, schema_version, prompt_version, model, "
         "extracted_json, confidence_explanation, needs_human_review, review_reasons_json, "
         "provenance_json, created_at_utc) VALUES ((SELECT MAX(source_item_id) FROM source_items), "
         "'s', 'p', 'm', '{}', 'x', 1, '[]', '{}', ?)", (NOW,)),
        ("INSERT INTO extraction_reviews(extraction_id, decision, reviewer, notes, event_id, "
         "decided_at_utc) VALUES ((SELECT MAX(extraction_id) FROM event_extractions), 'reject', "
         "'Rehearsal', 'guard test', NULL, ?)", (NOW,)),
    ]


def _state(db: Database):
    return (a2.table_counts(db), [r["version"] for r in db.execute("SELECT version FROM schema_migrations")])


def _host_of(url):
    return url.split("://", 1)[-1]


def test_00_embedded_foreign_migration_is_the_recorded_one():
    assert hashlib.sha256(FOREIGN_SQL.encode()).hexdigest() == RECORDED_CHECKSUM
    assert a2.FOREIGN_CHECKSUM == RECORDED_CHECKSUM
    assert len(split_statements(FOREIGN_SQL)) == 5


def test_01_collision_is_reproduced_by_the_runner_and_the_integrity_check(db):
    for kwargs in ({"dry_run": True}, {}):
        # the name check now refuses the foreign version-11 record before the checksum check is reached
        with pytest.raises(MigrationError, match=r"migration 11 is recorded as 'extraction_reviews'"):
            migrate(db, **kwargs)
    report = integrity.check(db)
    assert report["state"] == "problems"
    assert any("migration 11 (extraction_reviews) checksum differs" in p for p in report["problems"])


def test_02_preflight_is_clean_and_predicts_the_post_flight_digest(db):
    pre = a2.preflight(db)
    assert pre["problems"] == [] and pre["extraction_reviews_rows"] == 0
    assert pre["ledger_versions"] == list(range(1, 12))
    assert a2.expected_post_counts(pre["counts"])["schema_migrations"] == 10
    assert pre["digest"] != pre["expected_post_digest"]


def test_03_dry_run_and_incomplete_execute_change_nothing(db):
    before = _state(db)
    assert a2.run(db)["status"] == "dry_run_ok"
    ok = {"confirm": a2.CONFIRM_PHRASE, "backup_sha256": "f" * 64, "approval_id": "A-1"}
    # each variant is complete EXCEPT one requirement, so every requirement is tested on its own
    for kwargs in ({**ok, "confirm": "yes"}, {**ok, "confirm": ""}, {**ok, "backup_sha256": "f" * 63},
                   {**ok, "backup_sha256": "F" * 64}, {**ok, "backup_sha256": ""}, {**ok, "approval_id": " "},
                   {"confirm": a2.CONFIRM_PHRASE}):
        assert a2.run(db, execute=True, **kwargs)["status"] == "refused"
    stale = a2.run(db, expect_pre_digest="0" * 64)    # simulates: the database moved since the snapshot
    assert stale["status"] == "refused"
    assert _state(db) == before


def test_04_guard_aborts_and_rolls_back_when_a_decision_row_exists(db):
    before = _state(db)
    with pytest.raises(DatabaseError):
        db.batch(_decision_row_statements() + a2.remediation_statements(), transactional=True)
    assert _state(db) == before                        # the inserted chain rolled back with everything else


def test_05_guard_aborts_on_a_wrong_checksum(db):
    before = _state(db)
    with pytest.raises(DatabaseError):
        db.batch(a2.remediation_statements("0" * 64), transactional=True)
    assert _state(db) == before


def test_06_guard_aborts_when_a_higher_version_exists(db):
    before = _state(db)
    with pytest.raises(DatabaseError):
        db.batch([("INSERT INTO schema_migrations(version, name, checksum, applied_at_utc, result) "
                   "VALUES (12, 'x', ?, ?, 'applied')", ("1" * 64, NOW))] + a2.remediation_statements(),
                 transactional=True)
    assert _state(db) == before


def test_07_remediation_executes_and_verifies(db):
    report = a2.run(db, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64,
                    approval_id="REHEARSAL")
    assert report["status"] == "remediated_verified", report
    post = report["postflight"]
    assert post["problems"] == [] and post["ledger_versions"] == list(range(1, 11))
    assert post["runner_would_apply"] == [
        "0011_financial_documents", "0012_assessments_and_valuations",
        "0013_macro_series", "0014_validation_and_reports", "0015_psx_announcements",
        "0016_psx_financial_results"]
    assert post["integrity_state"] == "ok" and post["digest_matches_expected"] is True
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%extraction_reviews%' "
                          "OR name IN ('v_review_queue', '_a2_guard')")


def test_08_second_run_is_refused_and_a_direct_replay_aborts(db):
    before = _state(db)
    assert a2.run(db, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64,
                  approval_id="REHEARSAL")["status"] == "refused"
    with pytest.raises((DatabaseError, sqlite3.Error)):
        db.batch(a2.remediation_statements(), transactional=True)
    assert _state(db) == before


def test_09_repository_migrations_then_apply_and_rerun_is_a_noop(db):
    log = migrate(db)
    assert [line.split()[1] for line in log if line.startswith("apply")] == [
        "0011_financial_documents", "0012_assessments_and_valuations", "0013_macro_series",
        "0014_validation_and_reports", "0015_psx_announcements", "0016_psx_financial_results"]
    assert all(line.startswith("skip") for line in migrate(db))
    assert integrity.check(db)["state"] == "ok"
    assert db.execute("PRAGMA foreign_key_check") == []


def test_10_the_script_refuses_production_as_a_disposable_target(monkeypatch):
    prod = "libsql://psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io"
    env = {DISPOSABLE_URL_VAR: prod, DISPOSABLE_TOKEN_VAR: "x"}
    assert disposable_config_status(env)[0] == "fail"           # the gate the Turso leg relies on
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", prod)
    assert a2.target_problem("disposable", os.environ)           # refused by the allow-list and the deny-list
    assert a2.target_problem("production", {"PSXNI_TURSO_DATABASE_URL": prod}) == ""
    other = {"PSXNI_TURSO_DISPOSABLE_DATABASE_URL": "libsql://some-other-db-org.aws-us-east-1.turso.io",
             "PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN": "x"}
    # not production, but not a rehearsal database either: refused by the allow-list
    assert "must start with" in a2.target_problem("disposable", other)
    good = {**other, "PSXNI_TURSO_DISPOSABLE_DATABASE_URL":
            "libsql://psxni-migration-rehearsal-20261110-org.aws-us-east-1.turso.io"}
    assert a2.target_problem("disposable", good) == ""
    reused_token = {**good, "PSXNI_TURSO_AUTH_TOKEN": "x"}                 # same token as the disposable one
    assert "token equals the production token" in a2.target_problem("disposable", reused_token)
    same_host = {**good, "PSXNI_TURSO_DATABASE_URL": good["PSXNI_TURSO_DISPOSABLE_DATABASE_URL"]}
    assert "production database" in a2.target_problem("disposable", same_host)
    odd = {**other, "PSXNI_TURSO_DISPOSABLE_DATABASE_URL": "libsql://odd-name-org.aws-us-east-1.turso.io"}
    host = "odd-name-org.aws-us-east-1.turso.io"
    assert a2.target_problem("disposable", {**odd, a2.HOST_OVERRIDE_VAR: host}) == ""      # exact host only
    assert "exactly" in a2.target_problem("disposable", {**odd, a2.HOST_OVERRIDE_VAR: "other.turso.io"})
    prod_env = {**odd, "PSXNI_TURSO_DATABASE_URL": odd["PSXNI_TURSO_DISPOSABLE_DATABASE_URL"],
                a2.HOST_OVERRIDE_VAR: host}
    assert "production database" in a2.target_problem("disposable", prod_env)         # deny-list still wins
    prod_host = {**prod_env, "PSXNI_TURSO_DISPOSABLE_DATABASE_URL": prod,
                 a2.HOST_OVERRIDE_VAR: _host_of(prod)}
    assert "production database" in a2.target_problem("disposable", prod_host)
    with pytest.raises(SystemExit):
        a2.main([])                                              # --target is required


def test_11_read_budget_is_estimated_and_refused_before_anything_runs(tmp_path):
    class Tight(SQLiteDatabase):
        max_rows_read = 5                                   # stands in for the driver's per-run read budget

    d = Tight(":memory:")                                   # a private database: never the shared one
    _build_collision_state(d, tmp_path)
    assert any("read budget" in p for p in a2.preflight(d)["problems"])
    report = a2.run(d, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64, approval_id="A")
    assert report["status"] == "refused"
    assert d.execute("SELECT 1 FROM schema_migrations WHERE version = 11")      # nothing ran


def test_12_post_flight_failure_after_commit_is_reported_not_raised(tmp_path, monkeypatch):
    d = SQLiteDatabase(":memory:")                          # a private database: never the shared one
    _build_collision_state(d, tmp_path)

    def boom(*_args, **_kwargs):
        raise DatabaseError("per-run database budget exhausted")

    monkeypatch.setattr(a2, "postflight", boom)
    report = a2.run(d, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64, approval_id="A")
    assert report["status"] == "remediated_check_failed" and "did not finish" in report["error"]
    # the change DID commit even though verification could not finish
    assert not d.execute("SELECT 1 FROM sqlite_master WHERE name = 'extraction_reviews'")


def test_13_failed_guard_leaves_no_guard_table_and_no_partial_change(tmp_path):
    d = SQLiteDatabase(":memory:")
    _build_collision_state(d, tmp_path)
    before = a2.table_counts(d)
    with pytest.raises(DatabaseError):
        d.batch(a2.remediation_statements("0" * 64), transactional=True)    # wrong checksum: guard fails
    assert not d.execute("SELECT 1 FROM sqlite_master WHERE name = '_a2_guard'")
    assert a2.table_counts(d) == before
    assert d.execute("SELECT 1 FROM schema_migrations WHERE version = 11")
    assert len(d.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%extraction_reviews%' "
                         "OR name = 'v_review_queue'")) == 5


def test_14_leftover_guard_table_is_refused_by_preflight(tmp_path):
    d = SQLiteDatabase(":memory:")
    _build_collision_state(d, tmp_path)
    d.execute("CREATE TABLE _a2_guard(ok INTEGER)")
    assert any("_a2_guard" in p for p in a2.preflight(d)["problems"])


def test_15_verify_only_confirms_a_remediated_database_and_rejects_others(tmp_path):
    d = SQLiteDatabase(":memory:")
    _build_collision_state(d, tmp_path)
    pre = a2.preflight(d)
    assert a2.verify_only(d, "bad")["status"] == "refused"
    assert a2.verify_only(d, pre["expected_post_digest"])["status"] == "verify_failed"   # not remediated yet
    report = a2.run(d, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64, approval_id="A")
    assert report["status"] == "remediated_verified"
    assert a2.verify_only(d, pre["expected_post_digest"])["status"] == "verified"
    assert a2.verify_only(d, "0" * 64)["status"] == "verify_failed"


def test_16_budget_exhausted_after_commit_is_never_reported_as_verified(tmp_path):
    class Budgeted(SQLiteDatabase):
        max_rows_read = 10_000
        used = 0
        armed = False

        def usage(self):
            return {"requests": 0, "rows_read": self.used, "rows_written": 0}

        def batch(self, statements, transactional=True):
            result = super().batch(statements, transactional=transactional)
            if transactional and self.armed:
                self.used = self.max_rows_read              # the remediation consumed the whole budget
                self.exhausted = True
            return result

        def execute(self, sql, params=()):
            if getattr(self, "exhausted", False):
                raise DatabaseError("per-run database budget exhausted")
            return super().execute(sql, params)

    d = Budgeted(":memory:")
    _build_collision_state(d, tmp_path)
    d.armed = True
    report = a2.run(d, execute=True, confirm=a2.CONFIRM_PHRASE, backup_sha256="f" * 64, approval_id="A")
    assert report["status"] == "remediated_check_failed"
    assert "COMMITTED" in report["error"] and "--verify-only" in report["error"]
    assert report["status"] != "remediated_verified"
