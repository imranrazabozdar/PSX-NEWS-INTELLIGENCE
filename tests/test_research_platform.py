"""Stage 2 final batch: research views, reports, revalidation, review, validation and readiness.
Offline: local SQLite, seeded company master, SYNTHETIC headlines and labels."""

from __future__ import annotations

import json

import pytest

from database import repositories as repo
from database.connection import DatabaseError
from engines import impact_intel as ii
from engines import intel_pipeline as ip
from engines import research, validation
from engines import review_revalidation as rv
from tests.test_impact_intel import _db as _new_db
from tests.test_impact_intel import _event_of, _exposure, _item, _run

OIL = "Oil prices surge on supply worries"


@pytest.fixture
def db():
    d = _new_db()
    yield d
    d.close()


def _count(db, table):
    return db.execute(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]  # noqa: S608


# ------------------------------------------------------------------ views on empty and partial data
def test_empty_database_shows_nothing_assessed_not_success(db):
    page = research.events_page(db)
    assert page["total"] == 0 and page["items"] == []
    rep = research.company_report(db, "cmp-ogdc")
    assert rep["latest_developments"] == [] and rep["limitations"]["valuation"] == research.NOT_ASSESSED
    r = ip.readiness(db)
    assert {c["check"]: c["status"] for c in r["checks"]}["last intelligence run"] == "warn"
    assert r["overall"] == "warn"
    assert research.company_report(db, "cmp-nonexistent") is None


def test_partial_data_marks_unclassified_events_not_assessed(db):
    from engines import headline_events as hb

    _item(db, "Govt mulls new tax on property sales", at="2026-11-02T06:00:00Z")
    hb.run(db)
    item = research.events_page(db)["items"][0]
    assert item["classification"] == "not_assessed" and item["display_stage"] == "Not assessed"
    assert research.event_detail(db, item["event_id"])["display_stage"] == "Not assessed"


def test_event_detail_navigates_evidence_entities_exposure_assessments(db):
    _run(db, OIL)
    d = research.event_detail(db, _event_of(db, OIL))
    assert d["evidence"][0]["headline_only"] and d["evidence"][0]["publisher_group"] == "domain:dawn.com"
    assert d["revisions"] and d["impact"]["mechanisms"][0]["mechanism"] == "T1"
    assert "cmp-ogdc" in d["impact"]["assessments"] and d["impact"]["exposure_candidates"]
    assert research.event_detail(db, 99_999) is None


def test_macro_filter_and_pagination(db):
    _run(db, OIL, "OGDC posts higher quarterly profit", "SBP raises policy rate to 13pc")
    macro = research.events_page(db, macro_only=True)
    assert {e["event_type"] for e in macro["items"]} <= set(research.MACRO_TYPES) and macro["total"] == 2
    p1, p2 = research.events_page(db, limit=2, offset=0), research.events_page(db, limit=2, offset=2)
    assert p1["total"] == 3 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert not {e["event_id"] for e in p1["items"]} & {e["event_id"] for e in p2["items"]}


# ------------------------------------------------------------------ reports
def test_company_report_links_events_evidence_and_says_not_assessed(db):
    _exposure(db, "cmp-pso", "product", "petroleum products incl. oil")
    _run(db, OIL)
    rep = research.company_report(db, "cmp-pso")
    assert rep["company"]["ticker"] == "PSO" and rep["generated_at_utc"].endswith("Z")
    assert "T1" in rep["impact_by_mechanism"] and rep["evidence_references"][0]["excerpt"] == OIL
    assert rep["exposure"]["direct"] and rep["risks_and_invalidation"]
    lim = rep["limitations"]
    assert (
        lim["financial_statements"]
        == lim["share_price"]
        == lim["technical_indicators"]
        == research.NOT_ASSESSED
    )
    assert all(a["currency"] == "current" for a in rep["impact_by_mechanism"]["T1"])


def test_report_marks_assessments_historical_after_an_event_revision(db):
    _run(db, OIL)
    repo.revise_event(db, _event_of(db, OIL), {"summary": "later"}, reason="test", changed_by="test")
    rep = research.company_report(db, "cmp-ogdc")
    assert rep["impact_by_mechanism"]["T1"][0]["currency"].startswith("historical")


def test_markdown_export_has_all_sections_timestamp_and_no_advice(db):
    _run(db, OIL)
    md = research.report_markdown(research.company_report(db, "cmp-ogdc"))
    for n in range(1, 13):
        assert f"## {n}." in md
    assert "Data as of" in md and "no buy/sell recommendation" in md and "not forecasts" in md
    assert research.NOT_ASSESSED in md
    import re
    from urllib.parse import urlparse

    hosts = {urlparse(u).hostname for u in re.findall(r"https://[^\s|)]+", md)}
    assert hosts == {"www.dawn.com"}  # source references are present and point at the stored publisher


def test_sector_report_shows_differing_impacts_and_never_sector_proof(db):
    _run(db, OIL)
    rep = research.sector_report(db, "psx-oil-gas-exploration-companies")
    assert rep["companies"] and "never establishes" in rep["note"]
    assert rep["unverified_relationships"] and research.sector_report(db, "psx-nope") is None


