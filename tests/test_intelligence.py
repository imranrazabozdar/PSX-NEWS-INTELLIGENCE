"""Phase 3 intelligence engine tests. Synthetic fixture items and recorded LLM outputs only:
no network, no live model. These prove the deterministic logic, not a live integration."""

from __future__ import annotations

import copy
import json

import pytest

from database import repositories as repo
from database import seed_loader
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import schema, similarity, verification
from engines.extraction import extract, relevance
from engines.llm import (
    ClaudeProvider,
    FixtureProvider,
    Limits,
    LLMGateway,
    Pricing,
    load_prompt,
)
from engines.pipeline import run

PRICE = Pricing(4.0, 20.0)

SBP_TEXT = ("SYNTHETIC FIXTURE. The State Bank of Pakistan's Monetary Policy Committee decided to "
            "cut the policy rate by 100 basis points to 10.5 percent, effective tomorrow. "
            "The committee said inflation had eased.")
DAWN_TEXT = ("SYNTHETIC FIXTURE. The State Bank of Pakistan cut its policy rate by 100 basis points "
             "to 10.5 percent on Thursday, according to a statement. Analysts expect lower "
             "financing costs for Lucky Cement and other borrowers.")
RUMOUR_TEXT = ("SYNTHETIC FIXTURE. Market chatter suggests Oil & Gas Development Company may announce "
               "a special dividend, sources said, though nothing has been confirmed.")


def event(**over):
    ev = {"event_type": "monetary_policy", "headline": "SBP cuts policy rate to 10.5%",
          "summary": "Policy rate reduced by 100bp.", "status_stage": "approval",
          "event_date": "2026-11-05", "event_date_precision": "day", "geography": "Pakistan",
          "direction": "positive", "magnitude": "high", "horizon": "immediate",
          "entities": [{"name": "State Bank of Pakistan", "entity_type": "regulator",
                        "quote": "State Bank of Pakistan"}],
          "indicators": [{"name": "policy rate", "value": 10.5, "unit": "percent", "period": "Nov-2026",
                          "quote": "10.5 percent"}],
          "claims": [{"claim": "Policy rate cut by 100bp to 10.5%", "claim_type": "official_statement",
                      "quote": "cut the policy rate by 100 basis points to 10.5 percent"}],
          "uncertainties": []}
    ev.update(over)
    return ev


def payload(*events, relevant=True):
    return {"is_relevant": relevant, "relevance_reason": "monetary policy", "events": list(events)}


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def gw(responses, db=None, **kw):
    return LLMGateway(FixtureProvider(responses, **kw), PRICE, db=db, sleep=lambda s: None)


def item(text, *, tier="primary_official", item_id=1, title="Policy rate decision", access="public"):
    return {"source_item_id": item_id, "title": title, "text": text, "reliability_tier": tier,
            "source_id": "sbp", "access_status": access, "published_at_utc": "2026-11-05T12:00:00Z"}


# ------------------------------------------------------------ schema
def test_schema_accepts_valid_and_rejects_extra_missing_and_bad_vocab():
    assert schema.validate_extraction(payload(event()))
    bad = payload(event())
    bad["events"][0]["price_target"] = 100
    del bad["events"][0]["horizon"]
    bad["events"][0]["direction"] = "bullish"
    with pytest.raises(schema.SchemaError) as e:
        schema.validate_extraction(bad)
    joined = " ".join(e.value.problems)
    assert "price_target: unexpected key" in joined and "horizon: missing" in joined
    assert "bullish" in joined


def test_schema_rejects_events_when_not_relevant_and_wrong_types():
    with pytest.raises(schema.SchemaError):
        schema.validate_extraction(payload(event(), relevant=False))
    with pytest.raises(schema.SchemaError):
        schema.validate_extraction(payload(event(indicators=[{"name": "x", "value": "10", "unit": None,
                                                               "period": None, "quote": "10"}])))


def test_dates_must_be_iso_and_unknown_dates_stay_unknown():
    with pytest.raises(schema.SchemaError):
        schema.validate_extraction(payload(event(event_date="last Thursday")))
    with pytest.raises(schema.SchemaError):
        schema.validate_extraction(payload(event(event_date=None)))  # precision 'day' without a date
    ok = event(event_date=None, event_date_precision="unknown", direction="unknown", magnitude="unknown",
               horizon="unknown", geography=None)
    res = extract(item(SBP_TEXT), gw({"Monetary": payload(ok)}))
    ev = res.candidates[0].event
    assert ev["event_date"] is None and ev["direction"] == "unknown" and ev["geography"] is None


