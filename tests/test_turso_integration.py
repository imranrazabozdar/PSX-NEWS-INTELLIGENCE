"""Integration tests against this project's real Turso database.

They run only when PSXNI_TURSO_DATABASE_URL is set (and a token is available). In CI without
secrets they are skipped, never faked. Writes run inside batches that are always rolled
back, so the tests leave no data behind.
"""

from __future__ import annotations

import os

import pytest

from database.connection import DatabaseError, TursoHTTPDatabase, connect
from database.migrate import discover
from tests.turso_guard import OPT_IN_VALUE, OPT_IN_VAR, pending_migration_ddl_permitted

pytestmark = pytest.mark.skipif(
    not os.environ.get("PSXNI_TURSO_DATABASE_URL", "").startswith(("libsql://", "https://")),
    reason="PSXNI_TURSO_DATABASE_URL not set: Turso integration tests not run")


@pytest.fixture(scope="module")
def db():
    d = connect()
    assert isinstance(d, TursoHTTPDatabase)
    return d


def test_connection_and_foreign_keys(db):
    info = db.validate()
    assert info["backend"] == "turso" and info["foreign_keys"] is True


def test_all_migrations_applied_with_matching_checksums(db):
    """Applied migrations match the repository. Migrations added by an unmerged branch are
    verified on Turso inside a rolled-back batch, so production is never migrated early."""
    applied = {r["version"]: r["checksum"] for r in db.execute(
        "SELECT version, checksum FROM schema_migrations")}
    repo = {m.version: m for m in discover()}
    assert applied, "no migrations applied"
    assert set(applied) <= set(repo), "database has migrations unknown to this branch"
    assert all(applied[v] == repo[v].checksum for v in applied)
    assert sorted(applied) == list(range(1, len(applied) + 1))
    pending = [repo[v] for v in sorted(repo) if v not in applied]
    if pending and not pending_migration_ddl_permitted(os.environ):
        pytest.skip(f"{len(pending)} pending migration(s) not executed: set {OPT_IN_VAR}={OPT_IN_VALUE} "
                    "to run their DDL inside a rolled-back batch (never set in CI)")
    if pending:
        stmts = [(s, ()) for m in pending for s in m.statements()]
        stmts.append(("SELECT COUNT(*) AS n FROM sqlite_master WHERE name = 'collector_checkpoints'", ()))
        rows = db.batch(stmts, rollback=True)
        assert rows[-1][0]["n"] == 1
        left = db.execute("SELECT COUNT(*) AS n FROM sqlite_master WHERE name = 'collector_checkpoints'")
        assert left[0]["n"] == 0  # rolled back: production schema unchanged


def test_reference_data_present(db):
    r = db.execute("SELECT (SELECT COUNT(*) FROM companies WHERE listing_status='listed') listed, "
                   "(SELECT COUNT(*) FROM index_memberships WHERE index_code='KSE30') kse30, "
                   "(SELECT COUNT(*) FROM sources WHERE enabled=1) enabled")[0]
    assert r["listed"] == 50 and r["kse30"] == 30 and r["enabled"] == 0


def test_store_and_retrieve_source_event_evidence(db):
    rows = db.batch([
        ("INSERT INTO source_items(source_id, canonical_url, collected_at_utc, content_sha256) "
         "VALUES ('psx', 'https://psx.com.pk/integration-test', '2026-11-07T00:00:00Z', ?)", ("a" * 64,)),
        ("SELECT last_insert_rowid() AS item_id", ()),
        ("INSERT INTO events(event_type, headline, status_stage, first_seen_at_utc, created_at_utc, "
         "updated_at_utc) VALUES ('test','integration','proposal','2026-11-07T00:00:00Z',"
         "'2026-11-07T00:00:00Z','2026-11-07T00:00:00Z')", ()),
        ("INSERT INTO event_evidence(event_id, source_item_id, claim, claim_type, relation, excerpt, "
         "recorded_at_utc, recorded_by) VALUES (last_insert_rowid(), "
         "(SELECT source_item_id FROM source_items WHERE canonical_url='https://psx.com.pk/integration-test'),"
         " 'claim', 'official_statement', 'supports', 'excerpt', '2026-11-07T00:00:00Z', 'test')", ()),
        ("SELECT e.claim, s.canonical_url, src.name FROM event_evidence e JOIN source_items s "
         "USING(source_item_id) JOIN sources src ON src.source_id = s.source_id "
         "WHERE s.canonical_url = 'https://psx.com.pk/integration-test'", ()),
    ], rollback=True)
    assert rows[4] == [{"claim": "claim", "canonical_url": "https://psx.com.pk/integration-test",
                        "name": "Pakistan Stock Exchange - announcements and notices"}]
    left = db.execute("SELECT COUNT(*) n FROM source_items WHERE canonical_url = "
                      "'https://psx.com.pk/integration-test'")
    assert left[0]["n"] == 0  # rolled back


def test_constraints_enforced_on_turso(db):
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        db.batch([("INSERT INTO company_aliases(company_id, alias, alias_normalized, alias_type, "
                   "confidence) VALUES ('cmp-nope','x','x','ticker','verified')", ())], rollback=True)
    with pytest.raises(DatabaseError, match="append-only"):
        db.batch([("DELETE FROM company_status_history", ())], rollback=True)
    with pytest.raises(DatabaseError, match="CHECK"):
        db.batch([("UPDATE sources SET enabled = 1 WHERE source_id = 'dawn'", ())], rollback=True)


def test_point_in_time_lookup_on_turso(db):
    rows = db.execute("SELECT c.company_id FROM company_identifiers i JOIN companies c "
                      "USING(company_id) WHERE i.value='FFBL' AND i.valid_to >= '2024-06-01'")
    assert rows == [{"company_id": "cmp-ffbl"}]
