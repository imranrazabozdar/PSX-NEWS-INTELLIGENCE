"""M2 PDF extraction interface, with NO PDF library: contract, page references, scanned pages, headers.

SYNTHETIC page text only. These tests check the logic. They are not evidence of extraction accuracy on real
PSX reports, which needs an approved reader (U3) and real documents.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from engines import pdf_extraction as pe
from tests.test_m2_m3_financials import _corp


def _doc(*pages):
    return pe.DocumentText([pe.Page(i + 1, list(lines), has_text)
                            for i, (lines, has_text) in enumerate(pages)])


def test_no_reader_is_approved_and_extraction_never_guesses():
    assert pe.reader_available() is False
    with pytest.raises(pe.ExtractionUnavailable):
        pe.extract("report.pdf")  # no silent fallback to guessing


def test_hash_is_of_the_original_bytes(tmp_path):
    f = tmp_path / "annual.pdf"
    f.write_bytes(b"%PDF-1.4 synthetic bytes")
    assert pe.sha256_file(f) == __import__("hashlib").sha256(b"%PDF-1.4 synthetic bytes").hexdigest()
    meta = pe.document_metadata(f, _doc((["x"], True), (["y"], False)))
    assert meta.page_count == 2 and meta.scanned_pages == [2]  # the scanned page is flagged, not read


def test_scanned_pages_are_flagged_not_parsed():
    doc = _doc((["Statement of financial position", "Total assets 1,000"], True), (["image only"], False))
    r = pe.to_statement_lines(doc, "BS", [1, 2], columns=["2025-06-30"])
    assert any(u["page"] == 2 and "OCR required" in u["reason"] for u in r["unparsed"])
    assert all(ln["page"] == 1 for ln in r["lines"])  # no value invented for the scanned page


def test_every_line_keeps_its_page_and_brackets_and_dashes_are_handled():
    doc = _doc((["Statement of profit or loss", "Revenue 1,000 800", "Cost of sales (600) -"], True),
               (["Gross profit 400 800"], True))
    r = pe.to_statement_lines(doc, "IS", [1, 2], columns=["2025-06-30", "2024-06-30"])
    by = {(ln["raw_label"], ln["column_period_end"], ln["page"]): ln["value"] for ln in r["lines"]}
    assert by[("Cost of sales", "2025-06-30", 1)] == -600.0
    assert by[("Cost of sales", "2024-06-30", 1)] is None  # dash: not reported, never zero
    assert by[("Gross profit", "2025-06-30", 2)] == 400.0


def test_repeated_banners_and_page_numbers_are_removed_figures_are_kept():
    banner = "XYZ Oil Limited Annual Report 2025"
    doc = _doc(*[([banner, "Revenue 1,000 800", "Page 3 of 9"], True) for _ in range(4)])
    clean = pe.strip_running_headers(doc)
    for pg in clean.pages:
        assert banner not in pg.lines and not any("Page 3" in ln for ln in pg.lines)
        assert "Revenue 1,000 800" in pg.lines  # a figure line is never removed


def test_statement_locator_finds_continuation_pages_and_skips_missing():
    doc = _doc((["Statement of financial position"], True), (["Balance sheet (continued)"], True),
               (["Notes to the accounts"], True))
    loc = pe.locate_statements(doc)
    assert loc["BS"] == [1, 2] and "IS" not in loc and "CF" not in loc


def test_pdf_sourced_import_requires_page_and_source():
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    rec = _corp(filed_at_utc="2026-09-30T00:00:00Z")
    rec["source"] = "pdf"
    rec["original_url"] = None
    rec["source_note"] = None
    with pytest.raises(fin.ImportError_, match="source"):
        fin.import_report(db, rec, importer="o", rights_attestation="own download")
    rec["source_note"] = "investor relations, downloaded by owner"
    with pytest.raises(fin.ImportError_, match="page reference"):
        fin.import_report(db, rec, importer="o", rights_attestation="own download")
    for ln in rec["lines"]:
        ln["page"] = 12
    rec["scope"] = "consolidated"
    assert fin.import_report(db, rec, importer="o", rights_attestation="own download")["status"] in (
        "reconciled", "needs_review", "extracted")


def test_legacy_synthetic_imports_still_need_no_page():
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    assert fin.import_report(db, _corp(), importer="o", rights_attestation="fixture")["report_id"]