def test_json_schema_is_strict():
    js = schema.json_schema()
    assert js["additionalProperties"] is False and set(js["required"]) == set(schema.TOP)
    ev = js["properties"]["events"]["items"]
    assert ev["additionalProperties"] is False and "enum" in ev["properties"]["event_type"]


# ------------------------------------------------------------ prompts and gateway
def test_prompt_is_versioned_and_forbids_invention():
    p = load_prompt("event_extraction_v1")
    assert p.prompt_id == "event_extraction" and p.version == "1.0.0" and len(p.sha256) == 64
    assert "must not invent" in p.text and "verbatim" in p.text


def test_gateway_ledger_tokens_cost_and_cache(db):
    g = gw({"Policy rate": payload(event())}, db=db)
    p = load_prompt("event_extraction_v1")
    first = g.complete(p, "Policy rate text", {})
    second = g.complete(p, "Policy rate text", {})
    assert first.outcome == "ok" and second.outcome == "cached" and g.provider.calls == 1
    rows = db.execute("SELECT outcome, input_tokens, output_tokens, cost_usd, prompt_version "
                      "FROM llm_calls ORDER BY call_id")
    assert [r["outcome"] for r in rows] == ["ok", "cached"]
    assert rows[0]["cost_usd"] > 0 and rows[0]["prompt_version"] == "1.0.0" and rows[1]["cost_usd"] == 0


def test_gateway_retries_transient_errors():
    g = gw({"x": payload(event())}, fail_first=2)
    out = g.complete(load_prompt("event_extraction_v1"), "x", {})
    assert out.outcome == "ok" and g.provider.calls == 3


def test_gateway_gives_up_after_max_attempts():
    g = gw({"x": payload(event())}, fail_first=5)
    out = g.complete(load_prompt("event_extraction_v1"), "x", {})
    assert out.outcome == "error" and out.text is None and g.provider.calls == 3


def test_daily_cost_limit_and_token_limit_refuse_before_calling(db):
    g = LLMGateway(FixtureProvider({"x": "{}"}), PRICE, Limits(daily_cost_usd=0.0001), db=db)
    assert g.complete(load_prompt("event_extraction_v1"), "x", {}).outcome == "refused_budget"
    g2 = LLMGateway(FixtureProvider({"x": "{}"}), PRICE, Limits(max_input_tokens=10))
    assert g2.complete(load_prompt("event_extraction_v1"), "x" * 500, {}).outcome == "refused_budget"
    assert g.provider.calls == 0 and g2.provider.calls == 0


def test_kill_switch_blocks_llm(monkeypatch):
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "1")
    g = gw({"x": "{}"})
    assert g.complete(load_prompt("event_extraction_v1"), "x", {}).outcome == "refused_kill_switch"
    assert g.provider.calls == 0


def test_claude_provider_is_not_connected_and_never_fakes_output():
    g = LLMGateway(ClaudeProvider(), PRICE, sleep=lambda s: None)
    out = g.complete(load_prompt("event_extraction_v1"), "x", {})
    assert out.outcome == "not_connected" and out.text is None


def test_llm_ledger_is_append_only(db):
    gw({"x": payload(event())}, db=db).complete(load_prompt("event_extraction_v1"), "x", {})
    with pytest.raises(DatabaseError):
        db.execute("UPDATE llm_calls SET cost_usd = 0")
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM llm_calls")


# ------------------------------------------------------------ extraction
def test_extraction_keeps_only_quoted_facts_and_explains_confidence():
    res = extract(item(SBP_TEXT), gw({"Monetary Policy Committee": payload(event())}))
    assert res.status == "extracted" and len(res.candidates) == 1
    c = res.candidates[0]
    assert c.event["claims"] and c.confidence > 0.7
    assert any("source tier primary_official" in w for w in c.confidence_explanation)
    assert c.importance_explanation and 0 < c.importance <= 1


def test_invented_claim_and_number_are_removed_and_flagged():
    ev = event(claims=[{"claim": "Rate cut to 9%", "claim_type": "official_statement",
                        "quote": "cut the policy rate to 9 percent"}],
               indicators=[{"name": "policy rate", "value": 9.0, "unit": "percent", "period": None,
                            "quote": "10.5 percent"}])
    res = extract(item(SBP_TEXT), gw({"Monetary": payload(ev)}))
    c = res.candidates[0]
    assert c.event["claims"] == [] and c.event["indicators"] == []
    assert any("no claim is supported" in r for r in c.review_reasons)
    assert any("value not present" in r for r in c.review_reasons)
    assert res.needs_human_review


