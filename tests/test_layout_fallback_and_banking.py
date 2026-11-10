"""Layout-preserving extraction tier, per-page cross-check, owner-confirmed spread regions, SBP bank taxonomy,
label-less total inference, cash-flow FX term, and going-concern boilerplate.

Every statement here is a SYNTHETIC hand-built fixture (generated PDFs from tests/pdf_fixture_builder.py, and
hand-set figures). They test the logic only. They are not evidence of extraction accuracy on a real report.
"""

from __future__ import annotations

import shutil

import pytest

from engines import audit_extraction as ae
from engines import pdf_extraction as pe
from engines import pdf_reader
from engines import statement_pipeline as sp
from engines import statement_reconciliation as rec
from scripts.financial_intake import parse_statement_spec
from tests.pdf_fixture_builder import write_pdf

COLS = ["2025-12-31", "2024-12-31"]
NEEDS_PDFTOTEXT = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="pdftotext (Poppler) not installed"
)


# ------------------------------------------------------------------ per-page cross-check (pure logic)


def test_clean_page_keeps_pdfplumber_text():
    plumber = ["Total assets 1,000 900", "Total liabilities 600 500"]
    layout = ["Total assets      1,000        900", "Total liabilities   600        500"]
    lines, method, metrics = pe.choose_page_text(plumber, layout)
    assert method == "pdfplumber" and lines == plumber
    assert metrics["word_agreement"] == 1.0 and metrics["number_agreement"] == 1.0


def test_interleaved_glyphs_fall_back_to_layout_text():
    # character-interleaved pdfplumber output, as seen on the UBL notes pages
    plumber = ["NFOoTErS tThO eAN yD eFOaRrM IeNGn PdAeRTd O FD TeHEc UeNmCObN 2 5"]
    layout = [
        "Notes to and forming part of the Unconsolidated Financial Statements",
        "Total assets 1,000 900",
    ]
    lines, method, _ = pe.choose_page_text(plumber, layout)
    assert method == "pdftotext_layout" and lines == layout


def test_reversed_numbers_fall_back_to_layout_text():
    # reversed glyphs: "STNEMETATS" for STATEMENTS and "5202" for 2025
    plumber = ["STNEMETATS LAICNANIF 5202 ,13 REBMECED", "seitilibail 1,000 800"]
    layout = ["STATEMENT OF FINANCIAL POSITION AS AT DECEMBER 31, 2025", "Liabilities 1,000 800"]
    lines, method, metrics = pe.choose_page_text(plumber, layout)
    assert method == "pdftotext_layout"
    assert metrics["number_agreement"] < pe.MIN_NUMBER_AGREEMENT


def test_without_a_layout_text_the_page_is_kept_but_marked_unverified():
    lines, method, metrics = pe.choose_page_text(["Total assets 1,000 900"], None)
    assert method == "pdfplumber_unverified" and metrics == {}
    assert lines == ["Total assets 1,000 900"]


def test_a_page_with_no_figures_or_words_in_layout_is_not_replaced_by_nothing():
    lines, method, _ = pe.choose_page_text(["Some plumber text 1 2 3"], [])
    assert method == "pdfplumber_unverified"  # an empty layout text is never used to replace the page


def test_agreement_is_a_multiset_share():
    m = pe.page_agreement(["alpha beta"], ["alpha alpha beta"])
    assert m["word_agreement"] == pytest.approx(2 / 3)  # the second "alpha" has no match left


# ------------------------------------------------------------------ reader modes on generated PDFs


@pytest.fixture
def clean_pdf(tmp_path):
    return write_pdf(
        tmp_path / "clean.pdf",
        [["SYNTHETIC statement of profit or loss", "Net sales 1,000 800", "Cost of sales (600) (500)"], None],
    )


@NEEDS_PDFTOTEXT
def test_auto_mode_tags_every_page_with_its_extraction_method(clean_pdf):
    doc = pdf_reader.read(clean_pdf)
    assert {p.extraction_method for p in doc.pages} <= {"pdfplumber", "pdftotext_layout", "no_text"}
    assert doc.pages[1].extraction_method == "no_text"
    assert sum(doc.method_counts().values()) == len(doc.pages) == 2
    assert doc.warnings == []


@NEEDS_PDFTOTEXT
def test_layout_mode_reads_pages_with_pdftotext(clean_pdf):
    doc = pdf_reader.read(clean_pdf, mode="layout")
    assert doc.pages[0].extraction_method == "pdftotext_layout"
    assert any("Net sales" in ln and "1,000" in ln for ln in doc.pages[0].lines)
    assert doc.pages[1].has_text is False  # a page with no text layer stays without text


def test_pdfplumber_mode_is_unchanged(clean_pdf):
    doc = pdf_reader.read(clean_pdf, mode="pdfplumber")
    assert {p.extraction_method for p in doc.pages} == {"pdfplumber"}


