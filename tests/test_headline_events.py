"""Stage 2 Component 1: deterministic headline event builder (engines/headline_events.py).
Offline: local SQLite, SYNTHETIC headlines and publishers."""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import headline_events as he

T0 = "2026-11-05T06:00:00Z"
TABLES = ("events", "event_revisions", "event_evidence", "event_extractions")


def _db(path=":memory:"):
    d = SQLiteDatabase(path)
    migrate(d)
    for sid, name, owner, stype in (("syn_a", "SYNTHETIC Paper A", "Owner A", "news_media"),
                                    ("syn_b", "SYNTHETIC Paper B", "Owner B", "news_media"),
                                    ("syn_a2", "SYNTHETIC Paper A business feed", "Owner A", "news_media"),
                                    ("syn_mkt", "SYNTHETIC market data", "Owner M", "data_provider")):
        d.execute("INSERT INTO sources(source_id, name, source_type, owner, is_synthetic, created_at_utc, "
                  "updated_at_utc) VALUES (?,?,?,?,1,?,?)", (sid, name, stype, owner, T0, T0))
    return d


@pytest.fixture
def db():
    d = _db()
    yield d
    d.close()


def _item(db, source, title, *, at=T0, dup_of=None, url=None):
    url = url or f"https://example.invalid/{hashlib.sha256((source + str(title) + at).encode()).hexdigest()}"
    db.execute("INSERT INTO source_items(source_id, canonical_url, original_url, title, published_at_utc, "
               "publication_time_status, collected_at_utc, content_sha256, duplicate_of_item_id) "
               "VALUES (?,?,?,?,?,'known',?,?,?)",
               (source, url, url, title, at, at, hashlib.sha256(url.encode()).hexdigest(), dup_of))
    return db.execute("SELECT MAX(source_item_id) AS id FROM source_items")[0]["id"]


def _count(db, table, where="1=1", params=()):
    return db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)[0]["n"]  # noqa: S608


def _x(db, item_id):
    return db.execute("SELECT * FROM event_extractions WHERE source_item_id = ?", (item_id,))[0]


# ------------------------------------------------------------------ NEW
def test_new_headline_creates_one_event_with_exact_headline_evidence(db):
    title = "  SBP keeps policy rate unchanged at 11pc  "
    i = _item(db, "syn_a", title)
    s = he.run(db)
    assert s.outcomes == {"NEW": 1} and not s.errors
    ev = db.execute("SELECT * FROM events")[0]
    assert ev["headline"] == title.strip() and ev["verification_state"] == "unverified"
    assert ev["event_type"] == "other" and ev["novelty"] == "new" and ev["confidence"] is None
    assert ev["first_seen_at_utc"] == T0 and ev["current_revision"] == 1
    assert _count(db, "event_revisions", "event_id = ?", (ev["event_id"],)) == 1
    e = db.execute("SELECT * FROM event_evidence")[0]
    assert e["claim"] == e["excerpt"] == title.strip() and e["claim_type"] == "news_report"
    assert e["verification_state"] == "unverified"
    assert e["is_independent"] is None  # corroboration not assessed here
    x = _x(db, i)
    assert x["event_id"] == ev["event_id"] and x["model"] == "deterministic" and x["call_id"] is None
    assert "headline only" in x["confidence_explanation"]


def test_headline_only_provenance_is_complete(db):
    i = _item(db, "syn_b", "Cement despatches rise in October", url="https://example.invalid/cement")
    he.run(db)
    p = json.loads(_x(db, i)["provenance_json"])
    assert p["evidence_basis"] == "headline_only" and p["article_text_available"] is False
    assert (p["source_id"], p["publisher"], p["owner"]) == ("syn_b", "SYNTHETIC Paper B", "Owner B")
    assert p["url"] == "https://example.invalid/cement" and p["published_at_utc"] == T0
    assert p["collected_at_utc"] == T0 and p["publication_time_status"] == "known"


# ------------------------------------------------------------------ idempotency, retries, concurrency
def test_rerun_creates_nothing_new(db):
    _item(db, "syn_a", "SBP keeps policy rate unchanged at 11pc")
    _item(db, "syn_b", "Cement despatches rise in October")
    he.run(db)
    counts = [_count(db, t) for t in TABLES]
    s = he.run(db)
    assert s.processed == 0 and s.outcomes == {}
    assert [_count(db, t) for t in TABLES] == counts


