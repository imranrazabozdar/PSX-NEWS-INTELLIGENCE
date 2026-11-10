"""Reconciliation statuses and deterministic metrics. Offline, pure functions; figures are invented."""

from __future__ import annotations

import pytest

from engines import institutional_metrics as m
from engines import statement_reconciliation as rec

# ------------------------------------------------------------------ reconciliation statuses


def test_balanced_identity_is_reconciled_and_one_unit_is_rounding():
    assert (
        rec.balance_sheet(
            "2025-06-30", {"total_assets": 1000.0, "total_liabilities": 600.0, "total_equity": 400.0}
        ).status
        == rec.RECONCILED
    )
    c = rec.balance_sheet(
        "2025-06-30", {"total_assets": 1000.0, "total_liabilities": 600.0, "total_equity": 399.0}
    )
    assert c.status == rec.ROUNDED and c.discrepancy == 1.0


def test_a_gap_beyond_the_allowance_is_unreconciled_with_the_exact_amount():
    c = rec.balance_sheet(
        "2025-06-30", {"total_assets": 1000.0, "total_liabilities": 600.0, "total_equity": 350.0}
    )
    assert c.status == rec.UNRECONCILED and c.discrepancy == 50.0


def test_a_missing_input_is_insufficient_data_and_never_zero():
    c = rec.cash_flow("2025-06-30", {"closing_cash": 70.0, "net_change_in_cash": -30.0})
    assert c.status == rec.INSUFFICIENT and c.missing == ("opening_cash",) and c.discrepancy is None


def test_overall_status_precedence():
    ok = rec.balance_sheet("p", {"total_assets": 1.0, "total_liabilities": 0.5, "total_equity": 0.5})
    rounded = rec.balance_sheet("p", {"total_assets": 1.0, "total_liabilities": 0.0, "total_equity": 2.0})
    bad = rec.balance_sheet("p", {"total_assets": 10.0, "total_liabilities": 0.0, "total_equity": 0.0})
    none = rec.cash_flow("p", {})
    assert rec.overall([ok]) == rec.RECONCILED
    assert rec.overall([ok, rounded]) == rec.ROUNDED
    assert rec.overall([ok, bad]) == rec.UNRECONCILED
    assert rec.overall([none]) == rec.INSUFFICIENT
    assert rec.overall([none, ok]) == rec.RECONCILED


def test_comparatives_flag_a_mismatch_and_need_both_values():
    assert rec.comparatives("comparative:revenue", "2024-06-30", 800.0, 800.0).status == rec.RECONCILED
    assert rec.comparatives("comparative:revenue", "2024-06-30", 800.0, 750.0).status == rec.UNRECONCILED
    assert rec.comparatives("comparative:revenue", "2024-06-30", None, 750.0).status == rec.INSUFFICIENT


# ------------------------------------------------------------------ metrics

V = {
    "revenue": 1000.0,
    "gross_profit": 400.0,
    "operating_profit": 250.0,
    "trade_receivables": 120.0,
    "inventory": 80.0,
    "trade_payables": 60.0,
    "cost_of_sales": -600.0,
    "cfo": 150.0,
    "profit_after_tax": 140.0,
    "total_assets": 500.0,
    "long_term_borrowings": 50.0,
    "short_term_borrowings": 30.0,
    "total_equity": 200.0,
    "cash_and_equivalents": 20.0,
    "finance_cost": -50.0,
    "capex": -40.0,
}
PRIOR = {"revenue": 800.0, "trade_receivables": 90.0}


def test_metric_values_match_the_hand_calculation():
    by = {x["metric"]: x for x in m.all_metrics(V, PRIOR)}
    assert by["gross_margin"]["value"] == pytest.approx(0.40)
    assert by["operating_margin"]["value"] == pytest.approx(0.25)
    assert by["cash_conversion_cycle"]["value"] == pytest.approx(
        365 * 120 / 1000 + 365 * 80 / 600 - 365 * 60 / 600
    )
    assert by["ocf_to_net_income"]["value"] == pytest.approx(150 / 140)
    assert by["accruals_ratio"]["value"] == pytest.approx((140 - 150) / 500)
    assert by["debt_to_equity"]["value"] == pytest.approx(80 / 200)
    assert by["net_debt"]["value"] == pytest.approx(80 - 20)
    assert by["interest_coverage"]["value"] == pytest.approx(5.0)
    assert by["free_cash_flow"]["value"] == pytest.approx(110.0)
    assert by["revenue_growth"]["value"] == pytest.approx(0.25)
    assert by["receivables_vs_sales_growth"]["value"] == pytest.approx(120 / 90 - 1 - 0.25)


def test_a_missing_input_is_reported_and_never_treated_as_zero():
    gm = m.gross_margin({"revenue": 1000.0})
    assert gm["value"] is None and gm["missing"] == ["current.gross_profit"]
    nd = m.net_debt({"long_term_borrowings": 50.0, "cash_and_equivalents": 20.0})
    assert nd["value"] is None and nd["missing"] == ["current.short_term_borrowings"]


def test_growth_without_a_prior_period_is_absent_not_zero():
    names = {x["metric"] for x in m.all_metrics(V)}
    assert "revenue_growth" not in names and "gross_margin" in names


def test_a_zero_denominator_gives_no_value():
    assert m.gross_margin({"revenue": 0.0, "gross_profit": 10.0})["value"] is None
    assert m.ocf_to_net_income({"cfo": 10.0, "profit_after_tax": -5.0})["value"] is None


def test_collection_days_is_receivables_over_revenue_times_365():
    assert m.collection_days({"trade_receivables": 120.0, "revenue": 1000.0})["value"] == pytest.approx(43.8)


def test_collection_days_needs_both_inputs_and_is_not_zero_when_revenue_is_zero():
    assert m.collection_days({"trade_receivables": 120.0})["missing"] == ["current.revenue"]
    assert m.collection_days({"trade_receivables": 120.0, "revenue": 0.0})["value"] is None


def test_working_capital_set_is_in_the_all_metrics_output():
    names = {x["metric"] for x in m.all_metrics(V, PRIOR)}
    assert {"cash_conversion_cycle", "collection_days", "receivables_vs_sales_growth"} <= names
