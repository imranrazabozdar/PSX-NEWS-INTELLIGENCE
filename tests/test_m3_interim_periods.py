"""M3 ratio periods: interim flows are not compared with annual balances (pilot defect found on OGDCL).

Synthetic inputs only. The arithmetic is checked by hand; no real company figure is used here.
"""

from __future__ import annotations

import pytest

from engines import fundamentals as fu


def _m(**vals):
    return {k: {"value": v, "metric_id": i + 1, "basis": "reported"} for i, (k, v) in enumerate(vals.items())}


def test_receivable_days_for_a_quarter_uses_the_days_in_the_quarter_not_365():
    m = _m(trade_receivables=500.0, revenue=1000.0)
    q = fu.ratio("receivable_days", m, "corporate", 3)
    assert q["value"] == pytest.approx(365 * 3 / 12 * 500 / 1000)  # 45.625 days, not 182.5
    assert q["period_basis"] == "days in a 3-month period"


def test_asset_turnover_and_returns_for_a_quarter_are_annualised():
    m = _m(revenue=1000.0, total_assets=2000.0, profit_after_tax=100.0, total_equity=1000.0)
    assert fu.ratio("asset_turnover", m, "corporate", 3)["value"] == pytest.approx(0.5 * 4)
    assert fu.ratio("roe", m, "corporate", 3)["value"] == pytest.approx(0.1 * 4)
    assert fu.ratio("roa", m, "corporate", 3)["value"] == pytest.approx(0.05 * 4)


def test_annual_figures_are_unchanged():
    m = _m(trade_receivables=500.0, revenue=1000.0, total_assets=2000.0)
    assert fu.ratio("receivable_days", m, "corporate", 12)["value"] == pytest.approx(182.5)
    assert fu.ratio("asset_turnover", m, "corporate", 12)["value"] == pytest.approx(0.5)


def test_flow_over_flow_ratios_are_not_scaled():
    m = _m(gross_profit=300.0, revenue=1000.0)
    assert fu.ratio("gross_margin", m, "corporate", 3)["value"] == pytest.approx(0.3)


def test_period_months_table_covers_every_interim_type():
    assert fu.PERIOD_MONTHS["Q1"] == 3 and fu.PERIOD_MONTHS["H1"] == 6 and fu.PERIOD_MONTHS["9M"] == 9
    assert fu.PERIOD_MONTHS["FY"] == 12
