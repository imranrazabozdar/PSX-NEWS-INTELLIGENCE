"""Stage 2 batch 1: event classification, entity mapping and evidence assessment.

Modules: engines/event_intel.py, engines/event_classification.py.
Offline: local SQLite, seeded company master, SYNTHETIC publishers and headlines."""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import event_intel as ei
from engines import headline_events as hb
from engines.event_classification import classify, company_like_mentions, entity_mentions

T0 = "2026-11-05T06:00:00Z"
SOURCES = (  # id, url prefix, source type, tier
    ("syn_dawn", "https://www.dawn.com/news/", "news_media", "established_media"),
    ("syn_dawn_biz", "https://www.dawn.com/business/", "news_media", "established_media"),
    ("syn_br", "https://www.brecorder.com/news/", "news_media", "established_media"),
    ("syn_trib", "https://tribune.com.pk/story/", "news_media", "established_media"),
    ("syn_pbs", "https://www.pbs.gov.pk/release/", "government", "primary_official"),
)


def _db(path=":memory:"):
    d = SQLiteDatabase(path)
    migrate(d)
    load(d)
    for sid, _, stype, tier in SOURCES:
        d.execute(
            "INSERT INTO sources(source_id, name, source_type, reliability_tier, is_synthetic, "
            "created_at_utc, updated_at_utc) VALUES (?,?,?,?,1,?,?)",
            (sid, f"SYNTHETIC {sid}", stype, tier, T0, T0),
        )
    return d


@pytest.fixture
def db():
    d = _db()
    yield d
    d.close()


def _item(db, source, title, *, at=T0, dup_of=None):
    prefix = dict((s[0], s[1]) for s in SOURCES)[source]
    url = prefix + hashlib.sha256((source + title + at).encode()).hexdigest()[:12]
    db.execute(
        "INSERT INTO source_items(source_id, canonical_url, original_url, title, published_at_utc, "
        "publication_time_status, collected_at_utc, content_sha256, duplicate_of_item_id) "
        "VALUES (?,?,?,?,?,'known',?,?,?)",
        (source, url, url, title, at, at, hashlib.sha256(url.encode()).hexdigest(), dup_of),
    )
    return db.execute("SELECT MAX(source_item_id) AS id FROM source_items")[0]["id"]


def _both(db):
    hb.run(db)
    return ei.run(db)


def _rec(db, item_id):
    r = db.execute(
        "SELECT * FROM event_extractions WHERE source_item_id = ? AND schema_version = ?",
        (item_id, ei.SCHEMA_VERSION),
    )
    return (json.loads(r[0]["extracted_json"]) | {"_row": r[0]}) if r else None


def _event(db, event_id=1):
    return db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))[0]


# ------------------------------------------------------------------ classification rules
@pytest.mark.parametrize(
    "title, company, expected",
    [
        ("SBP keeps policy rate unchanged at 11pc", False, "monetary_policy"),
        ("US Fed holds rates steady", False, "monetary_policy"),
        ("OGDC posts higher quarterly profit", True, "corporate_result"),
        ("Lucky Cement announces final dividend of Rs 15", True, "corporate_dividend"),
        ("Board approves merger of two subsidiaries", False, "corporate_action"),
        ("Bank names new CEO after chairman resigns", False, "management_change"),
        ("IMF staff mission arrives for review talks", False, "imf_program"),
        ("Govt approves new petroleum levy", False, "tax_policy"),
        ("Federal budget deficit widens in first quarter", False, "fiscal_policy"),
        ("Circular debt rises to Rs 2.4 trillion", False, "energy_policy"),
        ("Oil prices jump on Middle East tensions", False, "commodity_price"),
        ("LNG cargo shortage hits gas supply", False, "commodity_supply"),
        ("Inflation eases to 4pc in October", False, "economic_indicator"),
        ("Government lifts ban on sugar exports", False, "trade_policy"),
        ("Moody's upgrades Pakistan outlook", False, "credit_rating"),
        ("SECP imposes penalty on brokerage", False, "regulatory_action"),
        ("Supreme Court hears petition on gas tariff", False, "legal_court"),
        ("KSE-100 gains 900 points in record session", False, "market_structure"),
        ("Ceasefire holds along border after strikes", False, "geopolitical"),
        ("Blast damages gas pipeline in Balochistan", False, "security_incident"),
        ("Refinery shutdown disrupts fuel supply chain", False, "infrastructure"),
        ("National Assembly session called for election bill", False, "political"),
        ("Engro Holdings signs contract for new plant", True, "corporate_announcement"),
    ],
)
def test_each_taxonomy_category_has_a_contextual_rule(title, company, expected):
    assert classify(title, company_mentioned=company).primary_type == expected


