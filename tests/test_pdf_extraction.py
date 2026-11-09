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


def test_extraction_never_guesses_when_the_file_cannot_be_read():
    """The approved reader is installed (owner decision U3). The property that remains: an unreadable
    input is refused, never returned as an empty document."""
    assert pe.reader_available() is True
    with pytest.raises(ValueError):  # the reader refuses a missing file rather than guessing
        pe.extract("report.pdf")


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


def test_omitting_or_misdeclaring_source_cannot_bypass_document_rules():
    """Review finding: the page/source/scope gate used to apply only when source was 'pdf'. An import with no
    source, or an unknown one, must now be refused outright, never treated as a synthetic test."""
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    rec = _corp(filed_at_utc="2026-09-30T00:00:00Z")
    rec.pop("source", None)
    with pytest.raises(fin.ImportError_, match="source must be one of"):
        fin.import_report(db, rec, importer="o", rights_attestation="own download")
    rec["source"] = "pdf_real"  # a typo or unknown value is refused, not defaulted
    with pytest.raises(fin.ImportError_, match="source must be one of"):
        fin.import_report(db, rec, importer="o", rights_attestation="own download")


def test_real_source_without_a_scope_is_refused_even_if_pages_are_present():
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    rec = _corp(filed_at_utc="2026-09-30T00:00:00Z", source="text_entry")
    for ln in rec["lines"]:
        ln["page"] = 3
    rec["scope"] = None
    with pytest.raises(fin.ImportError_, match="scope"):
        fin.import_report(db, rec, importer="o", rights_attestation="own download")


def test_synthetic_fixture_is_labelled_and_real_imports_keep_their_page():
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    rec = _corp(filed_at_utc="2026-09-30T00:00:00Z", source="synthetic_test")
    fin.import_report(db, rec, importer="o", rights_attestation="own download")
    row = db.execute("SELECT extraction_method FROM financial_reports")[0]
    assert row["extraction_method"] == "manual"  # fixture extraction method, unaffected by the source gate
    assert db.execute("SELECT COUNT(*) n FROM financial_line_items WHERE page IS NULL")[0]["n"] > 0


@pytest.mark.parametrize("tok,value", [
    ("1,234", 1234.0), ("(1,234)", -1234.0), ("1,234,567", 1234567.0),
    ("1,23,456", 123456.0), ("(1,23,456)", -123456.0), ("(12.5)", -12.5), ("-5", -5.0), ("0", 0.0),
])
def test_valid_number_formats_read_exactly(tok, value):
    assert fin.parse_number(tok) == value


@pytest.mark.parametrize("tok", ["(12", "12)", "12,34", "1,2,3", "12a", "1e5", "--", "(-5)", "(1,2,3)"])
def test_malformed_or_ambiguous_numbers_are_refused_not_guessed(tok):
    """Review finding: an unpaired bracket was read as a positive figure, and irregular grouping (12,34)
    was read as 1234. Both now raise rather than produce a value that could be off by 100x or more."""
    with pytest.raises(ValueError):
        fin.parse_number(tok)