def test_missing_pdftotext_keeps_pdfplumber_text_as_unverified_with_a_warning(clean_pdf, monkeypatch):
    monkeypatch.setattr(pdf_reader.shutil, "which", lambda name: None)
    doc = pdf_reader.read(clean_pdf)
    assert {p.extraction_method for p in doc.pages} == {"pdfplumber_unverified"}
    assert doc.warnings and "unverified" in doc.warnings[0]


def test_layout_mode_refuses_when_pdftotext_is_missing(clean_pdf, monkeypatch):
    monkeypatch.setattr(pdf_reader.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="pdftotext"):
        pdf_reader.read(clean_pdf, mode="layout")


def test_unknown_mode_is_refused(clean_pdf):
    with pytest.raises(ValueError, match="unknown extraction mode"):
        pdf_reader.read(clean_pdf, mode="ocr")


@NEEDS_PDFTOTEXT
def test_region_reader_refuses_bad_side_and_page(clean_pdf):
    with pytest.raises(ValueError, match="side must be L or R"):
        pdf_reader.region_lines(clean_pdf, 1, "X")
    with pytest.raises(ValueError, match="outside the document"):
        pdf_reader.region_lines(clean_pdf, 9, "L")


@NEEDS_PDFTOTEXT
def test_region_reader_returns_text_from_one_half(tmp_path):
    left_right = write_pdf(tmp_path / "halves.pdf", [["Left synthetic figure 111 222"]])
    lines = pdf_reader.region_lines(left_right, 1, "L")
    assert lines and any("Left synthetic" in ln for ln in lines)


def test_non_pdf_is_still_refused_in_every_mode(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"plain text")
    with pytest.raises(ValueError, match="not a readable PDF"):
        pdf_reader.read(bad, mode="pdfplumber")


# ------------------------------------------------------------------ owner statement map


def test_statement_spec_with_spread_sides_is_parsed():
    pages, regions = parse_statement_spec("BS=43R,IS=44L,CF=45R,EQ=45L")
    assert pages == {"BS": [43], "IS": [44], "CF": [45], "EQ": [45]}
    assert regions == {"BS": (43, "R"), "IS": (44, "L"), "CF": (45, "R"), "EQ": (45, "L")}


def test_statement_spec_without_sides_or_empty():
    assert parse_statement_spec("BS=3") == ({"BS": [3]}, None)
    assert parse_statement_spec("") == (None, None)


@pytest.mark.parametrize("bad", ["XX=1", "BS", "BS=", "BS=0", "BS=4X", "BS=43Z"])
def test_bad_statement_spec_is_refused(bad):
    with pytest.raises(ValueError):
        parse_statement_spec(bad)


def test_region_is_parsed_as_its_own_page_and_tagged_with_its_engine():
    region = pe.DocumentText(
        [
            pe.Page(
                number=43,
                lines=["Share capital 22 12,521,239 12,241,797"],
                has_text=True,
                extraction_method="pdftotext_layout_region",
            )
        ]
    )
    ex = sp.extract(
        region,
        columns=COLS,
        statement_regions={"BS": (43, "R")},
        region_reader=lambda p, s: [
            "Share capital 22 12,521,239 12,241,797",
            "Reserves 138,517,698 114,734,831",
        ],
    )
    engines = {ln["extraction_engine"] for ln in ex["lines"]}
    assert engines == {"pdftotext_layout_region"}
    assert ex["statement_pages"] == {"BS": [43]}


def test_regions_need_a_reader():
    doc = pe.DocumentText([pe.Page(number=1, lines=[], has_text=False)])
    with pytest.raises(ValueError, match="region_reader"):
        sp.extract(doc, columns=COLS, statement_regions={"BS": (1, "L")})


# ------------------------------------------------------------------ SBP bank taxonomy kept apart


def test_bank_framework_maps_sbp_lines_and_corporate_does_not():
    bank = sp.load_mappings(framework="bank")
    corp = sp.load_mappings(framework="corporate")
    assert sp.map_label("BS", "Balances with other banks", bank) == ("balances_with_other_banks", 1.0)
    assert sp.map_label("BS", "NET ASSETS", bank) == ("total_equity", 1.0)
    assert sp.map_label("IS", "Mark-up / return / interest earned", bank) == ("interest_earned", 1.0)
    assert sp.map_label("IS", "Fee and commission income", bank)[0] == "fee_commission_income"
    assert sp.map_label("IS", "Total non mark-up / interest expenses", bank)[0] == "non_markup_expenses"
    assert sp.map_label("IS", "Operating expenses", bank)[0] == "operating_expenses"
    assert sp.map_label("CF", "Net cash flow used in investing activities", bank)[0] == "cfi"
    # the corporate working-capital rules never see bank labels
    assert sp.map_label("BS", "Balances with other banks", corp) == (None, None)
    assert sp.map_label("IS", "Fee and commission income", corp) == (None, None)


def test_unknown_framework_is_refused():
    with pytest.raises(ValueError, match="unknown mapping framework"):
        sp.load_mappings(framework="retail")


# ------------------------------------------------------------------ reconciliation: FX on cash