def test_invalid_model_output_is_rejected_not_repaired():
    res = extract(item(SBP_TEXT), gw({"Monetary": "not json"}))
    assert res.status == "invalid_output" and not res.candidates and res.needs_human_review
    bad = payload(event(direction="buy"))
    res2 = extract(item(SBP_TEXT), gw({"Monetary": bad}))
    assert res2.status == "invalid_output"


def test_irrelevant_items_skip_the_llm_and_restricted_sources_are_not_processed():
    g = gw({})
    assert extract(item("A recipe for lemon cake.", title="Baking"), g).status == "skipped_prefilter"
    assert extract(item(SBP_TEXT, access="restricted"), g).status == "skipped_prefilter"
    assert g.provider.calls == 0
    assert relevance("x", "Pakistan raises petrol price")[0] > 0


def test_rumour_and_unresolved_company_need_review():
    ev = event(event_type="corporate_dividend", status_stage="rumour", magnitude="medium",
               entities=[{"name": "Oil & Gas Development Company", "entity_type": "company",
                          "quote": "Oil & Gas Development Company"},
                         {"name": "Unknown Holdings", "entity_type": "company", "quote": "sources said"}],
               indicators=[],
               claims=[{"claim": "Special dividend may be announced", "claim_type": "rumour",
                        "quote": "may announce a special dividend"}])
    resolver = {"oil & gas development company": [{"company_id": 7, "legal_name": "OGDCL"}]}
    res = extract(item(RUMOUR_TEXT, tier="established_media", title="Dividend talk"),
                  gw({"Market chatter": payload(ev)}),
                  resolve_company=lambda n: resolver.get(n.casefold(), []))
    c = res.candidates[0]
    assert c.companies[0]["company_id"] == 7
    assert any("rumour" in r for r in c.review_reasons)
    assert any("Unknown Holdings" in r for r in c.review_reasons)


# ------------------------------------------------------------ similarity and clustering
def test_near_duplicate_and_same_story_clustering():
    a = similarity.Doc(1, "SBP cuts policy rate", SBP_TEXT, "2026-11-05T12:00:00Z", frozenset({"sbp"}))
    dup = similarity.Doc(2, "SBP cuts policy rate", SBP_TEXT + " Reported.", "2026-11-05T13:00:00Z",
                         frozenset({"sbp"}))
    b = similarity.Doc(3, "State Bank cuts policy rate to 10.5pc", DAWN_TEXT, "2026-11-05T14:00:00Z",
                       frozenset({"sbp"}))
    other = similarity.Doc(4, "Cement despatches rise", "Cement despatches rose in October.",
                           "2026-11-05T14:00:00Z", frozenset({"cement"}))
    old = similarity.Doc(5, "SBP cuts policy rate", SBP_TEXT, "2026-10-01T12:00:00Z", frozenset({"sbp"}))
    assert similarity.similarity(a, dup)[1] is True
    clusters = similarity.cluster([other, b, dup, a, old])
    big = next(c for c in clusters if 1 in c.members)
    assert big.members == [1, 2, 3] and big.near_duplicates == {2: 1}
    assert any(c.members == [4] for c in clusters) and any(c.members == [5] for c in clusters)


# ------------------------------------------------------------ verification and timeline
def rep(item_id, owner, tier, stage="approval", value=10.5, dup=None, ts="2026-11-05T12:00:00Z"):
    ev = event(status_stage=stage)
    ev["indicators"][0]["value"] = value
    return verification.Report(item_id, owner, owner, tier, ts, ev, 0.7, dup)


def test_primary_confirmation_and_media_corroboration():
    a0 = verification.assess([rep(1, "sbp", "primary_official"), rep(2, "dawn", "established_media")])
    assert a0.verification_state == "primary_confirmed"
    a = verification.assess([rep(1, "dawn", "established_media"), rep(2, "brecorder", "established_media")])
    assert a.verification_state == "corroborated" and a.confidence > 0.7


def test_syndicated_copies_do_not_count_as_independent():
    a = verification.assess([rep(1, "dawn", "established_media"),
                             rep(2, "tribune", "established_media", dup=1)])
    assert a.verification_state == "single_source" and a.independent_sources == ["dawn"]
    assert a.needs_human_review


