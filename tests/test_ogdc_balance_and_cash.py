"""Comparative balance promotion, cash definition, cash-flow adjustments block and average-balance M3.

SYNTHETIC statements only. Every expected value below is calculated by hand in the test.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from engines import fundamentals as fu
from engines import subtotals as st

CLOSE, OPEN = "2026-09-30", "2026-06-30"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


def _rec(lines, scope="unconsolidated", period=CLOSE, doc_type="quarterly", sha="a" * 64, restates=None):
    rec = {
        "company_ticker": "OGDC",
        "doc_type": doc_type,
        "period_end": period,
        "scope": scope,
        "currency": "PKR",
        "unit_scale": 1000,
        "audit_status": "unaudited",
        "filed_at_utc": "2026-10-30T00:00:00Z",
        "document_sha256": sha,
        "source": "synthetic_test",
        "original_url": None,
        "source_note": "synthetic",
        "lines": lines,
    }
    if restates:
        rec["restates_period_end"] = restates
    return rec


def _bs(code, col, value, label="Synthetic balance", page=10):
    return {
        "statement": "BS",
        "raw_label": label,
        "column_period_end": col,
        "value": value,
        "page": page,
        "canonical_code": code,
    }


def test_comparative_balance_at_fiscal_year_end_is_promoted_with_provenance(db):
    lines = [_bs("total_assets", CLOSE, 2000.0), _bs("total_assets", OPEN, 1600.0, "Total assets")]
    rid = fin.import_report(db, _rec(lines), importer="o", rights_attestation="s")["report_id"]
    r = fin.promote_balance_comparative(db, rid, OPEN)
    assert r["promoted"] == 1 and r["period_type"].startswith("FY")
    row = db.execute(
        "SELECT value, basis, calculation_method, scope FROM financial_metrics "
        "WHERE metric='total_assets' AND period_end=?",
        (OPEN,),
    )[0]
    assert row["value"] == 1600.0 * 1000 and row["basis"] == "reported" and row["scope"] == "unconsolidated"
    assert "source_label=Total assets" in row["calculation_method"] and "page=10" in row["calculation_method"]


def test_quarter_end_balance_is_refused_as_a_point_balance(db):
    lines = [_bs("total_assets", CLOSE, 2000.0), _bs("total_assets", OPEN, 1600.0)]
    rid = fin.import_report(db, _rec(lines), importer="o", rights_attestation="s")["report_id"]
    r = fin.promote_balance_comparative(db, rid, "2026-03-31")  # a quarter end, not a fiscal year end
    assert r["promoted"] == 0 and "not a fiscal year-end" in r["refused"]


def test_income_statement_comparative_is_never_promoted_by_the_balance_rule(db):
    lines = [
        {
            "statement": "IS",
            "raw_label": "Revenue",
            "column_period_end": OPEN,
            "value": 500.0,
            "page": 12,
            "canonical_code": "revenue",
        },
        _bs("total_assets", CLOSE, 2000.0),
    ]
    rid = fin.import_report(db, _rec(lines), importer="o", rights_attestation="s")["report_id"]
    r = fin.promote_balance_comparative(db, rid, OPEN)
    assert r["promoted"] == 0 and "no balance-sheet comparative" in r["refused"]


def test_a_different_existing_value_is_refused_not_overwritten(db):
    rid1 = fin.import_report(
        db,
        _rec([_bs("total_assets", OPEN, 1600.0)], sha="b" * 64, period=OPEN, doc_type="annual"),
        importer="o",
        rights_attestation="s",
    )["report_id"]
    assert (
        fin.promote_balance_comparative(db, rid1, OPEN)["refused"]
        == "current period balances are promoted by promote(), not this rule"
    )
    rid2 = fin.import_report(
        db,
        _rec([_bs("total_assets", CLOSE, 2100.0), _bs("total_assets", OPEN, 1650.0)], sha="c" * 64),
        importer="o",
        rights_attestation="s",
    )["report_id"]
    first = fin.promote_balance_comparative(db, rid2, OPEN)
    assert first["promoted"] == 1
    again = fin.promote_balance_comparative(db, rid2, OPEN)  # same value: nothing new
    assert again["promoted"] == 0 and "refused" not in again
    rid3 = fin.import_report(
        db,
        _rec(
            [_bs("total_assets", CLOSE, 2200.0), _bs("total_assets", OPEN, 1700.0)],
            sha="d" * 64,
            scope="unconsolidated",
            restates=None,
        ),
        importer="o",
        rights_attestation="s",
    )["report_id"]
    conflict = fin.promote_balance_comparative(db, rid3, OPEN)
    assert conflict["promoted"] == 0 and conflict["refused"] == "conflicting existing values"
    stored = db.execute(
        "SELECT value FROM financial_metrics WHERE metric='total_assets' AND period_end=?", (OPEN,)
    )
    assert [s["value"] for s in stored] == [1650.0 * 1000]  # the first value is kept, never overwritten


def test_scope_is_preserved_and_consolidated_balances_stay_separate(db):
    fin.import_report(
        db,
        _rec([_bs("total_assets", OPEN, 1600.0)], scope="unconsolidated", sha="e" * 64),
        importer="o",
        rights_attestation="s",
    )
    rid = fin.import_report(
        db,
        _rec([_bs("total_assets", OPEN, 1590.0)], scope="consolidated", sha="f" * 64),
        importer="o",
        rights_attestation="s",
    )["report_id"]
    assert fin.promote_balance_comparative(db, rid, OPEN)["promoted"] == 1
    rows = {
        r["scope"]: r["value"]
        for r in db.execute(
            "SELECT scope, value FROM financial_metrics WHERE metric='total_assets' AND period_end=?", (OPEN,)
        )
    }
    assert rows == {"consolidated": 1590.0 * 1000}


def test_cash_definition_explains_the_note_23_difference_and_keeps_both_measures():
    r = fin.cash_definition_check(39711514.0, 281746313.0, 321457827.0)
    assert r["result"] == "pass" and r["expected"] == 321457827.0
    assert (
        fin.cash_definition_check(39711614.0, 281746313.0, 321457827.0)["result"] == "fail"
    )  # 100 not explained
    assert fin.cash_definition_check(None, 281746313.0, 321457827.0)["result"] == "not_checkable"


def _cf_page(total_2026, total_2025, adj_offset=0):
    lines = [
        "CASH FLOWS FROM OPERATING ACTIVITIES",
        "Profit before income tax 1,000 800",
        "Adjustments for:",
        "Depreciation 300 250",
        "Royalty - 100",
        "Interest income (50) (40)",
        f"{total_2026:,} {total_2025:,}",
    ]
    return lines


def test_cash_flow_adjustments_subtotal_is_recognised_by_its_block_with_a_nil_dash():
    # PBT 1,000 + depreciation 300 + royalty nil + interest (50) = 1,250; 2025: 800 + 250 + 100 - 40 = 1,110
    lines = _cf_page(1250, 1110)
    lines[-1] = "1,250 1,110"
    res = st.analyse(lines, statement="CF", columns=["2026-09-30", "2025-09-30"], page=15)
    row = next(r for r in res if r["text"] == "1,250 1,110")
    assert row["status"] == "recognised" and row["rule"] == "R8_cf_adjustments_block"
    assert row["nil_items"] == 1 and row["code"] is None  # no canonical code invented


def test_cash_flow_adjustments_subtotal_off_by_one_is_not_recognised():
    lines = _cf_page(0, 0)
    lines[-1] = "1,251 1,110"
    res = st.analyse(lines, statement="CF", columns=["2026-09-30", "2025-09-30"], page=15)
    row = next(r for r in res if r["text"] == "1,251 1,110")
    assert row["status"] == "unresolved"


def _m(**vals):
    return {k: {"value": v, "metric_id": i + 1, "basis": "reported"} for i, (k, v) in enumerate(vals.items())}


def test_average_balance_ratios_use_promoted_opening_balances_with_hand_checks(db):
    close_lines = [
        {
            "statement": "IS",
            "raw_label": "Revenue",
            "column_period_end": CLOSE,
            "value": 1000.0,
            "page": 12,
            "canonical_code": "revenue",
        },
        {
            "statement": "IS",
            "raw_label": "Profit for the quarter",
            "column_period_end": CLOSE,
            "value": 100.0,
            "page": 12,
            "canonical_code": "profit_after_tax",
        },
        _bs("total_assets", CLOSE, 2000.0),
        _bs("total_equity", CLOSE, 1200.0),
        _bs("total_assets", OPEN, 1600.0),
        _bs("total_equity", OPEN, 1000.0),
    ]
    rid = fin.import_report(db, _rec(close_lines), importer="o", rights_attestation="s")["report_id"]
    fin.promote(db, rid)
    assert fin.promote_balance_comparative(db, rid, OPEN)["promoted"] == 2
    a = fu.analyse(db, "cmp-ogdc", period_end=CLOSE, as_of="2026-11-09", period_type="Q1")["ratios"]
    # asset turnover: revenue x4 / average assets = 1,000,000 x 4 / ((1,600,000 + 2,000,000) / 2)
    assert a["asset_turnover_average"]["value"] == pytest.approx(4_000_000 / 1_800_000)
    # ROE on average equity: PAT x4 / average equity = 100,000 x 4 / ((1,000,000 + 1,200,000) / 2)
    assert a["roe_average_balance"]["value"] == pytest.approx(400_000 / 1_100_000)
    # ROA on average assets: 100,000 x 4 / 1,800,000
    assert a["roa_average_assets"]["value"] == pytest.approx(400_000 / 1_800_000)
    assert a["roe_average_balance"]["basis"] == "average of opening and closing balance"


def test_average_ratios_are_insufficient_when_the_opening_balance_is_missing(db):
    close_lines = [
        {
            "statement": "IS",
            "raw_label": "Revenue",
            "column_period_end": CLOSE,
            "value": 1000.0,
            "page": 12,
            "canonical_code": "revenue",
        },
        _bs("total_assets", CLOSE, 2000.0),
    ]
    rid = fin.import_report(db, _rec(close_lines), importer="o", rights_attestation="s")["report_id"]
    fin.promote(db, rid)
    a = fu.analyse(db, "cmp-ogdc", period_end=CLOSE, as_of="2026-11-09", period_type="Q1")["ratios"]
    assert a["asset_turnover_average"]["state"] == "insufficient_data"
    assert a["asset_turnover_average"]["missing"] == ["opening total_assets"]
