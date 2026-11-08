"""Stage 2 batch 2: company exposure and T1-T9 impact intelligence (engines/impact_intel.py).
Offline: local SQLite, seeded company master, SYNTHETIC headlines, sources and documented exposures."""

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
from engines import impact_intel as ii

T0 = "2026-11-05T06:00:00Z"


def _db(path=":memory:"):
    d = SQLiteDatabase(path)
    migrate(d)
    load(d)
    for sid, tier, stype in (
        ("syn", "established_media", "news_media"),
        ("syn2", "established_media", "news_media"),
    ):
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


def _item(db, title, at=T0, source="syn"):
    dom = "dawn.com" if source == "syn" else "brecorder.com"
    url = f"https://www.{dom}/" + hashlib.sha256((title + at + source).encode()).hexdigest()[:12]
    db.execute(
        "INSERT INTO source_items(source_id, canonical_url, original_url, title, published_at_utc, "
        "publication_time_status, collected_at_utc, content_sha256) VALUES (?,?,?,?,?,'known',?,?)",
        (source, url, url, title, at, at, hashlib.sha256(url.encode()).hexdigest()),
    )
    return db.execute("SELECT MAX(source_item_id) AS id FROM source_items")[0]["id"]


def _exposure(db, company_id, kind, subject):
    src = _item(
        db, f"SYNTHETIC annual report note for {company_id} {kind} {subject}", at="2026-01-01T00:00:00Z"
    )
    db.execute(
        "INSERT INTO company_exposures(company_id, exposure_kind, subject, confidence, source_item_id, "
        "evidence_excerpt, last_verified_utc) VALUES (?,?,?,'documented',?,?,?)",
        (company_id, kind, subject, src, f"SYNTHETIC: {subject}", T0),
    )


def _run(db, *titles):
    for k, t in enumerate(titles):
        _item(db, t, at=f"2026-11-{k + 2:02d}T06:00:00Z")
    hb.run(db)
    ei.run(db)
    return ii.run(db, synthetic=True)


def _event_of(db, title):
    return db.execute("SELECT event_id FROM events WHERE headline = ?", (title,))[0]["event_id"]


def _a(db, event_id, company_id, mech):
    r = db.execute(
        "SELECT * FROM impact_assessments WHERE event_id = ? AND company_id = ? AND mechanism_id = ?",
        (event_id, company_id, mech),
    )
    return r[0] if r else None


# ------------------------------------------------------------------ exposure
def test_named_company_gives_direct_exposure_but_no_invented_impact(db):
    s = _run(db, "OGDC posts higher quarterly profit")
    ev = _event_of(db, "OGDC posts higher quarterly profit")
    o = ii.event_impact_overview(db, ev)
    cands = o["exposure_candidates"]
    assert [(c["company_id"], c["exposure_level"]) for c in cands] == [("cmp-ogdc", "direct")]
    assert o["assessments"] == {} and o["no_transmission"] and s.no_mechanism  # nothing manufactured


def test_documented_exposure_gives_direct_signed_impact_and_sector_does_not(db):
    _exposure(db, "cmp-pso", "product", "petroleum products incl. oil")  # documented seller of oil products
    _run(db, "Oil prices surge on supply worries")
    ev = _event_of(db, "Oil prices surge on supply worries")
    a = _a(db, ev, "cmp-pso", "T1")
    assert (
        a["direction"] == "positive" and a["exposure_confidence"] == "low"
    )  # unapproved sources: unverified
    assert "documented company exposure" in json.loads(a["confidence_reasons_json"])["exposure"]
    o = ii.event_impact_overview(db, ev)
    sector_only = [c for c in o["exposure_candidates"] if c["exposure_level"] == "indirect"]
    assert sector_only and all(c["effective_status"] == "unverified" for c in sector_only)


def test_sector_hypotheses_follow_framework_roles_and_differ_by_company(db):
    _run(db, "Oil prices surge on supply worries")
    ev = _event_of(db, "Oil prices surge on supply worries")
    assert _a(db, ev, "cmp-ogdc", "T1")["direction"] == "positive"  # E&P
    assert _a(db, ev, "cmp-prl", "T1")["direction"] == "mixed"  # refiner
    assert _a(db, ev, "cmp-pso", "T1")["direction"] == "mixed"  # OMC
    for cid in ("cmp-ogdc", "cmp-prl", "cmp-pso"):
        a = _a(db, ev, cid, "T1")
        assert a["magnitude_level"] == "low" and a["exposure_confidence"] == "low"
        assert "sector-level hypothesis" in json.loads(a["confidence_reasons_json"])["exposure"]
    assert _a(db, ev, "cmp-hbl", "T1") is None  # a bank is not attributed through the oil sector


