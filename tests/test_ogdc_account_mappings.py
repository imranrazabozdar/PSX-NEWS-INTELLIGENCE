"""Owner-approved OGDC mappings, the rejected amortisation mapping, cash-flow codes and the cash identity.

SYNTHETIC statements only. Labels are the exact OGDC wording; every figure is invented for testing.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin

COLS = {
    "IS": ["2026-09-30", "2025-09-30"],
    "CF": ["2026-09-30", "2025-09-30"],
    "BS": ["2026-09-30", "2026-06-30"],
}


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


def _rec(lines, doc_type="quarterly", ticker="OGDC", scope="unconsolidated", period="2026-09-30"):
    return {
        "company_ticker": ticker,
        "doc_type": doc_type,
        "period_end": period,
        "scope": scope,
        "currency": "PKR",
        "unit_scale": 1000,
        "audit_status": "unaudited",
        "filed_at_utc": "2026-10-30T00:00:00Z",
        "document_sha256": "a" * 64,
        "source": "synthetic_test",
        "original_url": None,
        "source_note": "synthetic",
        "lines": lines,
    }


def _ln(st, label, col, value, page=1):
    return {"statement": st, "raw_label": label, "column_period_end": col, "value": value, "page": page}


def _codes(db):
    return {
        (r["raw_label"], r["canonical_code"])
        for r in db.execute(
            "SELECT raw_label, canonical_code FROM financial_line_items WHERE canonical_code IS NOT NULL"
        )
    }


def test_approved_quarterly_profit_and_eps_mappings_apply_to_ogdc_quarterly_statements(db):
    lines = [
        _ln("IS", "Profit before income tax", "2026-09-30", 87988861.0),
        _ln("IS", "Profit for the quarter", "2026-09-30", 58513345.0),
        _ln("IS", "Earnings per share- basic and diluted (Rupees)", "2026-09-30", 13.60),
    ]
    r = fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    got = _codes(db)
    assert ("Profit before income tax", "profit_before_tax") in got
    assert ("Profit for the quarter", "profit_after_tax") in got
    assert ("Earnings per share- basic and diluted (Rupees)", "eps_basic") in got  # combined wording kept
    assert r["checks"]  # the company mapping feeds the reconciliation


def test_quarterly_label_is_not_applied_to_an_annual_statement(db):
    lines = [_ln("IS", "Profit for the quarter", "2026-06-30", 1.0)]
    fin.import_report(
        db, _rec(lines, doc_type="annual", period="2026-06-30"), importer="o", rights_attestation="synthetic"
    )
    assert ("Profit for the quarter", "profit_after_tax") not in _codes(db)


def test_company_mapping_is_not_applied_to_another_company(db):
    lines = [_ln("IS", "Profit before income tax", "2026-09-30", 100.0)]
    fin.import_report(db, _rec(lines, ticker="LUCK"), importer="o", rights_attestation="synthetic")
    assert ("Profit before income tax", "profit_before_tax") not in _codes(db)


def test_consolidated_and_unconsolidated_are_mapped_separately_and_never_mixed(db):
    lines = [_ln("IS", "Profit before income tax", "2026-09-30", 100.0)]
    fin.import_report(db, _rec(lines, scope="unconsolidated"), importer="o", rights_attestation="synthetic")
    fin.import_report(db, _rec(lines, scope="consolidated"), importer="o", rights_attestation="synthetic")
    rows = db.execute(
        "SELECT fr.scope, COUNT(*) n FROM financial_line_items fl JOIN financial_reports fr USING(report_id) "
        "WHERE fl.canonical_code='profit_before_tax' GROUP BY fr.scope"
    )
    assert {r["scope"]: r["n"] for r in rows} == {"unconsolidated": 1, "consolidated": 1}


def test_rejected_amortisation_mapping_is_not_applied_and_the_new_code_is(db):
    lines = [_ln("CF", "Amortization of development and production assets", "2026-09-30", 6693123.0)]
    fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    got = _codes(db)
    assert ("Amortization of development and production assets", "depreciation_amortisation") not in got
    assert ("Amortization of development and production assets", "amortisation_expense") in got


def test_cash_flow_codes_map_and_the_cash_identity_is_checked(db):
    lines = [
        _ln("CF", "Net cash generated from operating activities", "2026-09-30", 34393943.0),
        _ln("CF", "Net cash (used in) /generated from investing activities", "2026-09-30", -3033067.0),
        _ln("CF", "Net cash used in financing activities", "2026-09-30", -505360.0),
        _ln("CF", "Net increase /(decrease) in cash and cash equivalents", "2026-09-30", 30855516.0),
        _ln("CF", "Cash and cash equivalents at end of the quarter", "2026-09-30", 321457827.0),
    ]
    r = fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    check = next(c for c in r["checks"] if c["check"] == "cash_movement")
    assert check["result"] == "pass" and check["expected"] == 30855516.0
    codes = {c for _, c in _codes(db)}
    assert {"cfi", "cff", "net_change_in_cash", "cash_closing"} <= codes


def test_cash_identity_failure_is_reported_not_forced(db):
    lines = [
        _ln("CF", "Net cash generated from operating activities", "2026-09-30", 100.0),
        _ln("CF", "Net cash (used in) /generated from investing activities", "2026-09-30", 0.0),
        _ln("CF", "Net cash used in financing activities", "2026-09-30", 0.0),
        _ln("CF", "Net increase /(decrease) in cash and cash equivalents", "2026-09-30", 500.0),
    ]
    r = fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    assert next(c for c in r["checks"] if c["check"] == "cash_movement")["result"] == "fail"
    assert r["status"] == "needs_review"


def test_cash_closing_is_distinct_from_balance_sheet_cash(db):
    """Same period, different measures: they must never share a canonical code."""
    lines = [
        _ln("BS", "Cash and bank balances", "2026-09-30", 39711514.0),
        _ln("CF", "Cash and cash equivalents at end of the quarter", "2026-09-30", 321457827.0),
    ]
    fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    rows = {
        r["canonical_code"]: r["value"]
        for r in db.execute(
            "SELECT canonical_code, value FROM financial_line_items WHERE canonical_code IN "
            "('cash_and_equivalents','cash_closing')"
        )
    }
    assert rows == {"cash_and_equivalents": 39711514.0, "cash_closing": 321457827.0}


def test_unknown_canonical_code_is_refused(db):
    lines = [dict(_ln("IS", "Something", "2026-09-30", 1.0), canonical_code="made_up_code")]
    with pytest.raises(fin.ImportError_, match="unknown canonical code"):
        fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")


def test_other_income_is_not_populated_from_a_combined_line(db):
    lines = [_ln("IS", "Finance and other income", "2026-09-30", 13771984.0)]
    fin.import_report(db, _rec(lines), importer="o", rights_attestation="synthetic")
    assert all(c != "other_income" for _, c in _codes(db))
