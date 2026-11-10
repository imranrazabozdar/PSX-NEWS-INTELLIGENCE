"""Financial PDF intake, balance-sheet gate and multi-period series.

Every statement here is a SYNTHETIC hand-built fixture (PDFs from tests/pdf_fixture_builder.py and the
hand-calculated values in tests/test_m2_m3_financials.py). They test the logic only. They are not evidence of
extraction accuracy on a real company report, which needs an owner-supplied document (OWNER_ACTIONS item 19).
"""

from __future__ import annotations

import hashlib

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import document_intake as di
from engines import financial_series as fs
from engines import financials as fin
from tests import test_m2_m3_financials as m2
from tests.pdf_fixture_builder import write_pdf

SYNTH = "synthetic fixture (not a real document)"
COLS = ["2025-06-30", "2024-06-30"]


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


@pytest.fixture
def vault(tmp_path):
    return di.vault_dir(tmp_path / "vault")


def _import(db, rec, seed):
    # a valid SHA-256 shape derived from a seed, so each synthetic document has its own hash
    rec = dict(rec, document_sha256=hashlib.sha256(seed.encode()).hexdigest())
    return m2._imp(db, rec)


def _promoted_metrics(db, report_id):
    return db.execute("SELECT COUNT(*) AS n FROM financial_metrics WHERE report_id = ?", (report_id,))[0]["n"]


# ------------------------------------------------------------------ balance-sheet gate (regression)

def test_missing_total_liabilities_blocks_reconciliation_and_promotion(db):
    """Regression: the P&L identities passed while the balance sheet could not be checked, so the report was
    marked reconciled and 17 metrics were promoted unverified. It must now be refused."""
    rec = m2._corp(overrides={("Total liabilities", "2025-06-30"): None,
                              ("Total liabilities", "2024-06-30"): None})
    r = _import(db, rec, "b")
    assert r["status"] == "needs_review"
    checks = {c["check"]: c["result"] for c in r["checks"]}
    assert checks["balance_sheet"] == "not_checkable"
    assert checks["balance_sheet_required"] == "fail"
    p = fin.promote(db, r["report_id"])
    assert p["promoted"] == 0 and "refused" in p
    assert _promoted_metrics(db, r["report_id"]) == 0


def test_balance_sheet_that_does_not_balance_is_refused(db):
    rec = m2._corp(overrides={("Total equity", "2025-06-30"): 150.0})  # 300 + 150 != 500
    r = _import(db, rec, "c")
    assert r["status"] == "needs_review"
    assert {c["check"]: c["result"] for c in r["checks"]}["balance_sheet"] == "fail"
    assert fin.promote(db, r["report_id"])["promoted"] == 0


def test_balanced_report_still_reconciles_and_promotes(db):
    r = _import(db, m2._corp(), "d")
    assert r["status"] == "reconciled"
    assert fin.promote(db, r["report_id"])["promoted"] > 0


def test_report_without_any_balance_sheet_is_not_forced_to_have_one(db):
    """An income-statement-only update has no balance-sheet totals, so the gate does not apply."""
    overrides = {}
    for col in ("2025-06-30", "2024-06-30"):
        for lab in ("Total assets", "Total liabilities", "Total equity", "Total current assets",
                    "Total current liabilities", "Long term financing", "Short term borrowings",
                    "Mystery reserve"):
            overrides[(lab, col)] = None
    r = _import(db, m2._corp(overrides=overrides), "e")
    checks = {c["check"]: c["result"] for c in r["checks"]}
    assert "balance_sheet_required" not in checks  # nothing was reported, so nothing is forced to balance
    assert checks.get("balance_sheet", "not_checkable") == "not_checkable"


# ------------------------------------------------------------------ PDF intake to promotion (synthetic PDFs)

