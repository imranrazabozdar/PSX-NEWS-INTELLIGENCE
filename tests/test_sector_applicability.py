"""Sector applicability matrix: classes, calculation guard, company sector link and negative cases.

SYNTHETIC checks of the rules. The matrix is a reviewed judgement, not a validation on real sector documents.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from engines import fundamentals as fu
from engines import sector_applicability as sa

ALL = ("CEMENT", "COMMERCIAL BANKS", "FERTILIZER")


def test_every_ratio_has_a_class_for_every_sector():
    rows = sa.matrix_rows()
    assert len(rows) == len({r["ratio"] for r in rows}) * len(sa.SECTORS)
    assert {r["class"] for r in rows} <= {"applicable", "conditional", "not_applicable"}


def test_banks_do_not_get_industrial_working_capital_ratios():
    for ratio in ("current_ratio", "inventory_days", "gross_margin", "asset_turnover", "debt_to_equity"):
        assert sa.applicability(ratio, "COMMERCIAL BANKS")[0] == "not_applicable", ratio
    assert sa.applicability("nim", "COMMERCIAL BANKS")[0] == "applicable"


def test_insurers_get_insurance_measures_and_no_current_ratio():
    assert sa.applicability("claims_ratio", "INSURANCE")[0] == "applicable"
    assert sa.applicability("combined_ratio", "INSURANCE")[0] == "applicable"
    assert sa.applicability("current_ratio", "INSURANCE")[0] == "not_applicable"


def test_industrial_sectors_are_not_given_bank_or_insurer_measures():
    assert sa.applicability("nim", "CEMENT")[0] == "not_applicable"
    assert sa.applicability("claims_ratio", "FERTILIZER")[0] == "not_applicable"


def test_upstream_inventory_days_is_conditional_not_applicable_by_default():
    assert sa.applicability("inventory_days", "OIL & GAS EXPLORATION COMPANIES")[0] == "conditional"


def test_undefined_ratio_is_not_applicable_by_default():
    assert sa.applicability("made_up_ratio", "CEMENT")[0] == "not_applicable"


def test_unknown_sector_is_refused():
    with pytest.raises(ValueError):
        sa.applicability("roe", "NOT A SECTOR")


def test_classify_is_not_calculable_for_a_not_applicable_ratio_even_with_inputs():
    c = sa.classify(
        "current_ratio",
        "COMMERCIAL BANKS",
        {"current_assets", "current_liabilities"},
        {"current_assets", "current_liabilities"},
    )
    assert c.state == "not_applicable"


def test_classify_reports_missing_inputs_instead_of_zero():
    c = sa.classify("roe", "COMMERCIAL BANKS", {"profit_after_tax"}, {"profit_after_tax", "total_equity"})
    assert c.state == "insufficient_data" and c.missing_inputs == ("total_equity",)


def test_conditional_ratio_is_never_reported_as_calculable_without_its_condition():
    c = sa.classify("production_growth", "OIL & GAS EXPLORATION COMPANIES", {"x"}, {"x"})
    assert c.state == "conditional_unverified"


def test_applicable_ratio_with_inputs_is_calculable():
    c = sa.classify("gross_margin", "CEMENT", {"gross_profit", "revenue"}, {"gross_profit", "revenue"})
    assert c.state == "calculable"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


def test_company_sector_link_is_read_from_the_master_data(db):
    assert sa.company_sector(db, "cmp-ogdc") == "OIL & GAS EXPLORATION COMPANIES"
    out = sa.company_applicability(db, "cmp-ogdc", ["roe", "current_ratio", "inventory_days"])
    assert out["state"] == "ok" and out["ratios"]["roe"] == "applicable"
    assert out["ratios"]["inventory_days"] == "conditional"


def test_analysis_output_reports_applicability_without_changing_values(db):
    rid = fin.import_report(
        db,
        {
            "company_ticker": "OGDC",
            "doc_type": "annual",
            "period_end": "2026-06-30",
            "scope": "unconsolidated",
            "currency": "PKR",
            "unit_scale": 1000,
            "audit_status": "audited",
            "filed_at_utc": "2026-09-04T00:00:00Z",
            "document_sha256": "9" * 64,
            "source": "synthetic_test",
            "original_url": None,
            "source_note": "synthetic",
            "lines": [
                {
                    "statement": "IS",
                    "raw_label": "Revenue",
                    "column_period_end": "2026-06-30",
                    "value": 1000.0,
                    "page": 1,
                    "canonical_code": "revenue",
                }
            ],
        },
        importer="o",
        rights_attestation="s",
    )["report_id"]
    fin.promote(db, rid)  # the analysis reads promoted metrics only
    a = fu.analyse(db, "cmp-ogdc", period_end="2026-06-30", as_of="2026-11-09")
    assert a["applicability"]["sector"] == "OIL & GAS EXPLORATION COMPANIES"
    assert a["ratios"]["gross_margin"]["state"] == "insufficient_data"  # value logic unchanged