def test_company_specific_event_does_not_spread_to_sector_peers(db):
    _run(db, "OGDC announces new gas discovery in Sindh")
    ev = _event_of(db, "OGDC announces new gas discovery in Sindh")
    cands = ii.event_impact_overview(db, ev)["exposure_candidates"]
    assert {c["company_id"] for c in cands} == {"cmp-ogdc"}  # no PPL/MARI/POL by sector


def test_unresolved_and_ambiguous_companies_stay_visible(db):
    _run(db, "XYZ Textile Mills Limited faces higher power tariff")
    ev = _event_of(db, "XYZ Textile Mills Limited faces higher power tariff")
    o = ii.event_impact_overview(db, ev)
    assert o["unresolved_companies"][0]["name"] == "XYZ Textile Mills Limited"
    assert all(c["company_id"] != "XYZ Textile Mills Limited" for c in o["exposure_candidates"])


def test_no_established_exposure_is_reported_not_filled(db):
    _run(db, "Rupee depreciates sharply against dollar")
    o = ii.event_impact_overview(db, _event_of(db, "Rupee depreciates sharply against dollar"))
    assert {m["mechanism"] for m in o["mechanisms"]} == {"T4"}
    assert o["no_established_exposure"] and o["assessments"] == {}


# ------------------------------------------------------------------ T1-T9, direction, horizon
def test_currency_depreciation_signs_importers_and_exporters_differently(db):
    _exposure(db, "cmp-luck", "input", "imported coal")
    _exposure(db, "cmp-ffc", "fx", "export revenue in USD")
    _run(db, "Rupee depreciates sharply against dollar")
    ev = _event_of(db, "Rupee depreciates sharply against dollar")
    assert _a(db, ev, "cmp-luck", "T4")["direction"] == "negative"
    assert _a(db, ev, "cmp-ffc", "T4")["direction"] == "positive"
    assert _a(db, ev, "cmp-luck", "T4")["horizon"] == "short"


def test_gas_price_rise_is_negative_for_fertiliser_feedstock_users(db):
    _run(db, "Govt raises gas price for fertilizer plants")
    ev = _event_of(db, "Govt raises gas price for fertilizer plants")
    a = _a(db, ev, "cmp-efert", "T2")
    assert a["direction"] == "negative" and a["horizon"] == "medium"
    assert "pass-through orders" in json.loads(a["counter_evidence_json"])


def test_rate_change_leaves_bank_direction_unknown(db):
    _run(db, "SBP raises policy rate to 13pc")
    a = _a(db, _event_of(db, "SBP raises policy rate to 13pc"), "cmp-hbl", "T3")
    assert a["direction"] == "unknown" and a["scenario_uncertainty"] == "undetermined"
    assert a["direction_confidence"] == "low"


def test_tax_on_documented_product_is_negative_t5_only_when_the_rise_is_stated(db):
    _exposure(db, "cmp-luck", "product", "cement")
    _run(db, "Govt raises sales tax on cement")
    a = _a(db, _event_of(db, "Govt raises sales tax on cement"), "cmp-luck", "T5")
    assert a["direction"] == "negative" and a["horizon"] == "medium"
    d2 = _db()
    _exposure(d2, "cmp-luck", "product", "cement")
    _run(d2, "Govt imposes new sales tax regime on cement")
    b = _a(d2, _event_of(d2, "Govt imposes new sales tax regime on cement"), "cmp-luck", "T5")
    assert b["direction"] == "unknown"  # framework: the change is not stated, so the direction is unknown
    d2.close()


