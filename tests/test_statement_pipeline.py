"""Statement pipeline end to end: vault -> registration -> extraction -> evidence -> reconciliation ->
metrics.

Every PDF here is a SYNTHETIC fixture with invented figures, written by tests/pdf_fixture_builder.py. The
figures
are chosen so the identities hold or fail on purpose. They prove the logic only. They are not validation of
any
real company's accounts (that needs an owner-supplied annual report).
"""

from __future__ import annotations

import hashlib

import pytest

from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase
from engines import document_intake as di
from engines import statement_pipeline as sp
from engines import statement_reconciliation as rec
from tests.pdf_fixture_builder import write_pdf

SYNTH = "synthetic fixture (not a real document)"
COLS = ["2025-06-30", "2024-06-30"]
EVIDENCE_FIELDS = (
    "document_id",
    "file_hash",
    "symbol",
    "period_end",
    "statement_type",
    "line_item_name",
    "restated_flag",
    "currency",
    "unit_scale",
    "pdf_page_number",
    "extractor_version",
    "consolidation",
    "column_period_end",
)


def _report_pages(
    equity=400,
    revenue=("1,000", "800"),
    prev_bs_total=("900",),
    cf_closing=("70", "100"),
    opinion="In our opinion the financial statements present fairly the financial position",
):
    bs = [
        "Statement of financial position",
        "Total assets 1,000 900",
        "Total liabilities 600 500",
        f"Total equity {equity} 400",
        "Trade debts 120 90",
        "Stock in trade 80 70",
        "Trade and other payables 60 50",
        "Cash and bank balances 20 15",
        "Long term financing 50 40",
        "Short term borrowings 30 20",
    ]
    is_ = [
        "Statement of profit or loss",
        f"Net sales {revenue[0]} {revenue[1]}",
        "Cost of sales (600) (500)",
        "Gross profit 400 300",
        "Operating profit 250 200",
        "Finance cost (50) (40)",
        "Profit before taxation 200 160",
        "Taxation (60) (48)",
        "Profit for the year 140 112",
    ]
    cf = [
        "Statement of cash flows",
        "Net cash generated from operating activities 150 120",
        "Purchase of property plant and equipment (40) (30)",
        "Cash and cash equivalents at beginning of the year 100 90",
        "Net decrease in cash and cash equivalents (30) 10",
        f"Cash and cash equivalents at end of the year {cf_closing[0]} {cf_closing[1]}",
    ]
    aud = ["Independent auditor's report", opinion, "Key audit matters", "Revenue recognition"]
    return [bs, is_, cf, aud]


@pytest.fixture
def archive():
    d = SQLiteDatabase()
    d.role = "archive"
    gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    yield d
    d.close()


@pytest.fixture
def mapping():
    return sp.load_mappings()


def _doc(path, sha, period="2025-06-30", restated=False):
    return {
        "document_id": sha,
        "file_hash": sha,
        "symbol": "OGDC",
        "period_end": period,
        "currency": "PKR",
        "unit_scale": 1000,
        "consolidation": "unconsolidated",
        "restated_flag": restated,
    }


def _pdf(tmp_path, name, pages):
    return write_pdf(tmp_path / name, pages)


# ------------------------------------------------------------------ vault


def test_vault_stores_once_and_rejects_the_duplicate(tmp_path):
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    vault = di.vault_dir(tmp_path / "vault")
    first = di.store_manual_upload(pdf, vault)
    again = di.store_manual_upload(pdf, vault)
    assert first["status"] == "stored" and again["status"] == "duplicate"
    assert len(list(vault.glob("*.pdf"))) == 1
    assert oct((vault / first["vault_ref"]).stat().st_mode & 0o777) == "0o600"


def test_vault_reads_reverify_the_hash_and_never_serve_a_tampered_file(tmp_path):
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    vault = di.vault_dir(tmp_path / "vault")
    sha = di.store_manual_upload(pdf, vault)["report_sha256"]
    assert di.read_verified(vault, sha) == pdf.read_bytes()
    (vault / f"{sha}.pdf").write_bytes(b"tampered")
    with pytest.raises(di.VaultIntegrityError, match="no longer matches"):
        di.read_verified(vault, sha)


def test_safe_filename_strips_paths_and_unsafe_characters():
    assert di.safe_filename("../../etc/OGDC 2025?.pdf") == "OGDC_2025_.pdf"
    with pytest.raises(di.IntakeError):
        di.safe_filename("///")


# ------------------------------------------------------------------ extraction, evidence, reconciliation


