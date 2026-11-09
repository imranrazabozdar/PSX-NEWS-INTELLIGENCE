"""M3 hardening: average versus closing balances, approximations, missing values and scope isolation.

SYNTHETIC inputs; the arithmetic is checked by hand in each test.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from engines import fundamentals as fu


def _m(**vals):
    return {k: {"value": v, "metric_id": i + 1, "basis": "reported"} for i, (k, v) in enumerate(vals.items())}


def test_average_balance_ratio_is_insufficient_without_an_opening_balance_and_never_estimated():
    r = fu.ratio("asset_turnover_average", _m(revenue=1000.0, total_assets=2000.0), "corporate", 3)
    assert r["state"] == "insufficient_data" and r["missing"] == ["opening total_assets"]
    assert r["value"] is None


def test_average_balance_ratio_uses_opening_and_closing_and_is_annualised_for_a_quarter():
    m = _m(revenue=1000.0, total_assets=2000.0)
    opening = {"total_assets": {"value": 1600.0, "metric_id": 99, "basis": "reported"}}
    r = fu.ratio("asset_turnover_average", m, "corporate", 3, opening)
    assert r["value"] == pytest.approx(1000 * 4 / ((1600 + 2000) / 2))  # 2.222, annualised from a quarter
    assert r["basis"] == "average of opening and closing balance"


def test_closing_balance_ratios_keep_their_contract_and_say_so():
    r = fu.ratio("roe", _m(profit_after_tax=100.0, total_equity=1000.0), "corporate", 12)
    assert r["value"] == pytest.approx(0.1) and "closing" in r["formula"]
    assert "approximation" in r


def test_proxy_day_counts_are_labelled_as_proxies():
    r = fu.ratio("receivable_days", _m(trade_receivables=500.0, revenue=1000.0), "corporate", 3)
    assert "proxy" in r["approximation"] and r["period_basis"] == "days in a 3-month period"


def test_zero_or_negative_denominator_is_not_computable_not_zero():
    r = fu.ratio("roa", _m(profit_after_tax=100.0, total_assets=0.0), "corporate", 12)
    assert r["state"] == "not_computable" and r["value"] is None


def test_missing_input_is_insufficient_data_never_zero():
    r = fu.ratio("gross_margin", _m(revenue=1000.0), "corporate", 12)
    assert r["state"] == "insufficient_data" and r["value"] is None and r["missing"] == ["gross_profit"]


def test_debt_to_equity_is_unavailable_without_mapped_borrowings_even_with_liabilities_present():
    r = fu.ratio("debt_to_equity", _m(total_liabilities=500.0, total_equity=1000.0), "corporate", 12)
    assert r["state"] == "insufficient_data"  # total liabilities are never used as borrowings
    assert set(r["missing"]) == {"long_term_borrowings", "short_term_borrowings"}


def test_opening_balance_month_arithmetic_crosses_year_end():
    assert fu._months_before("2026-09-30", 3) == "2026-06-30"
    assert fu._months_before("2026-03-31", 3) == "2025-12-31"
    assert fu._months_before("2026-06-30", 12) == "2025-06-30"


def test_scope_isolation_a_consolidated_metric_never_feeds_an_unconsolidated_ratio():
    from engines.pdf_extraction import Page  # noqa: F401  (import check only)

    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    base = {
        "company_ticker": "OGDC",
        "doc_type": "quarterly",
        "period_end": "2026-09-30",
        "currency": "PKR",
        "unit_scale": 1000,
        "audit_status": "unaudited",
        "filed_at_utc": "2026-10-30T00:00:00Z",
        "document_sha256": "c" * 64,
        "source": "synthetic_test",
        "original_url": None,
        "source_note": "synthetic",
    }
    lines = [
        {
            "statement": "IS",
            "raw_label": "Revenue from contracts with customers",
            "column_period_end": "2026-09-30",
            "value": 1000.0,
            "page": 1,
        },
        {
            "statement": "IS",
            "raw_label": "Gross profit",
            "column_period_end": "2026-09-30",
            "value": 400.0,
            "page": 1,
        },
    ]
    fin.import_report(
        db, dict(base, scope="unconsolidated", lines=lines), importer="o", rights_attestation="s"
    )
    lines_c = [dict(ln, value=(ln["value"] * 2 if ln["value"] else None)) for ln in lines]
    fin.import_report(
        db,
        dict(base, scope="consolidated", document_sha256="d" * 64, lines=lines_c),
        importer="o",
        rights_attestation="s",
    )
    for r in db.execute("SELECT report_id FROM financial_reports"):
        fin.promote(db, r["report_id"])
    m = fu.metrics(db, "cmp-ogdc", "2026-09-30", "Q1", "unconsolidated", as_of="2026-11-09", strict=True)
    ids = {v["metric_id"] for v in m.values()}
    scopes = {
        r["scope"]
        for r in db.execute("SELECT metric_id, scope FROM financial_metrics")
        if r["metric_id"] in ids
    }
    assert scopes == {"unconsolidated"}  # every input metric came from the unconsolidated scope
    assert fu.ratio("gross_margin", m, "corporate", 3)["value"] == pytest.approx(0.4)  # 400 / 1000, not 800
    db.close()


def test_cash_conversion_hand_calculation_for_ogdc_quarter():
    """Definition: operating cash flow (cfo) over profit after tax, same period, same scope, both signed as
    reported. Hand check on the verified Q1 FY27 figures (Rs '000 scaled to PKR by the engine)."""
    m = _m(cfo=34393943.0, profit_after_tax=58513345.0)
    r = fu.ratio("cash_conversion", m, "corporate", 3)
    assert r["state"] == "ok" and r["value"] == pytest.approx(34393943 / 58513345)  # 0.5878
    assert "cfo / profit_after_tax" in r["formula"]


def test_cash_conversion_with_a_loss_is_not_computable_rather_than_a_strong_ratio():
    """A loss makes the denominator negative: the ratio has no economic meaning and is not shown."""
    r = fu.ratio("cash_conversion", _m(cfo=100.0, profit_after_tax=-50.0), "corporate", 3)
    assert r["state"] == "not_computable" and r["value"] is None


def test_payout_ratio_for_an_interim_period_carries_a_period_note():
    r = fu.ratio("payout_ratio", _m(dividends_paid=169977.0, profit_after_tax=58513345.0), "corporate", 3)
    assert "interim period" in r["period_note"] and r["value"] == pytest.approx(169977 / 58513345)