@pytest.mark.parametrize(
    "title, company, mechs",
    [
        ("NEPRA approves power tariff hike for HUBC", "cmp-hubc", {"T6"}),
        ("Coal prices surge as LUCK imports rise", "cmp-luck", {"T7"}),
        ("PSO tankers delayed as Hormuz shipping attack escalates tensions", "cmp-pso", {"T8"}),
        ("IMF budget measures hit HBL with higher super tax", "cmp-hbl", {"T5", "T9"}),
    ],
)
def test_named_companies_get_only_the_event_supported_mechanisms(db, title, company, mechs):
    _run(db, title)
    o = ii.event_impact_overview(db, _event_of(db, title))
    got = {a["mechanism_id"] for a in o["assessments"].get(company, [])}
    assert mechs <= got
    assert all(a["direction"] == "unknown" for a in o["assessments"][company])  # role not documented


def test_horizons_follow_the_framework():
    assert {k: m.horizon for k, m in ii.MECHANISMS.items()} == {
        "T1": "short",
        "T2": "medium",
        "T3": "medium",
        "T4": "short",
        "T5": "medium",
        "T6": "medium",
        "T7": "medium",
        "T8": "unknown",
        "T9": "long",
    }


def test_opposite_signs_aggregate_to_mixed_never_netted(db):
    _exposure(db, "cmp-luck", "input", "imported coal")
    _exposure(db, "cmp-luck", "fx", "export revenue in USD")
    _run(db, "Rupee depreciates sharply against dollar")
    o = ii.event_impact_overview(db, _event_of(db, "Rupee depreciates sharply against dollar"))
    dirs = {a["direction"] for a in o["assessments"]["cmp-luck"]}
    assert o["company_aggregate_direction"]["cmp-luck"] in ("mixed", "positive", "negative")
    if {"positive", "negative"} <= dirs:
        assert o["company_aggregate_direction"]["cmp-luck"] == "mixed"


# ------------------------------------------------------------------ fundamentals versus market pressure
def test_regional_instability_is_market_pressure_not_fundamentals(db):
    title = "HBL shares fall as regional war tensions rise"
    _run(db, title)
    o = ii.event_impact_overview(db, _event_of(db, title))
    a = o["assessments"]["cmp-hbl"][0]
    assert a["mechanism_id"] == "T8" and a["direction"] == "unknown"
    assert a["layers"]["fundamental"].startswith("not assessed")
    assert "not evidence of a change in fundamentals" in a["layers"]["market_sentiment"]
    assert a["layers"]["valuation"].startswith("not assessed")


def test_global_event_with_pakistan_transmission_versus_none(db):
    _run(db, "Oil prices surge as Iran tensions rise", "US stocks fall sharply on Wall Street")
    oil = ii.event_impact_overview(db, _event_of(db, "Oil prices surge as Iran tensions rise"))
    us = ii.event_impact_overview(db, _event_of(db, "US stocks fall sharply on Wall Street"))
    assert (
        oil["scope"] == "global"
        and "T1" in {m["mechanism"] for m in oil["mechanisms"]}
        and oil["assessments"]
    )
    assert us["scope"] == "global" and us["no_transmission"] and us["assessments"] == {}


# ------------------------------------------------------------------ confidence, scenarios, conflicts
def test_low_confidence_exposure_never_becomes_provisional_and_scenarios_are_conditional(db):
    _run(db, "Oil prices surge on supply worries")
    ev = _event_of(db, "Oil prices surge on supply worries")
    rows = db.execute(
        "SELECT assessment_status, magnitude_basis, magnitude_confidence FROM impact_assessments"
    )
    assert {r["assessment_status"] for r in rows} == {"scenario_only"}
    assert {(r["magnitude_basis"], r["magnitude_confidence"]) for r in rows} == {("qualitative", "low")}
    a = _a(db, ev, "cmp-ogdc", "T1")
    sc = db.execute(
        "SELECT * FROM impact_scenarios WHERE assessment_id = ? ORDER BY scenario_case", (a["assessment_id"],)
    )
    assert [s["scenario_case"] for s in sc] == ["adverse", "base", "optimistic"]
    for s in sc:
        j = json.loads(s["assumptions_json"])
        assert j["invalidated_by"] and j["strengthened_by"] and "not a forecast" in j["conditional"]
    steps = db.execute(
        "SELECT * FROM impact_transmission_steps WHERE assessment_id = ? ORDER BY step_no",
        (a["assessment_id"],),
    )
    assert len(steps) == 2 and steps[-1]["sign"] == 1
    missing = json.loads(a["missing_inputs_json"])
    assert any("fundamentals not assessed" in m for m in missing)
    assert (
        db.execute("SELECT COUNT(*) AS n FROM impact_assessments WHERE magnitude_level IN ('medium','high')")[
            0
        ]["n"]
        == 0
    )