def test_extraction_locates_statements_auditor_opinion_and_kams(tmp_path, mapping):
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    ex = sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]})
    assert {ln["statement"] for ln in ex["lines"]} == {"BS", "IS", "CF"}
    assert ex["auditor"]["opinion"] == "unmodified" and ex["auditor"]["kam_pages"] == [4]
    assert "key_audit_matters" in ex["notes"]


def test_every_line_carries_full_evidence_and_unmapped_lines_stay_unmapped(tmp_path, mapping):
    sha = hashlib.sha256(b"evidence").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages() + [])
    ex = sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]})
    t = sp.tag(ex, document=_doc(pdf, sha), extractor_version="pdfplumber-0.11.10/rules-1", mapping=mapping)
    assert t["lines"]
    for ln in t["lines"]:
        for f in EVIDENCE_FIELDS:
            assert ln[f] is not None, f"{f} missing on {ln['line_item_name']}"
        assert ln["pdf_page_number"] in (1, 2, 3)
        if ln["canonical_code"] is None:
            assert ln["confidence"] is None  # never a guessed code or confidence
        else:
            assert ln["confidence"] == 1.0
    pl = {ln["line_item_name"]: ln for ln in t["lines"] if not ln["is_comparative"]}
    assert pl["Net sales"]["canonical_code"] == "revenue" and pl["Net sales"]["reported_amount"] == 1000.0
    assert pl["Net sales"]["is_comparative"] is False
    assert [x for x in t["lines"] if x["is_comparative"]][0]["column_period_end"] == "2024-06-30"


def test_a_balanced_document_reconciles_exactly(tmp_path, mapping):
    sha = hashlib.sha256(b"balanced").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    r = sp.reconcile(t, period_end="2025-06-30")
    status = {c["check"]: c["status"] for c in r["checks"]}
    assert status["balance_sheet"] == rec.RECONCILED and status["cash_flow"] == rec.RECONCILED
    assert r["overall"] == rec.RECONCILED


def test_a_one_unit_difference_is_rounding_and_the_exact_amount_is_kept(tmp_path, mapping):
    sha = hashlib.sha256(b"rounding").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages(equity=399))  # 600 + 399 = 999, assets 1,000
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    bs = next(c for c in sp.reconcile(t, period_end="2025-06-30")["checks"] if c["check"] == "balance_sheet")
    assert (
        bs["status"] == rec.ROUNDED and bs["discrepancy"] == 1.0
    )  # the exact difference is stored, not hidden
    assert (
        next(ln for ln in t["lines"] if ln["canonical_code"] == "total_equity" and not ln["is_comparative"])[
            "reported_amount"
        ]
        == 399.0
    )  # the printed number is unchanged


def test_an_unbalanced_document_is_unreconciled_and_its_numbers_are_not_altered(tmp_path, mapping):
    sha = hashlib.sha256(b"unbalanced").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages(equity=350))  # 600 + 350 = 950, assets 1,000
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    r = sp.reconcile(t, period_end="2025-06-30")
    assert r["overall"] == rec.UNRECONCILED
    bs = next(c for c in r["checks"] if c["check"] == "balance_sheet")
    assert bs["discrepancy"] == 50.0 and bs["status"] == rec.UNRECONCILED
    assert (
        next(ln for ln in t["lines"] if ln["canonical_code"] == "total_equity" and not ln["is_comparative"])[
            "reported_amount"
        ]
        == 350.0
    )


def test_a_cash_flow_break_is_reported(tmp_path, mapping):
    sha = hashlib.sha256(b"cashbreak").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages(cf_closing=("80", "100")))  # 100 - 30 != 80
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    cf = next(c for c in sp.reconcile(t, period_end="2025-06-30")["checks"] if c["check"] == "cash_flow")
    assert cf["status"] == rec.UNRECONCILED and cf["discrepancy"] == 10.0