def test_cash_flow_with_printed_fx_effect_reconciles():
    v = {
        "opening_cash": 368_320_156.0,
        "net_change_in_cash": 235_112_499.0,
        "fx_effect_on_cash": 1_394_001.0,
        "closing_cash": 604_826_656.0,
    }
    assert rec.cash_flow("2025", v).status == rec.RECONCILED


def test_cash_flow_without_the_fx_line_shows_the_fx_as_the_difference():
    v = {"opening_cash": 368_320_156.0, "net_change_in_cash": 235_112_499.0, "closing_cash": 604_826_656.0}
    c = rec.cash_flow("2025", v)
    assert c.status == rec.UNRECONCILED and c.discrepancy == pytest.approx(1_394_001.0)


# ------------------------------------------------------------------ label-less printed totals


def _bs_line(code, value, col="2025-12-31", page=43):
    return {
        "statement_type": "BS",
        "canonical_code": code,
        "column_period_end": col,
        "reported_amount": value,
        "pdf_page_number": page,
    }


def test_unlabelled_total_is_inferred_only_when_it_equals_the_components():
    tagged = [_bs_line("cash_and_equivalents", 600.0), _bs_line("advances_net", 400.0)]
    unparsed = [{"statement": "BS", "line": "1,000 900", "page": 43, "extraction_engine": "pdftotext_layout"}]
    out = sp.infer_unlabelled_totals(tagged, unparsed, columns=COLS)
    assert [(r["canonical_code"], r["reported_amount"]) for r in out] == [("total_assets", 1000.0)]
    assert "unlabelled printed total" in out[0]["line_item_name"]


def test_unlabelled_total_that_does_not_match_is_left_alone():
    tagged = [_bs_line("cash_and_equivalents", 600.0), _bs_line("advances_net", 400.0)]
    unparsed = [{"statement": "BS", "line": "1,500 900", "page": 43, "extraction_engine": "x"}]
    assert sp.infer_unlabelled_totals(tagged, unparsed, columns=["2025-12-31"]) == []


def test_ambiguous_unlabelled_totals_are_not_inferred():
    tagged = [_bs_line("cash_and_equivalents", 600.0), _bs_line("advances_net", 400.0)]
    unparsed = [
        {"statement": "BS", "line": "1,000 900", "page": 43, "extraction_engine": "x"},
        {"statement": "BS", "line": "1,000 800", "page": 43, "extraction_engine": "x"},
    ]
    assert sp.infer_unlabelled_totals(tagged, unparsed, columns=["2025-12-31"]) == []


def test_numbers_only_row_reads_brackets_as_negatives_and_rejects_labels():
    assert sp._numbers_only_row("(1,000) 900", 2) == [-1000.0, 900.0]
    assert sp._numbers_only_row("Total assets 1,000 900", 2) is None
    assert sp._numbers_only_row("1,000 900 800", 2) is None


# ------------------------------------------------------------------ provenance and page location


def test_tagged_lines_keep_the_database_category_and_the_engine():
    ex = {
        "lines": [
            {
                "statement": "BS",
                "raw_label": "Total assets",
                "column_period_end": "2025-12-31",
                "value": 1000.0,
                "page": 1,
                "extraction_engine": "pdftotext_layout",
            }
        ],
        "unparsed": [],
        "scanned_pages": [],
        "statement_pages": {"BS": [1]},
        "notes": {},
        "auditor": {},
        "note_lines": [],
        "note_index": [],
        "note_unparsed": [],
        "audit": {},
    }
    doc_meta = {
        "document_id": "d",
        "file_hash": "h",
        "symbol": "X",
        "period_end": "2025-12-31",
        "currency": "PKR",
        "unit_scale": 1000,
        "consolidation": "unconsolidated",
    }
    t = sp.tag(ex, document=doc_meta, extractor_version="v", mapping=sp.load_mappings(framework="bank"))
    row = t["lines"][0]
    assert row["extraction_method"] == "pdf_text"  # database category, migrations are immutable
    assert row["extraction_engine"] == "pdftotext_layout"


# ------------------------------------------------------------------ going-concern boilerplate


def test_conditional_isa_sentence_is_not_a_material_uncertainty():
    doc = pe.DocumentText(
        [
            pe.Page(
                number=42,
                has_text=True,
                extraction_method="pdfplumber",
                lines=[
                    "whether a material uncertainty exists related to events or conditions that may cast "
                    "significant doubt on the Bank's ability to continue as a going concern. "
                    "If we conclude that a material uncertainty exists, "
                    "we are required to draw attention in our auditor's report."
                ],
            )
        ]
    )
    out = ae.emphasis_and_uncertainty(doc)
    assert out["going_concern_material_uncertainty"] == []
    assert out["going_concern_conditional_boilerplate"] >= 1


def test_a_stated_material_uncertainty_is_still_reported():
    doc = pe.DocumentText(
        [
            pe.Page(
                number=3,
                has_text=True,
                extraction_method="pdfplumber",
                lines=[
                    "Material uncertainty related to going concern: the Bank's ability to continue as a "
                    "going concern is in significant doubt."
                ],
            )
        ]
    )
    out = ae.emphasis_and_uncertainty(doc)
    assert len(out["going_concern_material_uncertainty"]) == 1