def test_isolated_keywords_do_not_classify_and_ambiguity_goes_to_review():
    for t in (
        "Rates of tomatoes in local markets",
        "Oil painting exhibition opens",
        "Weather to stay pleasant",
    ):
        c = classify(t)
        assert c.primary_type == "other" and c.needs_review and c.review_reasons
    assert classify("Company reports record sales", company_mentioned=False).primary_type == "other"


def test_secondary_types_and_stage_and_claim_nature():
    c = classify("Oil prices surge as Iran sanctions tighten")
    assert c.primary_type == "commodity_price" and "geopolitical" in c.secondary_types
    assert classify("Govt mulls new tax on property").stage == "discussion"
    assert classify("Cabinet approves IMF deal").stage == "approval"
    assert classify("FBR notifies new withholding tax rates").stage == "notification"
    assert classify("Tax measure deferred to next year").stage == "delay"
    assert classify("Govt reportedly plans gas price hike").claim_nature == "rumour"
    assert classify("Opinion: why rates must fall").claim_nature == "personal_opinion"
    assert classify("Inflation likely to ease next month").claim_nature == "prediction"
    assert classify("Ministry denies reports of tax increase").denial == ["denies"]


# ------------------------------------------------------------------ entities
def test_company_matches_by_ticker_legal_name_and_alias_only(db):
    i1 = _item(db, "syn_dawn", "OGDC posts higher quarterly profit")
    i2 = _item(
        db, "syn_br", "Pakistan Petroleum Limited reports record annual earnings", at="2026-11-09T06:00:00Z"
    )
    i3 = _item(db, "syn_trib", "Bank Alfalah quits Kabul after 20 years", at="2026-11-13T06:00:00Z")
    _both(db)
    get = lambda i: [(e["ticker"], e["relation"]) for e in _rec(db, i)["entities"] if e.get("company_id")]  # noqa: E731
    assert (
        get(i1) == [("OGDC", "direct")] and get(i2) == [("PPL", "direct")] and get(i3) == [("BAFL", "direct")]
    )


def test_ambiguous_unknown_and_lowercase_names_are_never_assigned(db):
    i1 = _item(db, "syn_dawn", "Engro Corporation profit rises sharply this quarter")
    i2 = _item(db, "syn_br", "XYZ Textile Mills Limited announces expansion", at="2026-11-09T06:00:00Z")
    i3 = _item(db, "syn_trib", "Good luck to engro fans at the match tonight", at="2026-11-13T06:00:00Z")
    _both(db)
    e1 = [e for e in _rec(db, i1)["entities"] if e["entity_type"] == "company"]
    assert e1 and all(e["company_id"] is None and e["relation"] in ("unresolved", "ambiguous") for e in e1)
    e2 = [e for e in _rec(db, i2)["entities"] if e["entity_type"] == "company"]
    assert (
        e2 == [e2[0]] and e2[0]["name"] == "XYZ Textile Mills Limited" and e2[0]["relation"] == "unresolved"
    )
    assert _rec(db, i2)["_row"]["needs_human_review"] == 1
    assert not [e for e in _rec(db, i3)["entities"] if e["entity_type"] == "company"]


def test_non_company_entities_direct_and_contextual():
    ents = {
        (e["entity_type"], e["name"], e["relation"])
        for e in entity_mentions(
            "NEPRA approves tariff hike; OGRA notifies petrol price as US and IMF watch", ["CEMENT"]
        )
    }
    assert {
        ("regulator", "NEPRA", "direct"),
        ("regulator", "OGRA", "direct"),
        ("commodity", "petrol", "direct"),
        ("country", "United States", "direct"),
        ("organisation", "IMF", "direct"),
        ("indicator", "electricity tariff", "context"),
    } <= ents
    assert not [e for e in entity_mentions("Tell us about the market") if e["name"] == "United States"]
    sec = entity_mentions("Cement despatches rise in October", ["CEMENT", "COMMERCIAL BANKS"])
    assert ("sector", "CEMENT") in {(e["entity_type"], e["name"]) for e in sec}
    assert not any(e["entity_type"] == "company" for e in sec)  # no company inferred from a sector
    assert company_like_mentions("State Bank of Pakistan holds rate") == []


# ------------------------------------------------------------------ evidence and corroboration
def test_same_publisher_feeds_are_one_group_and_never_independent(db):
    _item(db, "syn_dawn", "Government approves new petroleum levy on diesel and petrol")
    b = _item(
        db,
        "syn_dawn_biz",
        "Petroleum levy on diesel and petrol approved by government",
        at="2026-11-05T08:00:00Z",
    )
    _both(db)
    ev = _rec(db, b)["evidence"]
    assert ev["publisher_group"] == "domain:dawn.com" and ev["independence"] == "not_independent"
    assert ev["distinct_publisher_groups"] == 1


