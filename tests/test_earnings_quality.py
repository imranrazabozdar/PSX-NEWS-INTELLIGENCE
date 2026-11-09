"""Earnings-quality indicators: hand-calculated cases, missing-data and period-mixing refusals.

SYNTHETIC and hand-checked. The indicators flag review items; they make no finding of manipulation.
"""

from __future__ import annotations

import pytest

from engines import earnings_quality as eq


def test_receivables_growing_far_faster_than_revenue_is_flagged_with_evidence():
    # revenue 100 -> 120 (+20%); receivables 50 -> 70 (+40%); gap +20 pp > 10 pp threshold
    i = eq.growth_gap_indicator(
        "receivables", "receivables", (120.0, 100.0), (70.0, 50.0), "FY2026", "consolidated"
    )
    assert i.state == "flag_for_review" and i.confidence == "medium"
    assert "+40.0%" in i.observed and "+20.0%" in i.observed
    assert i.alternative_explanations and i.additional_evidence_needed
    assert i.inputs["scope"] == "consolidated"


def test_growth_gap_within_threshold_is_not_flagged():
    i = eq.growth_gap_indicator(
        "inventory", "inventory", (110.0, 100.0), (115.0, 100.0), "FY2026", "unconsolidated"
    )
    assert i.state == "no_flag"  # gap +5 pp is inside the 10 pp review threshold


def test_zero_or_missing_prior_value_is_insufficient_not_zero_growth():
    i = eq.growth_gap_indicator(
        "receivables", "receivables", (120.0, 0.0), (70.0, 50.0), "FY2026", "unconsolidated"
    )
    assert i.state == "insufficient_data"
    j = eq.growth_gap_indicator(
        "receivables", "receivables", (120.0, None), (70.0, 50.0), "FY2026", "unconsolidated"
    )
    assert j.state == "insufficient_data"


def test_cash_conversion_hand_value_and_flag():
    i = eq.cash_conversion_indicator(
        100.0, 40.0, "FY2026", "unconsolidated"
    )  # 40 / 100 = 0.40 < 0.5 and cfo < pat
    assert i.state == "flag_for_review" and "0.40" in i.observed
    j = eq.cash_conversion_indicator(100.0, 90.0, "FY2026", "unconsolidated")
    assert j.state == "no_flag"


def test_cash_conversion_against_a_loss_is_not_computed():
    i = eq.cash_conversion_indicator(-5.0, 10.0, "Q1", "unconsolidated")
    assert i.state == "insufficient_data" and "not positive" in i.observed


def test_accrual_ratio_hand_value():
    # (PAT 120 - CFO 60) / average assets 400 = 0.15 > 0.10: flagged
    i = eq.accrual_indicator(120.0, 60.0, 400.0, "FY2026", "unconsolidated")
    assert i.state == "flag_for_review" and "+15.0%" in i.observed
    j = eq.accrual_indicator(120.0, 110.0, 400.0, "FY2026", "unconsolidated")
    assert j.state == "no_flag"  # 10 / 400 = 0.025


def test_missing_input_is_insufficient_data_not_a_flag():
    i = eq.accrual_indicator(120.0, None, 400.0, "FY2026", "unconsolidated")
    assert i.state == "insufficient_data"
    k = eq.accrual_indicator(120.0, 60.0, 0.0, "FY2026", "unconsolidated")
    assert k.state == "insufficient_data"  # zero denominator: not computed


def test_quarterly_and_annual_values_are_never_compared_for_growth():
    r = eq.yoy_growth(("Q1:2026", 100.0), ("FY:2025", 90.0))
    assert r["state"] == "refused"


def test_like_period_growth_is_calculated():
    r = eq.yoy_growth(("Q1:2026", 100.0), ("Q1:2025", 80.0))
    assert r["state"] == "ok" and r["growth"] == pytest.approx(0.25)


def test_every_indicator_states_its_limits_no_accusation_language():
    for i in (
        eq.growth_gap_indicator("receivables", "receivables", (120.0, 100.0), (70.0, 50.0), "FY2026", "x"),
        eq.cash_conversion_indicator(100.0, 40.0, "FY2026", "x"),
    ):
        text = (i.why_it_matters + " ".join(i.alternative_explanations)).lower()
        assert "manipulat" not in text and "fraud" not in text and "distress" not in text
        assert i.alternative_explanations