# ------------------------------------------------------------------ revalidation
def test_unchanged_result_revalidates_to_new_revision_with_history(db):
    _run(db, OIL)
    ev = _event_of(db, OIL)
    repo.revise_event(db, ev, {"summary": "later wording"}, reason="test", changed_by="test")
    assert rv.stale_assessments(db)
    out = rv.revalidate(db)
    assert out["unchanged"] > 0 and not out["errors"] and not rv.stale_assessments(db)
    a = db.execute("SELECT * FROM impact_assessments WHERE event_id = ? AND company_id = 'cmp-ogdc'", (ev,))[
        0
    ]
    assert (a["assessment_status"], a["status_reason"], a["current_revision"]) == (
        "scenario_only",
        "revalidated",
        2,
    )
    assert len(rv.review_history(db, a["assessment_id"])) == 2  # original revision kept
    assert (
        db.execute(
            "SELECT COUNT(*) AS n FROM impact_scenarios WHERE assessment_id = ? AND revision_no = 2",
            (a["assessment_id"],),
        )[0]["n"]
        == 3
    )
    assert rv.revalidate(db) == {
        "unchanged": 0,
        "needs_review": 0,
        "needs_revalidation": 0,
        "skipped": [],
        "errors": [],
    }  # repeated run is a no-op


def test_disputed_event_moves_assessments_to_review(db):
    _run(db, OIL)
    ev = _event_of(db, OIL)
    repo.revise_event(db, ev, {"verification_state": "disputed"}, reason="test conflict", changed_by="test")
    assert rv.revalidate(db)["needs_review"] > 0
    rows = db.execute(
        "SELECT DISTINCT assessment_status, status_reason FROM impact_assessments WHERE event_id = ?", (ev,)
    )
    assert rows == [{"assessment_status": "needs_review", "status_reason": "event_disputed"}]


def test_material_change_is_proposed_not_applied(db, monkeypatch):
    _run(db, OIL)
    ev = _event_of(db, OIL)
    before = db.execute(
        "SELECT direction FROM impact_assessments WHERE event_id = ? AND company_id = 'cmp-ogdc'", (ev,)
    )[0]["direction"]
    repo.revise_event(db, ev, {"summary": "new facts"}, reason="test", changed_by="test")
    real = ii._assessment

    def changed(*a, **k):
        out = real(*a, **k)
        return out | {"direction": "negative" if out["direction"] != "negative" else "positive"}

    monkeypatch.setattr(ii, "_assessment", changed)
    assert rv.revalidate(db)["needs_revalidation"] > 0
    a = db.execute("SELECT * FROM impact_assessments WHERE event_id = ? AND company_id = 'cmp-ogdc'", (ev,))[
        0
    ]
    assert a["assessment_status"] == "needs_revalidation" and a["direction"] == before  # conclusion kept
    assert "would change" in a["change_reason"] and "earlier conclusion kept" in a["change_reason"]
    assert rv.revalidate(db)["needs_revalidation"] == 0  # not re-flagged while awaiting a human


def test_revalidation_rollback_leaves_assessment_unchanged(db):
    _run(db, OIL)
    ev = _event_of(db, OIL)
    repo.revise_event(db, ev, {"summary": "later"}, reason="test", changed_by="test")
    real = db.batch

    def failing(stmts, **kw):
        stmts = list(stmts)
        if any("UPDATE impact_assessments" in s for s, _ in stmts):
            stmts.append(("SELECT not_a_function()", ()))
        return real(stmts, **kw)

    db.batch = failing
    out = rv.revalidate(db)
    db.batch = real
    assert (
        out["errors"] and db.execute("SELECT MAX(current_revision) AS m FROM impact_assessments")[0]["m"] == 1
    )
    assert rv.revalidate(db)["unchanged"] > 0


# ------------------------------------------------------------------ review workflow
def test_review_queue_is_read_only_and_explains_items(db):
    _run(db, OIL, "XYZ Textile Mills Limited faces higher power tariff")
    counts = [_count(db, t) for t in ("impact_reviews", "exposure_reviews", "impact_assessment_revisions")]
    q = rv.review_queue(db)
    assert [
        _count(db, t) for t in ("impact_reviews", "exposure_reviews", "impact_assessment_revisions")
    ] == counts
    kinds = {i["kind"] for i in q}
    assert {"exposure_candidate", "event_item"} <= kinds
    assert all(i["why"] and i["decision_changes"] and i["previous_actor"] for i in q)