def test_stored_and_near_duplicates_are_not_independent(db):
    a = _item(db, "syn_dawn", "OGDC announces new gas discovery in Sindh district")
    b = _item(
        db,
        "syn_br",
        "OGDC announces new gas discovery in Sindh district",
        at="2026-11-05T07:00:00Z",
        dup_of=a,
    )
    _both(db)
    assert _rec(db, b)["evidence"]["independence"] == "not_independent"


def test_other_publishers_stay_unknown_and_never_corroborate(db):
    _item(db, "syn_dawn", "Government approves new petroleum levy on diesel and petrol")
    b = _item(
        db, "syn_br", "Petroleum levy on diesel and petrol approved by government", at="2026-11-05T08:00:00Z"
    )
    c = _item(
        db, "syn_trib", "Government approves petroleum levy on petrol and diesel", at="2026-11-05T09:00:00Z"
    )
    _both(db)
    for i in (b, c):
        assert _rec(db, i)["evidence"]["independence"] == "unknown"
    assert _event(db)["verification_state"] == "unverified"  # three outlets is not verification
    view = ei.event_intel(db, 1)
    assert view["independent_reports_confirmed"] == 0 and len(view["publisher_groups"]) == 3


def test_primary_official_source_confirms_but_rumour_does_not(db):
    p = _item(db, "syn_pbs", "Inflation eases to 4pc in October, PBS data shows")
    _both(db)
    assert _event(db)["verification_state"] == "primary_confirmed"
    assert _rec(db, p)["evidence"]["source_role"] == "primary_official"
    d2 = _db()
    _item(d2, "syn_pbs", "Govt reportedly plans gas price hike next month")
    _both(d2)
    assert _event(d2)["verification_state"] == "unverified"
    d2.close()


def test_conflicting_reports_are_marked_disputed_and_visible(db):
    _item(db, "syn_dawn", "Govt approves new petroleum levy on diesel and petrol")
    b = _item(
        db,
        "syn_br",
        "Govt denies approving new petroleum levy on diesel and petrol",
        at="2026-11-05T08:00:00Z",
    )
    _both(db)
    assert _event(db)["verification_state"] == "disputed"
    assert _rec(db, b)["conflicts"] and _rec(db, b)["_row"]["needs_human_review"] == 1
    assert ei.event_intel(db, 1)["conflicts"]


# ------------------------------------------------------------------ status and developments
def test_not_assessed_until_processed_then_classified_through_a_revision(db):
    _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    hb.run(db)
    assert (
        ei.classification_status(db, 1) == "not_assessed" and _event(db)["status_stage"] == "not_applicable"
    )
    ei.run(db)
    ev = _event(db)
    assert ei.classification_status(db, 1) == "assessed"
    assert (ev["event_type"], ev["status_stage"], ev["current_revision"]) == ("tax_policy", "discussion", 2)
    rev = db.execute("SELECT * FROM event_revisions WHERE event_id = 1 ORDER BY revision_no")
    assert rev[0]["changed_by"] == hb.RECORDED_BY and rev[1]["changed_by"] == ei.CHANGED_BY
    assert rev[0]["status_stage"] == "not_applicable"  # history is never overwritten
    assert "stage assessed" in rev[1]["change_reason"]


def test_non_numerical_development_is_recorded_as_a_new_revision(db):
    _item(db, "syn_dawn", "Government proposes new petroleum levy on diesel and petrol")
    _item(
        db,
        "syn_dawn",
        "Government approves new petroleum levy on diesel and petrol",
        at="2026-11-06T06:00:00Z",
    )
    _both(db)
    ev = _event(db)
    assert ev["status_stage"] == "approval" and ev["current_revision"] == 3
    last = db.execute("SELECT change_reason FROM event_revisions WHERE event_id = 1 AND revision_no = 3")[0]
    assert "development: proposal -> approval" in last["change_reason"]


def test_repeats_cause_no_revision_and_unitless_number_updates_are_not_material(db):
    _item(db, "syn_dawn", "Government approves new petroleum levy on diesel and petrol")
    _item(
        db, "syn_br", "Petroleum levy on diesel and petrol approved by government", at="2026-11-05T08:00:00Z"
    )
    c = _item(
        db,
        "syn_trib",
        "Government approves new petroleum levy 2 on diesel and petrol",
        at="2026-11-05T09:00:00Z",
    )
    _both(db)
    revs = db.execute(
        "SELECT COUNT(*) AS n FROM event_revisions WHERE event_id = 1 AND changed_by = ?", (ei.CHANGED_BY,)
    )[0]["n"]
    assert revs == 1  # only the first assessment; the repeat changed nothing
    assert (
        _rec(db, c)["builder_outcome"] == "UPDATE" and "not treated as material" in _rec(db, c)["figure_note"]
    )


