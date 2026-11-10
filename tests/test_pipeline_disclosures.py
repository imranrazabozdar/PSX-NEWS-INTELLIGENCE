"""Statement pipeline with notes and auditor findings, end to end on a SYNTHETIC report. Invented figures."""

from __future__ import annotations

import hashlib

import pytest

from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase
from engines import statement_pipeline as sp
from engines import statement_reconciliation as rec
from tests.pdf_fixture_builder import write_pdf
from tests.test_statement_pipeline import COLS, _report_pages

NOTE_PAGES = [
    ["12. Trade debts", "Trade debts 120 90", "Expected credit loss allowance (12) (10)"],
    ["Note 15 Borrowings", "Long term financing 50 40", "Short term borrowings 30 20"],
    [
        "Key audit matters",
        "Revenue recognition",
        "We identified revenue recognition as a key audit matter because of the volume of transactions.",
    ],
]
AUDIT = [
    "Independent auditor's report",
    "In our opinion the financial statements present fairly, in all material respects, "
    "the financial position",
]


@pytest.fixture
def archive():
    d = SQLiteDatabase()
    d.role = "archive"
    gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    yield d
    d.close()


def _tagged(tmp_path):
    pages = _report_pages() + [AUDIT] + NOTE_PAGES
    pdf = write_pdf(tmp_path / "report.pdf", pages)
    doc = {
        "document_id": hashlib.sha256(b"d").hexdigest(),
        "file_hash": hashlib.sha256(b"d").hexdigest(),
        "symbol": "OGDC",
        "period_end": "2025-06-30",
        "currency": "PKR",
        "unit_scale": 1000,
        "consolidation": "unconsolidated",
        "restated_flag": False,
    }
    ex = sp.extract(pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]})
    return (
        pdf,
        doc,
        sp.tag(ex, document=doc, extractor_version="pdfplumber-0.11.10/notes-1", mapping=sp.load_mappings()),
        ex,
    )


def test_notes_are_tagged_with_full_evidence_and_statements_are_unchanged(tmp_path):
    _, doc, t, ex = _tagged(tmp_path)
    note_lines = [ln for ln in t["lines"] if ln["statement_type"] == "NOTE"]
    assert note_lines and all(ln["document_id"] == doc["document_id"] for ln in note_lines)
    for ln in note_lines:
        for f in (
            "file_hash",
            "symbol",
            "period_end",
            "line_item_name",
            "reported_amount",
            "currency",
            "unit_scale",
            "pdf_page_number",
            "note_ref",
            "extractor_version",
            "consolidation",
        ):
            assert ln[f] is not None, f
    ecl = next(
        ln
        for ln in note_lines
        if ln["line_item_name"] == "Expected credit loss allowance" and not ln["is_comparative"]
    )
    assert (
        ecl["canonical_code"] == "ecl_allowance"
        and ecl["reported_amount"] == -12.0
        and ecl["note_ref"] == "12"
    )
    r = sp.reconcile(t, period_end="2025-06-30")
    assert r["overall"] == rec.RECONCILED  # notes do not enter the statement identities


def test_unmapped_note_lines_are_kept_not_dropped(tmp_path):
    pdf = write_pdf(
        tmp_path / "u.pdf", [["7. Contingencies and commitments", "Guarantees issued by banks 50 40"]]
    )
    ex = sp.extract(pdf, columns=COLS, statement_pages={})
    t = sp.tag(
        ex,
        document={
            "document_id": "a" * 64,
            "file_hash": "a" * 64,
            "symbol": "OGDC",
            "period_end": "2025-06-30",
            "currency": "PKR",
            "unit_scale": 1000,
            "consolidation": "unconsolidated",
            "restated_flag": False,
        },
        extractor_version="v1",
        mapping=sp.load_mappings(),
    )
    g = [ln for ln in t["lines"] if ln["line_item_name"] == "Guarantees issued by banks"]
    assert len(g) == 2 and all(ln["canonical_code"] is None and ln["confidence"] is None for ln in g)


def test_store_writes_note_lines_and_the_audit_trail_once(tmp_path, archive):
    pdf, doc, t, ex = _tagged(tmp_path)
    r = sp.reconcile(t, period_end="2025-06-30")
    meta = {
        "report_sha256": doc["file_hash"],
        "psx_symbol": "OGDC",
        "company_id": "co-disc",
        "doc_type": "annual",
        "financial_year": 2025,
        "period_end": "2025-06-30",
        "consolidation": "unconsolidated",
        "audit_status": "audited",
        "original_filename": "report.pdf",
        "vault_ref": f"{doc['file_hash']}.pdf",
        "source_id": "company_reports_manual",
        "retrieved_at_utc": "2026-11-10T00:00:00Z",
    }
    first = sp.store(
        archive,
        registry_meta=meta,
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=r,
        extractor_version="pdfplumber-0.11.10/notes-1",
        audit=ex["audit"],
    )
    assert first["audit_disclosure"]["archived"] == 1
    notes_stored = archive.execute(
        "SELECT COUNT(*) AS n FROM archive_line_items_v2 WHERE statement_type = 'NOTE' AND run_id = ?",
        (first["run_id"],),
    )[0]["n"]
    assert notes_stored == len([ln for ln in t["lines"] if ln["statement_type"] == "NOTE"]) > 0
    again = sp.store(
        archive,
        registry_meta=meta,
        file_size_bytes=pdf.stat().st_size,
        tagged=t,
        reconciliation=r,
        extractor_version="pdfplumber-0.11.10/notes-1",
        audit=ex["audit"],
    )
    assert again["lines"]["inserted"] == 0 and again["audit_disclosure"]["archived"] == 0
    assert archive.execute("SELECT COUNT(*) AS n FROM archive_disclosures")[0]["n"] == 1


def test_the_audit_trail_keeps_opinion_excerpts_pages_and_kam_headings(tmp_path):
    _, _, _, ex = _tagged(tmp_path)
    payload = sp.audit_payload(ex["audit"])
    assert payload["opinion"] == "unqualified"
    assert payload["opinion_evidence"][0]["page"] == 5
    assert payload["opinion_evidence"][0]["excerpt"]
    kams = payload["key_audit_matters"]
    assert [k["heading"] for k in kams] == ["Revenue recognition"]  # no statement or note line is a KAM
    assert kams[0]["page"] == 8 and kams[0]["excerpt"].startswith("We identified revenue recognition")