def test_explicit_human_decision_is_audited_and_cannot_repeat(db):
    _run(db, OIL)
    aid = db.execute("SELECT assessment_id FROM impact_assessments LIMIT 1")[0]["assessment_id"]
    with pytest.raises(ValueError):
        rv.record_impact_review(db, aid, "reject", reviewer=" ", notes="no reviewer")
    with pytest.raises(ValueError):
        rv.record_impact_review(db, aid, "accept", reviewer="Analyst A", notes="cannot accept scenario")
    a = rv.record_impact_review(db, aid, "needs_more_evidence", reviewer="Analyst A", notes="need filings")
    assert (a["assessment_status"], a["actor_type"], a["changed_by"]) == (
        "needs_review",
        "human",
        "Analyst A",
    )
    h = rv.review_history(db, aid)
    assert h[-1]["actor_type"] == "human" and h[-1]["review_id"] is not None
    rv.record_impact_review(db, aid, "reject", reviewer="Analyst A", notes="unsupported")
    with pytest.raises(DatabaseError):  # terminal: a further decision is refused by the database
        rv.record_impact_review(db, aid, "reject", reviewer="Analyst A", notes="again")


# ------------------------------------------------------------------ validation
def test_no_labels_means_no_scores(db):
    res = validation.evaluate({"items": []})
    assert (
        res["status"] == "insufficient_labelled_data"
        and res["metrics"] == []
        and "no accuracy" in res["note"]
    )
    assert res["market_outcomes"]["status"] == "not_evaluable"
    assert validation.load_labels()["items"] == []  # the shipped label file contains no invented labels


def _label(i, headline, **exp):
    return {
        "id": f"L{i}",
        "headline": headline,
        "published_at_utc": f"2026-0{1 + i % 9}-{10 + i % 18}T06:00:00Z",
        "publisher_domain": "dawn.com",
        "labeller": "test labeller",
        "expected": exp,
    }


def test_small_sample_lists_errors_but_reports_no_score():
    labels = {
        "items": [
            _label(1, "SBP raises policy rate to 13pc", primary_type="monetary_policy"),
            _label(2, "Weather stays pleasant in Lahore", primary_type="political"),
            _label(3, "OGDC posts higher quarterly profit", companies=["cmp-ogdc", "cmp-ppl"]),
        ]
    }
    res = validation.evaluate(labels)
    m = {x["metric"]: x for x in res["metrics"]}
    assert (
        m["classification"]["status"] == "insufficient_labelled_data" and "value" not in m["classification"]
    )
    assert any(
        f["kind"] == "classification" and f["reason"].startswith("no rule") for f in res["false_negatives"]
    )
    assert any(f["kind"] == "entity" and f["expected"] == "cmp-ppl" for f in res["false_negatives"])


def test_sufficient_sample_is_measured_against_human_labels():
    heads = ["SBP raises policy rate to {} pc", "Inflation eases to {} pc in survey"]
    types = ["monetary_policy", "economic_indicator"]
    items = [_label(i, heads[i % 2].format(10 + i), primary_type=types[i % 2]) for i in range(30)]
    items[0]["expected"]["primary_type"] = "fiscal_policy"  # one deliberate disagreement
    res = validation.evaluate({"items": items})
    m = {x["metric"]: x for x in res["metrics"]}["classification"]
    assert m["status"] == "measured" and m["n"] == 30 and m["value"] == round(29 / 30, 4)
    assert res["calibration"] == {"status": "insufficient_labelled_data"}


def test_invalid_label_file_is_refused(tmp_path):
    p = tmp_path / "labels.json"
    p.write_text(json.dumps({"items": [{"id": "x", "headline": "h"}]}))
    with pytest.raises(validation.LabelError):
        validation.load_labels(p)


# ------------------------------------------------------------------ pipeline, single writer, readiness
def test_run_all_holds_a_lease_and_reports_honestly(db):
    _item(db, OIL, at="2026-11-02T06:00:00Z")
    out = ip.run_all(db, synthetic=True)
    assert out["status"] == "succeeded" and out["stages"]["impact"]["assessments_created"] > 0
    run = db.execute("SELECT status, finished_at_utc FROM collector_runs WHERE job = 'intelligence'")[0]
    assert run["status"] == "succeeded" and run["finished_at_utc"]
    db.execute(
        "INSERT INTO collector_runs(job, started_at_utc, status) VALUES ('intelligence', "
        "strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'running')"
    )
    with pytest.raises(ip.Busy):
        ip.run_all(db, synthetic=True)
    assert {c["check"]: c["status"] for c in ip.readiness(db)["checks"]}["single writer"] == "ok"


def test_abandoned_lease_is_recovered_and_failures_are_recorded(db, monkeypatch):
    db.execute(
        "INSERT INTO collector_runs(job, started_at_utc, status) VALUES ('intelligence', "
        "'2026-01-01T00:00:00Z', 'running')"
    )
    monkeypatch.setattr(ip.hb, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        ip.run_all(db)
    rows = db.execute("SELECT status, errors FROM collector_runs WHERE job = 'intelligence' ORDER BY run_id")
    assert rows[0]["status"] == "failed" and "abandoned" in rows[0]["errors"]
    assert rows[1]["status"] == "failed" and "boom" in rows[1]["errors"]  # never reported as success
    assert ip.readiness(db)["overall"] == "fail"


def test_dashboard_guard_reports_database_outage():
    from engines import dashboard_views as dv

    def broken(_conn):
        raise DatabaseError("connection refused")

    assert dv._guard(broken, None) is None