def test_stageless_types_are_assessed_without_a_stage(db):
    _item(db, "syn_dawn", "OGDC posts higher quarterly profit")
    _both(db)
    ev = _event(db)
    assert ev["event_type"] == "corporate_result" and ev["status_stage"] == "not_applicable"
    assert ei.classification_status(db, 1) == "assessed"


# ------------------------------------------------------------------ integration and safety
def test_rerun_is_idempotent(db):
    _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    _both(db)
    counts = [
        db.execute(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]  # noqa: S608
        for t in ("events", "event_revisions", "event_extractions")
    ]
    assert ei.run(db).processed == 0
    assert [
        db.execute(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]  # noqa: S608
        for t in ("events", "event_revisions", "event_extractions")
    ] == counts


def test_double_processing_rolls_back_including_the_revision(db):
    _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    hb.run(db)
    from engines.news_tagging import NewsTagger

    rows = db.execute(
        ei.ITEM_SQL,
        (hb.RECORDED_BY, hb.SCHEMA_VERSION, hb.MODEL, ei.SCHEMA_VERSION, ei.MODEL, ei.PROMPT_VERSION, 10),
    )
    item, tagger = dict(rows[0]), NewsTagger(db)
    assert ei.process_item(db, item, tagger=tagger, sectors=[]) == ("PROCESSED", True)
    assert ei.process_item(db, item, tagger=tagger, sectors=[]) == ("ALREADY_PROCESSED", False)
    assert _event(db)["current_revision"] == 2  # the second attempt's revision was rolled back


def test_failure_mid_write_leaves_nothing_and_is_retried(db):
    it = _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    hb.run(db)
    real = db.batch

    def failing(stmts, **kw):
        stmts = list(stmts)
        if any(
            "INSERT INTO event_extractions" in sql and "event-intel/1" in json.dumps(p) for sql, p in stmts
        ):
            stmts.append(("SELECT not_a_function()", ()))
        return real(stmts, **kw)

    db.batch = failing
    s = ei.run(db)
    db.batch = real
    assert s.errors and _event(db)["current_revision"] == 1 and _rec(db, it) is None
    assert ei.run(db).processed == 1 and _event(db)["current_revision"] == 2


def test_malformed_item_data_is_isolated(db, monkeypatch):
    bad = _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    _item(db, "syn_br", "Cement despatches rise in October", at="2026-11-09T06:00:00Z")
    hb.run(db)
    real = ei.analyse

    def flaky(db_, item, **kw):
        if item["source_item_id"] == bad:
            raise ValueError("malformed stored value")
        return real(db_, item, **kw)

    monkeypatch.setattr(ei, "analyse", flaky)
    s = ei.run(db)
    assert s.processed == 1 and "invalid item data" in s.errors[0] and _rec(db, bad) is None


def test_concurrent_runs_do_not_duplicate(tmp_path):
    path = str(tmp_path / "ei.db")
    setup = _db(path)
    for k, t in enumerate(
        (
            "Govt mulls new tax on property sales",
            "Cement despatches rise in October",
            "Inflation eases to 4pc in October",
            "Oil prices jump on Middle East tensions",
        )
    ):
        _item(setup, "syn_dawn", t, at=f"2026-11-0{k + 1}T06:00:00Z")
    hb.run(setup)
    setup.close()
    barrier, out = threading.Barrier(2), []

    def worker():
        d = SQLiteDatabase(path)
        barrier.wait()
        out.append(ei.run(d))
        d.close()

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check = SQLiteDatabase(path)
    assert (
        check.execute(
            "SELECT COUNT(*) AS n FROM event_extractions WHERE schema_version = ?", (ei.SCHEMA_VERSION,)
        )[0]["n"]
        == 4
    )
    assert sum(s.processed for s in out) == 4 and not any(s.errors for s in out)
    check.close()


def test_builder_phase3_and_append_only_rules_still_hold(db):
    _item(db, "syn_dawn", "Govt mulls new tax on property sales")
    _both(db)
    assert hb.run(db).processed == 0  # the builder does not reprocess
    from engines.pipeline import ITEM_SQL as PHASE3

    assert db.execute(PHASE3, (10,)) == []  # Phase 3 unaffected (no permitted excerpts)
    with pytest.raises(DatabaseError):
        db.execute("UPDATE event_extractions SET model = 'x'")
    with pytest.raises(DatabaseError):
        db.execute("UPDATE event_revisions SET change_reason = 'x'")