def test_pdf_with_unbalanced_balance_sheet_is_not_promoted(db, tmp_path, vault):
    pdf = write_pdf(tmp_path / "bs_bad.pdf", [[
        "Statement of financial position",
        "Total assets 1,000 900",
        "Total liabilities 600 500",
        "Total equity 300 400",
    ]])
    r = di.intake(db, pdf, _meta(statement_pages={"BS": [1]}), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    assert r["status"] == "needs_review"
    assert fin.promote(db, r["import"]["report_id"])["promoted"] == 0


def test_pdf_with_balanced_balance_sheet_reconciles_and_promotes(db, tmp_path, vault):
    pdf = write_pdf(tmp_path / "bs_ok.pdf", [[
        "Statement of financial position",
        "Total assets 1,000 900",
        "Total liabilities 600 500",
        "Total equity 400 400",
    ]])
    r = di.intake(db, pdf, _meta(statement_pages={"BS": [1]}), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    assert r["import"]["status"] == "reconciled"
    assert fin.promote(db, r["import"]["report_id"])["promoted"] == 3
    # the promoted total is scaled by the stated unit (thousands) and keeps its page reference
    row = db.execute("SELECT value, unit FROM financial_metrics fm JOIN financial_reports fr "
                     "ON fr.report_id = fm.report_id WHERE fm.metric = 'total_assets' "
                     "AND fr.period_end = '2025-06-30'")[0]
    assert row["value"] == pytest.approx(1_000_000.0) and row["unit"] == "PKR"


def test_pdf_hash_is_the_original_bytes_and_duplicate_is_refused(db, tmp_path, vault):
    pdf = write_pdf(tmp_path / "bs_ok.pdf", [[
        "Statement of financial position", "Total assets 1,000 900",
        "Total liabilities 600 500", "Total equity 400 400"]])
    first = di.intake(db, pdf, _meta(statement_pages={"BS": [1]}), vault=vault, importer="owner",
                      rights_attestation=SYNTH)
    again = di.intake(db, pdf, _meta(statement_pages={"BS": [1]}), vault=vault, importer="owner",
                      rights_attestation=SYNTH)
    assert again["status"] == "duplicate" and again["report_id"] == first["import"]["report_id"]


def _meta(**kw):
    m = {"company_ticker": "OGDC", "doc_type": "annual", "period_end": "2025-06-30",
         "scope": "unconsolidated", "currency": "PKR", "unit_scale": 1000, "audit_status": "audited",
         "columns": COLS,
         "retrieved_at_utc": "2026-11-10T10:00:00Z", "filed_at_utc": "2025-09-30T00:00:00Z",
         "original_url": "https://example.invalid/synthetic-report.pdf"}
    m.update(kw)
    return m


# ------------------------------------------------------------------ multi-period series

def test_series_is_built_only_from_promoted_reports_and_gives_margins(db):
    r24 = _import(db, m2._corp(period="2024-06-30", prev="2023-06-30"), "f")
    r25 = _import(db, m2._corp(), "g")
    fin.promote(db, r24["report_id"])
    fin.promote(db, r25["report_id"])
    s = fs.annual_series(db, _company(db), scope="unconsolidated")
    assert [p["period_end"] for p in s["periods"]] == ["2024-06-30", "2025-06-30"]
    assert s["gaps"] == [] and s["not_promoted"] == [] and s["conflicts"] == []
    p25 = s["periods"][1]["metrics"]
    assert p25["gross_profit"] / p25["revenue"] == pytest.approx(0.4)  # 400 / 1000, same unit throughout


def test_missing_year_is_reported_as_a_gap_and_not_filled(db, monkeypatch):
    monkeypatch.setitem(m2.YEARS, "2026-06-30", m2.YEARS["2025-06-30"])
    r24 = _import(db, m2._corp(period="2024-06-30", prev="2023-06-30"), "h")
    r26 = _import(db, m2._corp(period="2026-06-30", prev="2025-06-30"), "i")
    fin.promote(db, r24["report_id"])
    fin.promote(db, r26["report_id"])
    s = fs.annual_series(db, _company(db), scope="unconsolidated")
    assert [p["period_end"] for p in s["periods"]] == ["2024-06-30", "2026-06-30"]
    assert s["gaps"] == [{"after": "2024-06-30", "before": "2026-06-30", "missing_years": 1}]


def test_unreconciled_report_is_listed_and_excluded_from_the_series(db):
    ok = _import(db, m2._corp(period="2024-06-30", prev="2023-06-30"), "j")
    bad = _import(db, m2._corp(overrides={("Total equity", "2025-06-30"): 1.0}), "k")
    fin.promote(db, ok["report_id"])
    assert fin.promote(db, bad["report_id"])["promoted"] == 0
    s = fs.annual_series(db, _company(db), scope="unconsolidated")
    assert [p["period_end"] for p in s["periods"]] == ["2024-06-30"]
    assert [(x["period_end"], x["status"]) for x in s["not_promoted"]] == [("2025-06-30", "needs_review")]


def test_two_promoted_reports_for_one_period_are_a_conflict_not_a_choice(db):
    first = _import(db, m2._corp(), "l")
    second = _import(db, m2._corp(restates_report_id=first["report_id"], overrides={
        ("Net sales", "2025-06-30"): 1100.0, ("Gross profit", "2025-06-30"): 450.0,
        ("Cost of sales", "2025-06-30"): -650.0}), "m")
    assert second["status"] == "reconciled"
    fin.promote(db, first["report_id"])
    fin.promote(db, second["report_id"])
    s = fs.annual_series(db, _company(db), scope="unconsolidated")
    assert s["periods"] == []
    assert s["conflicts"][0]["period_end"] == "2025-06-30"
    assert sorted(s["conflicts"][0]["report_ids"]) == sorted([first["report_id"], second["report_id"]])


def _company(db) -> str:
    return db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' "
                      "AND value = 'OGDC' AND valid_to IS NULL")[0]["company_id"]
