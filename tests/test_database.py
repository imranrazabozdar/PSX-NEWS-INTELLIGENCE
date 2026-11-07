"""Phase 1 database tests on local SQLite (same SQL as Turso; see test_turso_integration.py)."""

from __future__ import annotations

import json
import shutil

import pytest

from database import repositories as repo
from database import seed_loader
from database.canonical import content_sha256
from database.connection import DatabaseConfigError, DatabaseError, SQLiteDatabase, connect
from database.migrate import MIGRATIONS_DIR, MigrationError, discover, migrate, split_statements
from database.validation import validate_company_seed, validate_media_watchlist

SPEC_TABLES = {
    "companies", "company_aliases", "company_segments", "sources", "source_items", "events",
    "event_revisions", "event_evidence", "event_companies", "company_exposures",
    "financial_metrics", "sector_metrics", "commodity_prices", "funds", "fund_holdings",
    "research_views", "analyses", "alerts_predictions", "market_outcomes", "media_accounts",
    "media_items", "media_mentions", "media_event_links", "media_predictions",
    "media_metrics_history", "collector_runs", "user_watchlist", "schema_migrations",
}


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    yield d
    d.close()


@pytest.fixture
def seeded(db):
    seed_loader.load(db)
    return db


def _item(db, url="https://example.com/a", text="hello world", source="psx"):
    return repo.record_source_item(db, source_id=source, url=url, content=text,
                                   collected_at_utc="2026-11-07T10:00:00Z")


# ---------------------------------------------------------------- connection
def test_validate_reports_foreign_keys(db):
    info = db.validate()
    assert info["foreign_keys"] is True and info["backend"] == "sqlite"