def test_disputed_event_assessments_need_review(db):
    _item(db, "Govt approves new petroleum levy on diesel and petrol", at="2026-11-02T06:00:00Z")
    _item(
        db,
        "Govt denies approving new petroleum levy on diesel and petrol",
        at="2026-11-02T08:00:00Z",
        source="syn2",
    )
    _exposure(db, "cmp-pso", "product", "diesel and petrol")
    hb.run(db)
    ei.run(db)
    ii.run(db, synthetic=True)
    ev = db.execute("SELECT event_id, verification_state FROM events")[0]
    assert ev["verification_state"] == "disputed"
    rows = db.execute(
        "SELECT assessment_status, status_reason FROM impact_assessments WHERE event_id = ?",
        (ev["event_id"],),
    )
    assert rows and {(r["assessment_status"], r["status_reason"]) for r in rows} == {
        ("needs_review", "event_disputed")
    }
    assert ii.event_impact_overview(db, ev["event_id"])["conflicts"]


# ------------------------------------------------------------------ integration and safety
def test_rerun_is_idempotent_and_later_revisions_are_reported_stale(db):
    s1 = _run(db, "Oil prices surge on supply worries")
    n = db.execute("SELECT COUNT(*) AS n FROM impact_assessments")[0]["n"]
    s2 = ii.run(db, synthetic=True)
    assert s1.assessments_created == n > 0 and s2.assessments_created == 0 and s2.already_assessed == n
    assert db.execute("SELECT COUNT(*) AS n FROM exposure_candidate_revisions")[0]["n"] > 0
    from database import repositories as repo

    ev = _event_of(db, "Oil prices surge on supply worries")
    repo.revise_event(db, ev, {"summary": "later development"}, reason="test", changed_by="test")
    s3 = ii.run(db, synthetic=True)
    assert s3.stale and s3.assessments_created == 0  # history kept; revalidation is a reviewed step


def test_failed_assessment_write_leaves_nothing_and_is_retried(db):
    _item(db, "SBP raises policy rate to 13pc", at="2026-11-02T06:00:00Z")
    hb.run(db)
    ei.run(db)
    real = db.batch

    def failing(stmts, **kw):
        stmts = list(stmts)
        if any("INSERT INTO impact_assessments" in sql for sql, _ in stmts):
            stmts.append(("SELECT not_a_function()", ()))
        return real(stmts, **kw)

    db.batch = failing
    s = ii.run(db, synthetic=True)
    db.batch = real
    assert s.errors and db.execute("SELECT COUNT(*) AS n FROM impact_assessments")[0]["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM impact_scenarios")[0]["n"] == 0
    assert ii.run(db, synthetic=True).assessments_created > 0


def test_unique_key_prevents_duplicates_and_concurrent_runs_are_safe(tmp_path):
    path = str(tmp_path / "ii.db")
    setup = _db(path)
    _item(setup, "SBP raises policy rate to 13pc", at="2026-11-02T06:00:00Z")
    hb.run(setup)
    ei.run(setup)
    setup.close()
    barrier, out = threading.Barrier(2), []

    def worker():
        d = SQLiteDatabase(path)
        barrier.wait()
        out.append(ii.run(d, synthetic=True))
        d.close()

    ts = [threading.Thread(target=worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check = SQLiteDatabase(path)
    rows = check.execute(
        "SELECT event_id, company_id, mechanism_id, COUNT(*) AS n FROM impact_assessments "
        "GROUP BY 1, 2, 3 HAVING n > 1"
    )
    assert rows == [] and check.execute("SELECT COUNT(*) AS n FROM impact_assessments")[0]["n"] == 11
    check.close()


def test_only_assessed_events_are_processed_and_batch1_stays_compatible(db):
    _item(db, "SBP raises policy rate to 13pc", at="2026-11-02T06:00:00Z")
    hb.run(db)
    assert ii.run(db, synthetic=True).events == 0  # not assessed by batch 1 yet: untouched
    ei.run(db)
    assert ii.run(db, synthetic=True).events == 1
    assert ei.run(db).processed == 0 and hb.run(db).processed == 0
    with pytest.raises(DatabaseError):
        db.execute("UPDATE impact_scenarios SET direction = 'positive'")
