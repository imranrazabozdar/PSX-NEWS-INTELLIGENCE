"""The three-lens council: evidence discipline, deterministic conflict detection, and provenance.

Offline. Every model answer is a recorded fixture; no network and no key is used.
"""

from __future__ import annotations

import json

import pytest

from engines import analyst_council as council
from engines import llm

EVENT = "Oil prices rise sharply after escalating conflict in the Middle East."

PACK = council.EvidencePack(event=EVENT, items=[
    council.Evidence("n1", "news", "Brent rose 9% in a day on Gulf supply fears.",
                     "Permitted newswire", "2026-11-14", company="OGDC"),
    council.Evidence("n2", "announcement", "PSO notified the exchange of no change to supply contracts.",
                     "PSX announcement", "2026-11-14", company="PSO"),
    council.Evidence("f1", "figure", "OGDC trade receivables PKR 412bn at 2026-06-30.",
                     "OGDC annual report 2026", "2026-09-12", company="OGDC"),
    council.Evidence("f2", "ratio", "OGDC current ratio 3.1 (computed by the data engine).",
                     "Computed from filed statements", "2026-09-12", company="OGDC"),
    council.Evidence("m1", "macro", "A rising oil import bill widens the current account deficit.",
                     "SBP bulletin", "2026-11-10", company="OGDC"),
    council.Evidence("m2", "sector_rule", "Energy is over 70% of cement production cost.",
                     "Cement sector capsule", "2026-11-01", company="LUCK"),
])


def _answer(assessments, unresolved=None):
    return json.dumps({"assessments": assessments, "unresolved": unresolved or []})


# The disagreement the council exists for: the news lens reads the oil rise as good for the producer,
# the macro lens sees the currency and rate damage, and the financial lens sees receivables exposure.
NEWS_SAYS = _answer([{"company": "OGDC", "direction": "benefit", "magnitude": "high",
                      "timing": "immediate", "reason": "Higher crude lifts realised prices.",
                      "evidence_ids": ["n1"], "confidence": "high"}])
MACRO_SAYS = _answer([{"company": "OGDC", "direction": "suffer", "magnitude": "medium",
                       "timing": "delayed", "reason": "A wider deficit pressures the rupee and rates.",
                       "evidence_ids": ["m1"], "confidence": "medium"},
                      {"company": "LUCK", "direction": "suffer", "magnitude": "high",
                       "timing": "delayed", "reason": "Energy is most of cement's cost base.",
                       "evidence_ids": ["m2"], "confidence": "high"}],
                     unresolved=["the current policy rate is not in the pack"])
FINANCIAL_SAYS = _answer([{"company": "OGDC", "direction": "unclear", "magnitude": "medium",
                           "timing": "delayed", "reason": "Receivables of PKR 412bn may not convert.",
                           "evidence_ids": ["f1"], "confidence": "medium"}])
SYNTHESIS = json.dumps({"conflicted": [{"company": "OGDC", "views": [],
                                        "what_would_settle_it": "the cash conversion of receivables"}],
                        "monitor": ["rupee and policy rate"], "caveats": ["not investment advice"],
                        "benefit": [{"company": "INVENTED", "why": "a narrative must not add this"}]})


def _gateway_for(answers: dict):
    def factory(role: str):
        return llm.LLMGateway(provider=llm.FixtureProvider(answers), pricing=llm.Pricing(0, 0))
    return factory


ALL_ANSWERS = {"n1": NEWS_SAYS, "f1": FINANCIAL_SAYS, "m1": MACRO_SAYS,
               "computed_conflicts": SYNTHESIS}


# ---------- each lens sees only its own evidence

def test_each_lens_is_shown_only_the_evidence_for_its_own_discipline():
    news, financial, macro = (PACK.for_role(r) for r in council.ROLES)
    assert "n1" in news and "f1" not in news and "m1" not in news
    assert "f1" in financial and "f2" in financial and "n1" not in financial
    assert "m1" in macro and "m2" in macro and "f1" not in macro
    assert EVENT in news and "OGDC" in news  # every lens gets the event and the known companies


# ---------- the data engine owns the facts: a model may not add a company or an uncited claim

def test_a_company_that_is_not_in_the_pack_is_dropped():
    raw = [{"company": "GHOST", "direction": "benefit", "evidence_ids": ["n1"]}]
    kept, dropped = council._clean_assessments(raw, PACK)
    assert kept == [] and "GHOST" in dropped[0]


def test_an_assessment_citing_no_evidence_from_the_pack_is_dropped():
    raw = [{"company": "OGDC", "direction": "benefit", "evidence_ids": ["made-up-id"]}]
    kept, dropped = council._clean_assessments(raw, PACK)
    assert kept == [] and "cites no evidence" in dropped[0]


def test_an_unknown_direction_is_dropped_rather_than_guessed():
    raw = [{"company": "OGDC", "direction": "very good", "evidence_ids": ["n1"]}]
    kept, dropped = council._clean_assessments(raw, PACK)
    assert kept == [] and "direction" in dropped[0]


# ---------- the core: a conflict is found by comparison, not by asking a model

