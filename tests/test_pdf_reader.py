"""pdfplumber reader (approved, pinned): tests on SYNTHETIC generated PDFs only.

These show that the reader keeps pages, marks scanned pages without inventing text, keeps figures through
header removal, and refuses malformed input. They are NOT evidence of extraction accuracy on real PSX
reports, which has not been performed.
"""

from __future__ import annotations

import pytest

from engines import pdf_extraction as pe
from engines import pdf_reader
from tests.pdf_fixture_builder import write_pdf


@pytest.fixture
def pdf(tmp_path):
    def make(pages):
        return write_pdf(tmp_path / "synthetic.pdf", pages)
    return make


def test_reader_is_available_and_wired_into_the_interface():
    assert pdf_reader.available() is True
    assert pe.reader_available() is True


def test_pages_keep_their_numbers_and_scanned_pages_have_no_invented_text(pdf):
    doc = pdf_reader.read(pdf([["SYNTHETIC statement of profit or loss", "Revenue 1,000 800"], None]))
    assert [p.number for p in doc.pages] == [1, 2]
    assert doc.pages[0].has_text and doc.pages[0].lines
    assert doc.pages[1].has_text is False and doc.pages[1].lines == []  # no OCR, no invented figures


def test_figures_keep_their_page_brackets_and_dashes_are_handled(pdf):
    doc = pdf_reader.read(pdf([["SYNTHETIC statement of profit or loss", "Net sales 1,000 800",
                                "Cost of sales (600) (500)", "Other income - 120"],
                               ["Profit for the year 140 110"]]))
    r = pe.to_statement_lines(doc, "IS", [1, 2], columns=["2025-06-30", "2024-06-30"])
    by = {(ln["raw_label"], ln["column_period_end"]): (ln["page"], ln["value"]) for ln in r["lines"]}
    assert by[("Net sales", "2025-06-30")] == (1, 1000.0)
    assert by[("Cost of sales", "2024-06-30")] == (1, -500.0)  # bracketed: negative
    assert by[("Other income", "2025-06-30")] == (1, None)  # dash: not reported, never zero
    assert by[("Profit for the year", "2024-06-30")] == (2, 110.0)  # continuation page keeps its page


def test_running_banner_and_page_numbers_removed_but_figures_kept(pdf):
    banner = "XYZ Oil Limited Annual Report 2025"
    doc = pe.strip_running_headers(pdf_reader.read(pdf(
        [[banner, "Net sales 1,000 800", "Page 1 of 3"], [banner, "Cost of sales (600) (500)", "Page 2 of 3"],
         [banner, "Profit for the year 140 110", "Page 3 of 3"]])))
    text = [ln for pg in doc.pages for ln in pg.lines]
    assert banner not in text and not any(t.startswith("Page ") for t in text)
    assert {"Net sales 1,000 800", "Cost of sales (600) (500)", "Profit for the year 140 110"} <= set(text)


def test_statement_on_continuation_page_is_located(pdf):
    doc = pdf_reader.read(pdf([["Statement of financial position"], ["Balance sheet (continued)"],
                               ["Notes to the accounts"]]))
    assert pe.locate_statements(doc) == {"BS": [1, 2]}


def test_non_pdf_empty_and_missing_inputs_are_refused_not_empty(tmp_path):
    bad = tmp_path / "not_a_pdf.pdf"
    bad.write_bytes(b"this is plain text, not a PDF")
    with pytest.raises(ValueError, match="not a readable PDF"):
        pdf_reader.read(bad)
    with pytest.raises(ValueError, match="not a file"):
        pdf_reader.read(tmp_path / "missing.pdf")


def test_extract_uses_the_approved_reader_by_default(pdf):
    doc = pe.extract(pdf([["SYNTHETIC balance sheet"]]))
    assert len(doc.pages) == 1 and doc.pages[0].has_text
