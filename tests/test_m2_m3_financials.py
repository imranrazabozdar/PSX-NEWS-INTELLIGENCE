"""M2 financial statement import/mapping/reconciliation and M3 fundamentals.

The statements here are SYNTHETIC hand-built fixtures with hand-calculated expected values. They test the
logic only and are not evidence of extraction accuracy on real reports (that needs U3 and real report
fixtures, MASTER_VALIDATION_STRATEGY.md section 2).
"""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from engines import fundamentals as fu

SHA = "a" * 64


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


LABELS = {
    "IS": ["Net sales", "Cost of sales", "Gross profit", "Operating profit", "Finance cost",
           "Profit before taxation", "Taxation", "Profit for the year",
           "Earnings per share - basic and diluted"],
    "BS": ["Total assets", "Total liabilities", "Total equity", "Total current assets",
           "Total current liabilities", "Long term financing", "Short term borrowings", "Mystery reserve"],
    "CF": ["Net cash generated from operating activities", "Purchase of property, plant and equipment"],
}
# hand-built figures (PKR thousands) per fiscal year end; None = not reported
YEARS = {
    "2023-06-30": [700.0, -450.0, 250.0, 180.0, -35.0, 145.0, -45.0, 100.0, 10.0,
                   400.0, 250.0, 150.0, 180.0, 90.0, 95.0, None, 5.0, 100.0, -50.0],
    "2024-06-30": [800.0, -500.0, 300.0, 200.0, -40.0, 160.0, -50.0, 110.0, 11.0,
                   450.0, 280.0, 170.0, 200.0, 100.0, 90.0, None, 5.0, 120.0, -60.0],
    "2025-06-30": [1000.0, -600.0, 400.0, 250.0, -50.0, 200.0, -60.0, 140.0, 14.0,
                   500.0, 300.0, 200.0, 220.0, 110.0, 80.0, 20.0, 5.0, 175.0, -70.0],
}
YEARS["2025-03-31"] = YEARS["2025-06-30"]
YEARS["2024-03-31"] = YEARS["2024-06-30"]
YEARS["2024-12-31"] = YEARS["2025-06-30"]
YEARS["2023-12-31"] = YEARS["2024-06-30"]
ORDER = [(st, lab) for st in ("IS", "BS", "CF") for lab in LABELS[st]]


def _corp(period="2025-06-30", prev="2024-06-30", sha=SHA, overrides=None, **kw):
    lines = []
    for col in (period, prev):
        for (st, lab), v in zip(ORDER, YEARS[col], strict=True):
            v = (overrides or {}).get((lab, col), v)
            lines.append({"statement": st, "raw_label": lab, "column_period_end": col, "value": v})
    rec = {"company_ticker": "OGDC", "doc_type": "annual", "period_end": period, "scope": "unconsolidated",
           "currency": "PKR", "unit_scale": 1000, "audit_status": "audited", "auditor_opinion": "unmodified",
           "document_sha256": sha, "original_url": None, "lines": lines}
    rec.update(kw)
    return rec


def _imp(db, rec):
    return fin.import_report(db, rec, importer="owner", rights_attestation="downloaded from company website")


# ---------------------------------------------------------------- parsing
def test_parse_numbers_and_blanks():
    assert fin.parse_number("1,234") == 1234 and fin.parse_number("(1,234.5)") == -1234.5
    assert fin.parse_number("-") is None and fin.parse_number("—") is None
    with pytest.raises(ValueError):
        fin.parse_number("12a")


def test_parse_statement_text_with_note_refs_and_unparsed():
    text = """Net sales 24 12,345 11,000
Cost of sales (9,000) (8,100)
Other income - 120
Profit for the year 3,345
Total equity and liabilities"""
    r = fin.parse_statement_text(text, statement="IS", columns=["2025-06-30", "2024-06-30"], page=3)
    vals = {(ln["raw_label"], ln["column_period_end"]): ln["value"] for ln in r["lines"]}
    assert vals[("Net sales", "2025-06-30")] == 12345 and vals[("Cost of sales", "2024-06-30")] == -8100
    assert vals[("Other income", "2025-06-30")] is None  # dash: not reported, never zero
    assert {u["line"] for u in r["unparsed"]} == {"Profit for the year 3,345", "Total equity and liabilities"}


# ---------------------------------------------------------------- import / mapping / reconciliation
def test_import_maps_reconciles_and_flags_unmapped(db):
    r = _imp(db, _corp())
    assert r["status"] == "reconciled" and r["framework"] == "corporate"
    assert {c["check"]: c["result"] for c in r["checks"]} == {
        "balance_sheet": "pass", "gross_profit": "pass", "profit_after_tax": "pass"}
    assert r["unmapped"] == ["Mystery reserve"]
    blank = db.execute("SELECT value, value_state FROM financial_line_items WHERE raw_label = "
                       "'Short term borrowings' AND column_period_end = '2024-06-30'")[0]
    assert blank["value"] is None and blank["value_state"] == "not_reported"
    assert _imp(db, _corp())["status"] == "duplicate"