def test_opposing_lenses_on_one_company_are_recorded_as_a_conflict():
    findings = [
        council.RoleFinding(role="news", outcome="ok", assessments=[council.Assessment(
            "OGDC", "benefit", "high", "immediate", "prices up", ("n1",), "high")]),
        council.RoleFinding(role="macro", outcome="ok", assessments=[council.Assessment(
            "OGDC", "suffer", "medium", "delayed", "rupee pressure", ("m1",), "medium")]),
    ]
    conflicts = council.detect_conflicts(findings)
    assert [c.company for c in conflicts] == ["OGDC"]
    assert set(conflicts[0].lenses) == {"news", "macro"}


def test_agreement_is_not_a_conflict_and_a_neutral_lens_does_not_create_one():
    findings = [
        council.RoleFinding(role="news", outcome="ok", assessments=[council.Assessment(
            "LUCK", "suffer", "high", "delayed", "cost up", ("m2",), "high")]),
        council.RoleFinding(role="macro", outcome="ok", assessments=[council.Assessment(
            "LUCK", "neutral", "low", "delayed", "no clear effect", ("m2",), "low")]),
    ]
    assert council.detect_conflicts(findings) == []
    assert [b["company"] for b in council.agreed(findings, "suffer")] == ["LUCK"]


def test_a_company_a_lens_opposes_is_kept_out_of_the_agreed_lists():
    findings = [
        council.RoleFinding(role="news", outcome="ok", assessments=[council.Assessment(
            "OGDC", "benefit", "high", "immediate", "prices up", ("n1",), "high")]),
        council.RoleFinding(role="macro", outcome="ok", assessments=[council.Assessment(
            "OGDC", "suffer", "medium", "delayed", "rupee pressure", ("m1",), "medium")]),
    ]
    assert council.agreed(findings, "benefit") == [] and council.agreed(findings, "suffer") == []


# ---------- end to end

def test_the_council_surfaces_the_conflict_instead_of_taking_the_first_answer():
    verdict = council.deliberate(PACK, _gateway_for(ALL_ANSWERS))
    assert set(verdict.lenses_that_answered) == {"news", "financial", "macro"}
    assert [c.company for c in verdict.conflicted] == ["OGDC"]
    # OGDC is contested, so it appears on neither agreed list, while LUCK stands unopposed.
    assert "OGDC" not in [b["company"] for b in verdict.benefit]
    assert [s["company"] for s in verdict.suffer] == ["LUCK"]
    assert "the current policy rate is not in the pack" in verdict.monitor


def test_every_finding_records_its_role_model_prompt_version_and_timestamp():
    verdict = council.deliberate(PACK, _gateway_for(ALL_ANSWERS), synthesise=False)
    for finding in verdict.findings:
        assert finding.role in council.ROLES and finding.model
        assert finding.prompt_id and finding.prompt_version and finding.created_at.endswith("Z")
    assert verdict.to_dict()["findings"][0]["prompt_version"] == "1.0.0"


def test_a_narrative_cannot_overturn_the_computed_comparison():
    verdict = council.deliberate(PACK, _gateway_for(ALL_ANSWERS))
    assert verdict.narrative is not None
    assert "benefit" not in verdict.narrative  # the invented company cannot reach the verdict
    assert "INVENTED" not in json.dumps(verdict.to_dict()["benefit"])


def test_the_council_goes_on_when_one_lens_cannot_answer():
    partial = {"n1": NEWS_SAYS, "m1": MACRO_SAYS, "computed_conflicts": SYNTHESIS}  # no financial answer
    verdict = council.deliberate(PACK, _gateway_for(partial))
    assert set(verdict.lenses_that_answered) == {"news", "macro"}
    assert [f.outcome for f in verdict.findings if f.role == "financial"] == ["error"]
    assert [c.company for c in verdict.conflicted] == ["OGDC"]


def test_a_verdict_needs_at_least_one_lens():
    with pytest.raises(council.CouncilError, match="no lens answered"):
        council.deliberate(PACK, _gateway_for({}))


def test_a_model_that_returns_prose_is_recorded_not_guessed_at():
    verdict = council.deliberate(PACK, _gateway_for({"n1": "I think oil is good.", "m1": MACRO_SAYS,
                                                     "computed_conflicts": SYNTHESIS}))
    news = next(f for f in verdict.findings if f.role == "news")
    assert news.outcome == "unparsable" and not news.assessments


# ---------- each lens runs on its own free-tier account

def test_each_role_prefers_its_own_groq_account_but_can_use_the_others():
    env = {"PSXNI_GROQ_API_KEY_ONE": "g1", "PSXNI_GROQ_API_KEY_TWO": "g2",
           "PSXNI_GROQ_API_KEY_THREE": "g3"}
    starts = []
    for role in council.ROLES:
        chosen = council.provider_for_role(role, env)
        assert isinstance(chosen, llm.RotatingProvider) and chosen.key_count == 3
        starts.append(chosen._providers[0]._key)
    assert starts == ["g1", "g2", "g3"]  # a different account leads for each lens


def test_a_role_falls_back_to_another_vendor_and_needs_no_claude():
    env = {"PSXNI_GROQ_API_KEY_ONE": "g1", "PSXNI_GEMINI_API_KEY_ONE": "m1",
           "PSXNI_OPENROUTER_API_KEY_ONE": "o1"}
    chain = council.provider_for_role("macro", env)
    assert [p.name for p in chain._providers] == ["groq", "gemini", "openrouter"]
    assert isinstance(council.provider_for_role("news", {}), llm.ClaudeProvider)