def test_comparative_period_mismatch_across_reports_is_flagged(tmp_path, mapping):
    """The FY2024 report's own revenue (800) differs from the FY2025 report's comparative column (750)."""
    prior_pdf = _pdf(tmp_path, "fy24.pdf", _report_pages(revenue=("800", "700")))
    current_pdf = _pdf(tmp_path, "fy25.pdf", _report_pages(revenue=("1,000", "750")))
    prior = sp.tag(
        sp.extract(
            prior_pdf, columns=["2024-06-30", "2023-06-30"], statement_pages={"BS": [1], "IS": [2], "CF": [3]}
        ),
        document=_doc(prior_pdf, "a" * 64, period="2024-06-30"),
        extractor_version="v1",
        mapping=mapping,
    )
    prior["period"] = "2024-06-30"
    cur = sp.tag(
        sp.extract(current_pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(current_pdf, "b" * 64),
        extractor_version="v1",
        mapping=mapping,
    )
    r = sp.reconcile(cur, period_end="2025-06-30", prior=prior)
    rev = next(c for c in r["checks"] if c["check"] == "comparative:revenue")
    assert rev["status"] == rec.UNRECONCILED and rev["discrepancy"] == -50.0
    assert r["overall"] == rec.UNRECONCILED


def test_metrics_come_from_verified_values_and_missing_inputs_are_not_zero(tmp_path, mapping):
    sha = hashlib.sha256(b"metrics").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    m = {x["metric"]: x for x in sp.compute_metrics(t, period_end="2025-06-30")}
    assert m["gross_margin"]["value"] == pytest.approx(0.4)
    assert m["operating_margin"]["value"] == pytest.approx(0.25)
    assert m["debt_to_equity"]["value"] == pytest.approx(80 / 400)
    assert m["free_cash_flow"]["value"] == pytest.approx(150 - 40)
    assert "revenue_growth" not in m  # growth needs a prior report; it is not reported as zero


# ------------------------------------------------------------------ storage: versioned, idempotent


def _meta(sha, **over):
    m = {
        "report_sha256": sha,
        "psx_symbol": "OGDC",
        "company_id": "co-ogdc-fixture",
        "doc_type": "annual",
        "financial_year": 2025,
        "period_end": "2025-06-30",
        "consolidation": "unconsolidated",
        "audit_status": "audited",
        "original_filename": "ogdc-2025-synthetic.pdf",
        "vault_ref": f"{sha}.pdf",
        "source_id": "company_reports_manual",
        "retrieved_at_utc": "2026-11-10T10:00:00Z",
    }
    m.update(over)
    return m


def test_store_is_idempotent_and_a_new_extractor_version_adds_a_separate_run(tmp_path, mapping, archive):
    sha = hashlib.sha256(b"store").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages())
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="pdfplumber-0.11.10/rules-1",
        mapping=mapping,
    )
    r = sp.reconcile(t, period_end="2025-06-30")
    first = sp.store(
        archive,
        registry_meta=_meta(sha),
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=r,
        extractor_version="pdfplumber-0.11.10/rules-1",
    )
    n_lines = archive.execute("SELECT COUNT(*) AS n FROM archive_line_items_v2")[0]["n"]
    again = sp.store(
        archive,
        registry_meta=_meta(sha),
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=r,
        extractor_version="pdfplumber-0.11.10/rules-1",
    )
    assert first["registration"] == "registered" and again["registration"] == "duplicate"
    assert again["run"] == "existing" and again["lines"]["inserted"] == 0
    assert archive.execute("SELECT COUNT(*) AS n FROM archive_line_items_v2")[0]["n"] == n_lines
    other = sp.store(
        archive,
        registry_meta=_meta(sha),
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=r,
        extractor_version="pdfplumber-0.12.0/rules-2",
    )
    assert other["run"] == "created" and other["run_id"] != first["run_id"]
    assert (
        archive.execute(
            "SELECT COUNT(*) AS n FROM archive_line_items_v2 WHERE run_id = ?", (first["run_id"],)
        )[0]["n"]
        == n_lines
    )  # the first version's rows are untouched
    assert (
        archive.execute(
            "SELECT COUNT(*) AS n FROM archive_line_items_v2 WHERE run_id = ?", (other["run_id"],)
        )[0]["n"]
        == n_lines
    )


def test_stored_reconciliation_has_one_of_the_four_statuses_and_no_null_status(tmp_path, mapping, archive):
    sha = hashlib.sha256(b"status").hexdigest()
    pdf = _pdf(tmp_path, "src.pdf", _report_pages(equity=350))
    t = sp.tag(
        sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=_doc(pdf, sha),
        extractor_version="v1",
        mapping=mapping,
    )
    out = sp.store(
        archive,
        registry_meta=_meta(sha),
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=sp.reconcile(t, period_end="2025-06-30"),
        extractor_version="v1",
    )
    assert out["status"] == "needs_review"
    statuses = {r["status"] for r in archive.execute("SELECT status FROM archive_reconciliation_v2")}
    assert statuses <= {"RECONCILED", "RECONCILED_WITH_ROUNDING", "UNRECONCILED", "INSUFFICIENT_DATA"}
    assert "UNRECONCILED" in statuses