def test_failed_reconciliation_blocks_promotion(db):
    r = _imp(db, _corp(overrides={("Total assets", "2025-06-30"): 999.0}))
    assert r["status"] == "needs_review"
    assert fin.promote(db, r["report_id"])["promoted"] == 0
    assert not db.execute("SELECT 1 FROM financial_metrics")


def test_promote_scales_units_and_skips_not_reported(db):
    r = _imp(db, _corp())
    p = fin.promote(db, r["report_id"])
    assert p["period_type"] == "FY" and p["basis"] == "reported"
    m = {x["metric"]: x for x in db.execute("SELECT metric, value, unit FROM financial_metrics")}
    assert m["revenue"]["value"] == 1_000_000 and m["revenue"]["unit"] == "PKR"
    assert m["eps_basic"]["value"] == 14.0 and m["eps_basic"]["unit"] == "PKR/share"
    assert all(x["value"] is not None for x in m.values())
    assert db.execute("SELECT COUNT(*) n FROM financial_metrics WHERE period_end = '2024-06-30'")[0]["n"] == 0


def test_line_items_append_only(db):
    _imp(db, _corp())
    with pytest.raises(DatabaseError):
        db.execute("UPDATE financial_line_items SET value = 1")
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM financial_line_items")


def test_rejects_unknown_ticker_and_bad_input(db):
    with pytest.raises(fin.ImportError_):
        _imp(db, _corp(company_ticker="NOPE"))
    with pytest.raises(fin.ImportError_):
        _imp(db, _corp(document_sha256="short"))
    with pytest.raises(fin.ImportError_):
        fin.import_report(db, _corp(), importer="owner", rights_attestation="")


def test_comparative_change_is_flagged(db):
    _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64))
    r = _imp(db, _corp(overrides={("Net sales", "2024-06-30"): 790.0}))  # comparative restated
    assert [(c["canonical_code"], c["earlier"], c["value"]) for c in r["comparative_changes"]] == [
        ("revenue", 800.0, 790.0)]


def test_interim_period_labels(db):
    q = _corp(period="2025-03-31", prev="2024-03-31", sha="c" * 64, doc_type="nine_month")
    assert fin.promote(db, _imp(db, q)["report_id"])["period_type"] == "9M"
    h = _corp(period="2024-12-31", prev="2023-12-31", sha="d" * 64, doc_type="half_yearly")
    assert fin.promote(db, _imp(db, h)["report_id"])["period_type"] == "H1"  # OGDC fiscal year ends June


def test_mapping_versions_are_append_only(db):
    v = fin.add_mapping(db, framework="corporate", statement="BS", label="Mystery reserve",
                        canonical_code="other_reserves", approved_by="owner")
    assert v == 1
    assert fin.add_mapping(db, framework="corporate", statement="BS", label="Mystery reserve",
                           canonical_code="reserves", approved_by="owner") == 2
    with pytest.raises(DatabaseError):
        db.execute("UPDATE account_mappings SET canonical_code = 'x'")


# ---------------------------------------------------------------- fundamentals
def _two_years(db):
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64))["report_id"])
    fin.promote(db, _imp(db, _corp())["report_id"])


def test_ratios_hand_calculated(db):
    _two_years(db)
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30")
    r = {k: v["value"] for k, v in a["ratios"].items()}
    assert r["gross_margin"] == pytest.approx(0.4) and r["net_margin"] == pytest.approx(0.14)
    assert r["roe"] == pytest.approx(0.7) and r["current_ratio"] == pytest.approx(2.0)
    assert r["debt_to_equity"] == pytest.approx(0.5) and r["interest_cover"] == pytest.approx(5.0)
    assert r["cash_conversion"] == pytest.approx(1.25)
    assert a["ratios"]["advances_to_deposits"]["state"] == "not_applicable"  # bank ratio on a non-bank
    assert a["ratios"]["car_pct"]["state"] == "not_applicable"
    assert a["growth"]["revenue"]["value"] == pytest.approx(0.25)
    assert a["fcf"]["value"] == 105_000


def test_missing_inputs_are_insufficient_not_zero(db):
    rec = _corp()
    rec["lines"] = [ln for ln in rec["lines"] if ln["raw_label"] != "Total current liabilities"]
    fin.promote(db, _imp(db, rec)["report_id"])
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30")
    cr = a["ratios"]["current_ratio"]
    assert cr["state"] == "insufficient_data" and cr["value"] is None
    assert cr["missing"] == ["current_liabilities"]
    assert a["growth"]["revenue"]["state"] == "insufficient_data"  # no prior year imported


def test_assess_writes_dimensions_without_bands(db):
    _two_years(db)
    out = fu.assess(db, "cmp-ogdc", period_end="2025-06-30", as_of_date="2025-09-30")
    assert set(out["dimensions"]) == {"A", "B", "C"}
    rows = db.execute("SELECT dimension, band, data_state FROM dimension_assessments")
    assert len(rows) == 3 and all(r["band"] is None for r in rows)
    fu.assess(db, "cmp-ogdc", period_end="2025-06-30", as_of_date="2025-09-30")
    assert len(db.execute("SELECT 1 FROM dimension_assessments")) == 3


def test_no_metrics_gives_insufficient_data(db):
    assert fu.analyse(db, "cmp-hbl", period_end="2025-12-31")["state"] == "insufficient_data"