def test_connect_requires_configuration(monkeypatch):
    monkeypatch.delenv("PSXNI_TURSO_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigError):
        connect()
    with pytest.raises(DatabaseConfigError):
        connect("postgres://x")
    with pytest.raises(DatabaseConfigError):
        connect("libsql://example.turso.io", auth_token="")


def test_connect_ignores_unprefixed_turso_variables(monkeypatch):
    monkeypatch.delenv("PSXNI_TURSO_DATABASE_URL", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://someone-else.turso.io")
    with pytest.raises(DatabaseConfigError):
        connect()


def test_failed_batch_rolls_back(db):
    with pytest.raises(DatabaseError):
        db.batch([("INSERT INTO user_watchlist(item_type, value, created_at_utc) "
                   "VALUES ('ticker','OGDC','2026-11-07T00:00:00Z')", ()),
                  ("INSERT INTO user_watchlist(item_type, value, created_at_utc) "
                   "VALUES ('bogus','X','2026-11-07T00:00:00Z')", ())])
    assert db.execute("SELECT COUNT(*) n FROM user_watchlist")[0]["n"] == 0


def test_rollback_batch_leaves_no_data(db):
    rows = db.batch([("INSERT INTO user_watchlist(item_type, value, created_at_utc) "
                      "VALUES ('ticker','OGDC','2026-11-07T00:00:00Z')", ()),
                     ("SELECT COUNT(*) n FROM user_watchlist", ())], rollback=True)
    assert rows[1][0]["n"] == 1
    assert db.execute("SELECT COUNT(*) n FROM user_watchlist")[0]["n"] == 0


# ---------------------------------------------------------------- migrations
def test_all_spec_tables_exist(db):
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert SPEC_TABLES <= names


def test_migrations_are_idempotent(db):
    log = migrate(db)
    assert all(line.startswith("skip") for line in log)
    assert db.execute("SELECT COUNT(*) n FROM schema_migrations")[0]["n"] == len(discover())


def test_changed_applied_migration_is_refused(db, tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS_DIR, d)
    f = sorted(d.glob("0001_*.sql"))[0]
    f.write_text(f.read_text() + "\n-- edited\n")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        migrate(db, directory=d)


def test_destructive_migration_is_refused(tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS_DIR, d)
    (d / "0005_bad.sql").write_text("DROP TABLE companies;\n")
    with pytest.raises(MigrationError, match="destructive"):
        discover(d)


def test_failed_migration_applies_nothing(tmp_path):
    d = tmp_path / "m"
    shutil.copytree(MIGRATIONS_DIR, d)
    (d / "0005_broken.sql").write_text("CREATE TABLE ok_one (x INTEGER);\nCREATE TABLE broken (;\n")
    db = SQLiteDatabase()
    with pytest.raises(DatabaseError):
        migrate(db, directory=d)
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok_one" not in names
    assert db.execute("SELECT MAX(version) v FROM schema_migrations")[0]["v"] == 4


def test_splitter_keeps_triggers_whole():
    stmts = split_statements("CREATE TABLE t(x);\nCREATE TRIGGER g BEFORE DELETE ON t\n"
                             "BEGIN SELECT RAISE(ABORT, 'no; really'); END;\n")
    assert len(stmts) == 2 and stmts[1].endswith("END")


def test_expected_indexes_exist(db):
    idx = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for name in ("ix_source_items_published", "ix_source_items_collected", "ix_source_items_hash",
                 "ux_identifiers_current", "ix_aliases_normalized", "ix_events_date",
                 "ix_events_stage", "ix_evidence_event", "ux_media_accounts_handle"):
        assert name in idx


# ---------------------------------------------------------------- constraints
def test_foreign_keys_enforced(db):
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        db.execute("INSERT INTO company_aliases(company_id, alias, alias_normalized, alias_type, "
                   "confidence) VALUES ('cmp-nope','x','x','ticker','verified')")


def test_source_cannot_be_enabled_before_verification(seeded):
    with pytest.raises(DatabaseError, match="CHECK"):
        seeded.execute("UPDATE sources SET enabled = 1 WHERE source_id = 'dawn'")


def test_unverified_media_account_cannot_be_activated(seeded):
    with pytest.raises(DatabaseError, match="CHECK"):
        seeded.execute("UPDATE media_accounts SET monitoring_status='active' WHERE handle='CNN'")


def test_invalid_event_stage_rejected(db):
    with pytest.raises(DatabaseError, match="CHECK"):
        repo.create_event(db, {"event_type": "policy", "headline": "h", "status_stage": "done"},
                          changed_by="test")


# ---------------------------------------------------------------- source items / dedup / provenance
def test_source_item_dedup_and_versioning(seeded):
    a = _item(seeded, "https://Example.com/a/?utm_source=x&b=2&a=1#frag", "Price  raised")
    assert a.outcome == "inserted"
    same = _item(seeded, "https://example.com/a?a=1&b=2", "Price raised")
    assert (same.source_item_id, same.outcome) == (a.source_item_id, "unchanged")
    changed = _item(seeded, "https://example.com/a?a=1&b=2", "Price raised again")
    assert (changed.source_item_id, changed.outcome) == (a.source_item_id, "new_version")
    versions = seeded.execute("SELECT version_no FROM source_item_versions WHERE source_item_id=? "
                              "ORDER BY version_no", (a.source_item_id,))
    assert [v["version_no"] for v in versions] == [1, 2]
    original = seeded.execute("SELECT content_sha256 FROM source_items WHERE source_item_id=?",
                              (a.source_item_id,))[0]["content_sha256"]
    assert original == content_sha256("Price raised")


def test_syndicated_copy_is_flagged_duplicate(seeded):
    first = _item(seeded, "https://example.com/x", "same story", source="dawn")
    copy = _item(seeded, "https://other.example/y", "same   story", source="brecorder")
    assert copy.outcome == "duplicate_content"
    row = seeded.execute("SELECT duplicate_of_item_id d FROM source_items WHERE source_item_id=?",
                         (copy.source_item_id,))[0]
    assert row["d"] == first.source_item_id


def test_source_item_provenance_is_immutable(seeded):
    a = _item(seeded)
    for sql in ("UPDATE source_items SET content_sha256 = ? WHERE source_item_id = ?",
                "UPDATE source_items SET canonical_url = ? WHERE source_item_id = ?"):
        with pytest.raises(DatabaseError, match="immutable"):
            seeded.execute(sql, ("0" * 64, a.source_item_id))
    with pytest.raises(DatabaseError, match="append-only"):
        seeded.execute("DELETE FROM source_items WHERE source_item_id = ?", (a.source_item_id,))


# ---------------------------------------------------------------- events / evidence
def _event(db):
    return repo.create_event(db, {"event_type": "policy", "headline": "Tariff proposal",
                                  "status_stage": "proposal", "event_date": "2026-11-05"},
                             changed_by="test")


def test_event_revisions_preserve_history(seeded):
    eid = _event(seeded)
    rev = repo.revise_event(seeded, eid, {"status_stage": "approval"}, reason="ECC approved",
                            changed_by="test")
    assert rev == 2
    hist = repo.event_history(seeded, eid)
    assert [h["status_stage"] for h in hist] == ["proposal", "approval"]
    assert json.loads(hist[0]["snapshot_json"])["status_stage"] == "proposal"
    with pytest.raises(DatabaseError, match="append-only"):
        seeded.execute("UPDATE event_revisions SET status_stage='rumour' WHERE event_id=?", (eid,))


def test_event_cannot_be_changed_without_revision(seeded):
    eid = _event(seeded)
    with pytest.raises(DatabaseError, match="new recorded revision"):
        seeded.execute("UPDATE events SET status_stage='approval' WHERE event_id=?", (eid,))
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        seeded.execute("DELETE FROM events WHERE event_id=?", (eid,))


def test_evidence_links_claims_to_sources(seeded):
    eid = _event(seeded)
    item = _item(seeded, "https://psx.com.pk/notice/1", "Board meeting notice")
    ev1 = repo.add_evidence(seeded, event_id=eid, source_item_id=item.source_item_id,
                            claim="A proposal was published", claim_type="official_statement",
                            relation="supports", excerpt="Board meeting notice",
                            recorded_by="test")
    ev2 = repo.add_evidence(seeded, event_id=eid, source_item_id=item.source_item_id,
                            claim="A proposal was published", claim_type="official_statement",
                            relation="supports", excerpt="Board meeting notice",
                            recorded_by="test")
    assert ev1 == ev2  # idempotent
    full = repo.event_with_evidence(seeded, eid)
    assert full["evidence"][0]["canonical_url"] == "https://psx.com.pk/notice/1"
    assert full["evidence"][0]["source_name"].startswith("Pakistan Stock Exchange")
    with pytest.raises(DatabaseError, match="append-only"):
        seeded.execute("UPDATE event_evidence SET excerpt='changed' WHERE evidence_id=?", (ev1,))


def test_evidence_requires_existing_source_item(seeded):
    eid = _event(seeded)
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        repo.add_evidence(seeded, event_id=eid, source_item_id=99999, claim="c",
                          claim_type="rumour", relation="supports", excerpt="x", recorded_by="t")


# ---------------------------------------------------------------- company master
def test_company_master_loaded(seeded):
    n = seeded.execute("SELECT listing_status, COUNT(*) n FROM companies GROUP BY listing_status")
    assert {r["listing_status"]: r["n"] for r in n} == {"listed": 50, "delisted": 1}
    assert seeded.execute("SELECT COUNT(*) n FROM index_memberships WHERE index_code='KSE30'")[0]["n"] == 30
    missing = seeded.execute("SELECT company_id FROM companies WHERE profile_source_item_id IS NULL")
    assert missing == []


def test_point_in_time_ticker_and_delisting(seeded):
    assert repo.company_by_ticker(seeded, "OGDC")["company_id"] == "cmp-ogdc"
    assert repo.company_by_ticker(seeded, "FFBL") is None  # not current
    assert repo.company_by_ticker(seeded, "FFBL", as_of="2024-06-01")["company_id"] == "cmp-ffbl"
    hist = seeded.execute("SELECT status, related_company_id FROM company_status_history "
                          "WHERE company_id='cmp-ffbl' ORDER BY status")
    assert {h["status"]: h["related_company_id"] for h in hist} == {
        "delisted": None, "merged_into": "cmp-ffc"}


def test_one_current_holder_per_ticker(seeded):
    with pytest.raises(DatabaseError, match="UNIQUE"):
        seeded.execute("INSERT INTO company_identifiers(company_id, id_type, value, verified_at_utc) "
                       "VALUES ('cmp-hbl','psx_ticker','OGDC','2026-11-07T00:00:00Z')")


def test_alias_resolution(seeded):
    assert repo.resolve_alias(seeded, "HBL")[0]["company_id"] == "cmp-hbl"
    assert repo.resolve_alias(seeded, "habib bank")[0]["company_id"] == "cmp-hbl"
    assert repo.resolve_alias(seeded, "Fauji Fertilizer Bin Qasim") == []  # delisted excluded
    assert repo.resolve_alias(seeded, "Fauji Fertilizer Bin Qasim", listed_only=False)


def test_seed_load_is_idempotent(seeded):
    before = seed_loader.counts(seeded)
    assert seed_loader.load(seeded) == before


def test_watchlist_handles_preserved_exactly(seeded):
    rows = seeded.execute("SELECT platform, handle, supplied_url, monitoring_status, "
                          "identity_verification FROM media_accounts")
    handles = {(r["platform"], r["handle"]) for r in rows}
    assert ("x", "ARNOfficiall") in handles and ("youtube", "abdulrehmannajamofficial") in handles
    assert all(r["monitoring_status"] in ("disabled", "pending_handle") for r in rows)
    pending = [r for r in rows if r["handle"] is None]
    assert len(pending) == 2 and all(r["supplied_url"] is None for r in pending)


def test_reuters_not_activatable(seeded):
    r = seeded.execute("SELECT access_status, enabled FROM sources WHERE source_id='reuters'")[0]
    assert (r["access_status"], r["enabled"]) == ("licence_required", 0)


# ---------------------------------------------------------------- validation
def test_seed_validation_passes():
    assert seed_loader.validate_all() == []


def test_seed_validation_catches_bad_records():
    seed = seed_loader.load_json("companies.json")
    bad = json.loads(json.dumps(seed))
    bad["companies"][0]["ticker"] = "HBLXD"
    bad["companies"][1]["fiscal_year_end_month"] = "Smarch"
    bad["companies"][2]["source"]["url"] = "https://example.com/company/BOP"
    bad["companies"].append(dict(bad["companies"][3]))
    errors = "\n".join(validate_company_seed(bad))
    for expected in ("status marker", "fiscal year end", "official PSX page", "duplicate tickers"):
        assert expected in errors


def test_watchlist_validation_rejects_guessed_handles():
    wl = {"accounts": [{"platform": "x", "handle": None, "display_name": "Reuters",
                        "supplied_url": "https://x.com/Reuters"}]}
    assert validate_media_watchlist(wl)