def test_contradictions_are_detected_and_lower_confidence():
    a = verification.assess([rep(1, "dawn", "established_media", stage="approval"),
                             rep(2, "brecorder", "established_media", stage="reversal", value=11.5)])
    assert a.verification_state == "disputed" and a.needs_human_review
    assert any("stage" in c for c in a.contradictions) and any("policy rate" in c for c in a.contradictions)
    assert a.confidence < 0.7


def test_timeline_orders_and_marks_stage_changes():
    t = verification.timeline([rep(2, "b", "established_media", "approval", ts="2026-11-06T00:00:00Z"),
                               rep(1, "a", "established_media", "proposal", ts="2026-11-01T00:00:00Z"),
                               rep(3, "c", "established_media", "implementation", ts=None)])
    assert [x["item_id"] for x in t] == [1, 2, 3]
    assert [x["stage_changed"] for x in t] == [False, True, True] and t[2]["time_known"] is False


# ------------------------------------------------------------ end-to-end persistence (local SQLite)
def _fixture_sources(db):
    for sid, typ, tier in (("fxofficial", "official_regulator", "primary_official"),
                           ("fxmedia", "news_media", "established_media")):
        db.execute("INSERT INTO sources(source_id, name, source_type, reliability_tier, owner, "
                   "created_at_utc, updated_at_utc) "
                   "VALUES (?,?,?,?,?,?,?)", (sid, f"Synthetic {sid}", typ, tier, sid, "2026-11-07T00:00:00Z",
                                              "2026-11-07T00:00:00Z"))


def _store(db, source, url, title, text, ts):
    return repo.record_source_item(db, source_id=source, url=url, title=title, content=text,
                                   excerpt=text, collected_at_utc="2026-11-05T15:00:00Z",
                                   published_at_utc=ts).source_item_id


def test_pipeline_persists_events_evidence_provenance_and_cross_source_assessment(db):
    _fixture_sources(db)
    _store(db, "fxofficial", "https://sbp.example/mpc", "SBP cuts policy rate", SBP_TEXT,
           "2026-11-05T12:00:00Z")
    _store(db, "fxmedia", "https://dawn.example/rate", "SBP cuts policy rate to 10.5pc", DAWN_TEXT,
           "2026-11-05T13:00:00Z")
    dawn_ev = event(claims=[{"claim": "Policy rate cut to 10.5%", "claim_type": "news_report",
                             "quote": "cut its policy rate by 100 basis points to 10.5 percent"}])
    g = gw({"Monetary Policy Committee": payload(event()), "according to a statement": payload(dawn_ev)},
           db=db)
    s = run(db, g)
    assert s.processed == 2 and s.events_created == 2 and s.clusters == 1
    evs = db.execute("SELECT verification_state, current_revision FROM events")
    assert {e["verification_state"] for e in evs} == {"primary_confirmed"}
    assert all(e["current_revision"] == 2 for e in evs)
    ev = repo.event_with_evidence(db, 1)
    assert ev["evidence"] and "10.5 percent" in ev["evidence"][0]["excerpt"]
    x = db.execute("SELECT provenance_json, prompt_version, model FROM event_extractions "
                   "ORDER BY extraction_id LIMIT 1")[0]
    prov = json.loads(x["provenance_json"])
    assert prov["source_id"] == "fxofficial" and prov["published_at_utc"] == "2026-11-05T12:00:00Z"
    assert {"retrieval_method", "collected_at_utc", "access_status", "licence_status", "data_status",
            "published_tz_offset"} <= set(prov)
    assert x["prompt_version"] == "1.0.0" and x["model"] == "fixture-model"
    assert db.execute("SELECT COUNT(*) n FROM event_extractions e JOIN source_items i "
                      "USING(source_item_id) WHERE i.source_id = 'psx_dps'")[0]["n"] == 0
    assert run(db, g).processed == 0  # already extracted items are not re-sent to the LLM


def test_pipeline_records_unavailable_llm_without_inventing_events(db):
    _fixture_sources(db)
    _store(db, "fxofficial", "https://sbp.example/mpc", "SBP cuts policy rate", SBP_TEXT,
           "2026-11-05T12:00:00Z")
    s = run(db, LLMGateway(ClaudeProvider(), PRICE, db=db))
    assert s.events_created == 0 and s.statuses == {"llm_unavailable": 1} and s.review_flags == 1
    row = db.execute("SELECT needs_human_review FROM event_extractions")[0]
    assert row["needs_human_review"] == 1
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM event_extractions")


def test_fixture_payload_not_mutated_by_extraction():
    p = payload(event())
    snapshot = copy.deepcopy(p)
    extract(item(SBP_TEXT), gw({"Monetary": p}))
    assert p == snapshot
