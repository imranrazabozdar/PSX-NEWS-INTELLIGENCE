"""Earnings quality and audit signals (engines/earnings_quality.py). SYNTHETIC metric inputs only."""

from __future__ import annotations

import pytest

from engines import earnings_quality as eq


def m(**values):
    """Metric dict in fundamentals.metrics shape. Keys given are reported; the rest are missing."""
    return {k: {"value": v, "metric_id": i + 1, "basis": "reported"}
            for i, (k, v) in enumerate(values.items())}


CUR = m(revenue=1000.0, profit_after_tax=100.0, cfo=80.0, total_assets=2000.0, trade_receivables=200.0)
PRIOR = m(revenue=800.0, trade_receivables=150.0)


def test_cash_conversion_is_cfo_over_profit():
    r = eq.ratios(CUR, None)["cfo_to_profit"]
    assert r["state"] == "ok" and r["value"] == 0.8
    assert r["inputs"]["cfo"]["metric_id"] == 3          # the source row is kept with the number


def test_a_genuine_zero_is_a_value_but_a_missing_input_is_not_zero():
    zero = eq.ratios(m(revenue=1000.0, profit_after_tax=100.0, cfo=0.0, total_assets=2000.0), None)
    assert zero["cfo_to_profit"]["state"] == "ok" and zero["cfo_to_profit"]["value"] == 0.0
    missing = eq.ratios(m(revenue=1000.0, profit_after_tax=100.0, total_assets=2000.0), None)
    assert missing["cfo_to_profit"]["state"] == "insufficient_data"
    assert missing["cfo_to_profit"]["value"] is None
    assert missing["cfo_to_profit"]["missing"] == ["cfo"]


def test_loss_making_company_cash_conversion_is_not_applicable_not_strong():
    r = eq.ratios(m(profit_after_tax=-50.0, cfo=20.0), None)["cfo_to_profit"]
    assert r["state"] == "not_applicable" and r["value"] is None


def test_accruals_use_closing_assets_and_say_so():
    r = eq.ratios(CUR, None)["accruals_to_assets"]
    assert r["state"] == "ok" and r["value"] == round((100 - 80) / 2000, 4)
    assert "closing" in r["basis_note"]


def test_accruals_missing_cfo_is_reported_as_missing():
    r = eq.ratios(m(profit_after_tax=100.0, total_assets=2000.0), None)["accruals_to_assets"]
    assert r["state"] == "insufficient_data" and r["missing"] == ["cfo"]


def test_zero_total_assets_is_not_applicable():
    r = eq.ratios(m(profit_after_tax=100.0, cfo=80.0, total_assets=0.0), None)["accruals_to_assets"]
    assert r["state"] == "not_applicable"


def test_receivable_days_are_closing_receivables_over_revenue_times_365():
    r = eq.ratios(CUR, None)["receivable_days"]
    assert r["value"] == round(200 / 1000 * 365, 4)


def test_growth_divergence_needs_the_prior_year():
    r = eq.growth_divergence(CUR, None)
    assert r["state"] == "insufficient_data" and r["missing"] == ["prior period"]


def test_growth_divergence_is_receivables_growth_minus_revenue_growth():
    r = eq.growth_divergence(CUR, PRIOR)
    assert r["state"] == "ok"
    assert r["receivables_growth_pct"] == 33.33 and r["revenue_growth_pct"] == 25.0
    assert r["value"] == 8.33                             # receivables outgrew revenue by 8.33 points


def test_missing_prior_receivables_is_named_as_prior_year_missing():
    r = eq.growth_divergence(CUR, m(revenue=800.0))
    assert r["state"] == "insufficient_data" and r["missing"] == ["trade_receivables (prior)"]


def test_non_positive_prior_base_is_not_applicable():
    r = eq.growth_divergence(CUR, m(revenue=0.0, trade_receivables=150.0))
    assert r["state"] == "not_applicable"


def test_audit_facts_are_not_assumed_clean_when_not_reported():
    a = eq.audit_signals(None)
    assert a["opinion"]["state"] == "not_reported"
    assert a["key_audit_matters"]["state"] == "not_reported"
    assert a["going_concern_uncertainty"]["state"] == "not_reported"


def test_an_audit_opinion_without_evidence_is_refused():
    with pytest.raises(eq.EvidenceError):
        eq.audit_signals({"opinion": "unqualified"})


def test_audit_evidence_needs_a_real_page_and_an_excerpt():
    with pytest.raises(eq.EvidenceError):
        eq.audit_signals({"opinion": "qualified", "evidence": {"page": 0, "excerpt": "x"}})
    with pytest.raises(eq.EvidenceError):
        eq.audit_signals({"opinion": "qualified", "evidence": {"page": 12, "excerpt": "   "}})


def test_an_unknown_opinion_is_refused():
    with pytest.raises(eq.EvidenceError):
        eq.audit_signals({"opinion": "clean", "evidence": {"page": 3, "excerpt": "clean"}})


def test_a_qualified_opinion_is_reported_as_not_unqualified_with_its_page():
    ev = {"page": 214,
          "excerpt": "In our opinion, except for the matter described in the basis for qualified opinion"}
    a = eq.audit_signals({"opinion": "qualified", "key_audit_matters": 3, "evidence": ev})
    assert a["opinion"] == {"state": "reported", "value": "qualified", "is_unqualified": False}
    assert a["key_audit_matters"] == {"state": "reported", "value": 3}
    assert a["evidence"]["page"] == 214


def test_assess_keeps_only_reported_inputs_and_has_no_thresholds():
    result = eq.assess(m(revenue=1000.0, cfo=80.0), None)
    assert set(result["reported_inputs"]) == {"revenue", "cfo"}     # no zero-filled profit or assets
    keys = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(str(k).lower())
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(result)
    assert not keys & {"band", "bands", "grade", "verdict", "threshold", "score"}  # no grading, ever
    assert result["ratios"]["cfo_to_profit"]["state"] == "insufficient_data"


def test_assess_is_deterministic():
    assert eq.assess(CUR, PRIOR, None) == eq.assess(CUR, PRIOR, None)