def test_processing_an_item_twice_is_rejected_and_rolled_back(db):
    i = _item(db, "syn_a", "SBP keeps policy rate unchanged at 11pc")
    item = dict(db.execute(he.ITEM_SQL, (he.SCHEMA_VERSION, he.MODEL, he.PROMPT_VERSION, 10))[0])
    assert he.process_item(db, item) == "NEW"
    assert he.process_item(db, item) == "ALREADY_PROCESSED"  # stale retry: the whole second write rolled back
    assert [_count(db, t) for t in ("events", "event_evidence", "event_extractions")] == [1, 1, 1]
    assert _x(db, i)["event_id"] == 1


def test_a_failed_write_leaves_nothing_behind_and_the_item_is_retried(db):
    _item(db, "syn_a", "SBP keeps policy rate unchanged at 11pc")
    real = db.batch

    def failing(stmts, **kw):
        stmts = list(stmts)
        if any("INSERT INTO event_extractions" in sql for sql, _ in stmts):
            stmts.append(("SELECT RAISE_ERROR_NOT_A_FUNCTION()", ()))  # fails at the end of the transaction
        return real(stmts, **kw)

    db.batch = failing
    s = he.run(db)
    db.batch = real
    assert s.errors and s.processed == 0
    assert [_count(db, t) for t in TABLES] == [0] * 4
    assert he.run(db).outcomes == {"NEW": 1}  # retried cleanly on the next run


def test_concurrent_runs_never_duplicate_outcomes(tmp_path):
    path = str(tmp_path / "hl.db")
    setup = _db(path)
    topics = ("Cement despatches rise in October", "SBP keeps policy rate unchanged",
              "Textile exports climb on strong demand", "Fertiliser offtake slows sharply",
              "Banks report higher deposits this quarter", "Power tariff revision notified by regulator")
    for k, title in enumerate(topics):
        _item(setup, "syn_a" if k % 2 else "syn_b", title, at=f"2026-11-0{k + 1}T06:00:00Z")
    setup.close()
    barrier, out = threading.Barrier(2), []

    def worker():
        d = SQLiteDatabase(path)
        barrier.wait()
        out.append(he.run(d))
        d.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check = SQLiteDatabase(path)
    assert _count(check, "event_extractions") == 6 and _count(check, "event_evidence") == 6
    assert _count(check, "events") == 6 and not any(s.errors for s in out)
    assert sum(s.processed for s in out) == 6
    check.close()


# ------------------------------------------------------------------ REPEAT / UPDATE
def test_stored_duplicate_is_a_repeat_and_never_independent(db):
    a = _item(db, "syn_a", "OGDC announces new gas discovery in Sindh")
    b = _item(db, "syn_a2", "OGDC announces new gas discovery in Sindh", dup_of=a)
    s = he.run(db)
    assert s.outcomes == {"NEW": 1, "REPEAT": 1} and _count(db, "events") == 1
    dup = db.execute("SELECT * FROM event_evidence WHERE source_item_id = ?", (b,))[0]
    assert dup["is_independent"] == 0 and json.loads(_x(db, b)["extracted_json"])["outcome"] == "REPEAT"


def test_near_identical_headline_from_another_publisher_is_a_repeat_not_corroboration(db):
    _item(db, "syn_a", "OGDC announces new gas discovery in Sindh district")
    b = _item(db, "syn_b", "OGDC announces new gas discovery in Sindh district.", at="2026-11-05T08:00:00Z")
    he.run(db)
    assert _count(db, "events") == 1
    assert db.execute("SELECT is_independent FROM event_evidence WHERE source_item_id = ?", (b,))[0][
        "is_independent"] == 0


def test_same_story_without_new_figures_is_a_repeat_with_independence_not_assessed(db):
    _item(db, "syn_a", "Government approves new petroleum levy on diesel and petrol")
    b = _item(db, "syn_b", "Petroleum levy on diesel and petrol approved by government",
              at="2026-11-05T09:00:00Z")
    s = he.run(db)
    assert s.outcomes == {"NEW": 1, "REPEAT": 1}
    e = db.execute("SELECT is_independent FROM event_evidence WHERE source_item_id = ?", (b,))[0]
    assert e["is_independent"] is None  # different publisher, but corroboration is not decided here
    ev = db.execute("SELECT current_revision, novelty FROM events")[0]
    assert ev == {"current_revision": 1, "novelty": "new"}


def test_same_story_with_a_new_figure_is_an_update_with_a_new_revision(db):
    _item(db, "syn_a", "Government approves new petroleum levy on diesel and petrol")
    b = _item(db, "syn_b", "Government approves new petroleum levy of Rs 10 on diesel and petrol",
              at="2026-11-05T10:00:00Z")
    s = he.run(db)
    assert s.outcomes == {"NEW": 1, "UPDATE": 1}
    ev = db.execute("SELECT * FROM events")[0]
    assert ev["current_revision"] == 2 and ev["novelty"] == "update"
    rev = db.execute("SELECT * FROM event_revisions WHERE revision_no = 2")[0]
    assert "10" in rev["change_reason"] and rev["changed_by"] == he.RECORDED_BY
    # the first headline is kept
    assert ev["headline"] == "Government approves new petroleum levy on diesel and petrol"
    assert _count(db, "event_evidence", "event_id = ?", (ev["event_id"],)) == 2
    assert json.loads(_x(db, b)["extracted_json"])["matched_event_id"] == ev["event_id"]


def test_unrelated_or_out_of_window_headlines_are_new_events(db):
    _item(db, "syn_a", "Government approves new petroleum levy on diesel and petrol")
    _item(db, "syn_b", "Cement despatches rise in October", at="2026-11-05T07:00:00Z")
    _item(db, "syn_b", "Government approves new petroleum levy on diesel and petrol",
          at="2026-11-20T07:00:00Z")
    assert he.run(db).outcomes == {"NEW": 3}


# ------------------------------------------------------------------ safety
@pytest.mark.parametrize("title", [None, "", "   ", "PSX update", "Breaking"])
def test_empty_or_ambiguous_headlines_are_skipped_for_review(db, title):
    i = _item(db, "syn_a", title)
    assert he.run(db).outcomes == {"SKIPPED": 1}
    x = _x(db, i)
    assert x["event_id"] is None and x["needs_human_review"] == 1 and _count(db, "events") == 0
    assert json.loads(x["extracted_json"])["outcome"] == "SKIPPED"


def test_duplicate_of_a_skipped_item_is_not_forced_into_an_event(db):
    a = _item(db, "syn_a", "PSX update")
    _item(db, "syn_a2", "PSX update", dup_of=a)
    assert he.run(db).outcomes == {"SKIPPED": 2} and _count(db, "events") == 0


def test_non_news_sources_are_not_eligible(db):
    _item(db, "syn_mkt", "OGDC 1d bars stored for synthetic session")
    assert he.run(db).processed == 0 and _count(db, "event_extractions") == 0


def test_incremental_batches_process_existing_backlog_then_new_arrivals(db):
    for k in range(5):
        _item(db, "syn_a", f"Distinct synthetic backlog headline number {k} today",
              at=f"2026-11-0{k + 1}T06:00:00Z")
    assert he.run(db, limit=2).processed == 2 and he.run(db, limit=10).processed == 3
    _item(db, "syn_b", "Fresh synthetic arrival about textile exports growth", at="2026-11-07T06:00:00Z")
    assert he.run(db).outcomes == {"NEW": 1} and _count(db, "event_extractions") == 6


def test_events_remain_append_only_and_existing_pipeline_queries_still_work(db):
    _item(db, "syn_a", "SBP keeps policy rate unchanged at 11pc")
    he.run(db)
    with pytest.raises(DatabaseError):
        db.execute("UPDATE event_evidence SET claim = 'x'")
    from database import repositories as repo
    from engines.pipeline import ITEM_SQL as PHASE3_ITEMS

    assert repo.event_with_evidence(db, 1)["evidence"][0]["claim_type"] == "news_report"
    assert db.execute(PHASE3_ITEMS, (10,)) == []  # Phase 3 path unchanged: no permitted excerpts


# ------------------------------------------------------------------ follow-up: item-level data errors
def test_malformed_item_data_is_reported_stays_eligible_and_later_items_still_run(db):
    bad = _item(db, "syn_a", "Synthetic headline with an unparseable stored timestamp", at="not-a-timestamp")
    good = _item(db, "syn_b", "Cement despatches rise in October", at="2026-11-06T06:00:00Z")
    s = he.run(db)
    assert s.outcomes == {"NEW": 1} and len(s.errors) == 1 and "invalid item data: ValueError" in s.errors[0]
    assert _count(db, "event_extractions", "source_item_id = ?", (bad,)) == 0  # never recorded as processed
    assert _count(db, "event_extractions", "source_item_id = ?", (good,)) == 1
    assert [_count(db, t) for t in ("events", "event_evidence")] == [1, 1]  # nothing partial for the bad item
    again = he.run(db)
    assert again.processed == 0 and len(again.errors) == 1  # still eligible, retried, still reported


def test_programming_errors_are_not_swallowed(db, monkeypatch):
    _item(db, "syn_a", "SBP keeps policy rate unchanged at 11pc")

    def broken(db, item):
        raise RuntimeError("bug")

    monkeypatch.setattr(he, "decide", broken)
    with pytest.raises(RuntimeError):
        he.run(db)
    assert _count(db, "event_extractions") == 0
