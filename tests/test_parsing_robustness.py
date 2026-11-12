"""Real-report quirks: brackets, dashes, repeated headers, wrapped labels, split notes. SYNTHETIC text."""

from __future__ import annotations

import pytest

from engines import financials as fin
from engines import notes_extraction as ne
from engines import pdf_extraction as pe
from tests.pdf_fixture_builder import write_pdf

COLS = ["2025-06-30", "2024-06-30"]


@pytest.mark.parametrize(
    "tok,expected",
    [
        ("(1,234)", -1234.0),
        ("(1,234.5)", -1234.5),
        ("1,234", 1234.0),
        ("0", 0.0),
        ("-", None),
        ("—", None),
        ("–", None),
        ("nil", None),
        ("n/a", None),
        ("(0)", 0.0),
    ],
)
def test_parse_number_brackets_and_dashes(tok, expected):
    assert fin.parse_number(tok) == expected


def test_a_reported_zero_is_zero_and_a_dash_is_not_reported():
    r = fin.parse_statement_text("Other income 0 —", statement="IS", columns=COLS)
    vals = {x["column_period_end"]: x["value"] for x in r["lines"]}
    assert vals == {"2025-06-30": 0.0, "2024-06-30": None}


def test_a_dash_in_the_middle_of_a_row_with_a_note_reference_is_parsed():
    r = fin.parse_statement_text("Trade debts 12 — 1,234", statement="BS", columns=COLS)
    assert {x["column_period_end"]: x["value"] for x in r["lines"]} == {
        "2025-06-30": None,
        "2024-06-30": 1234.0,
    }


def test_repeated_column_headers_are_not_read_as_data():
    text = "Rupees in thousand 2025 2024\n2025 2024\nNote 2025 2024\nNet sales 1,000 800"
    r = fin.parse_statement_text(text, statement="IS", columns=COLS)
    assert {x["raw_label"] for x in r["lines"]} == {"Net sales"}
    reasons = [u["reason"] for u in r["unparsed"]]
    assert reasons.count("column header (not data)") == 3


def test_a_label_wrapped_onto_two_lines_is_joined_to_its_figures():
    text = "Long term financing for the expansion\n50 40"
    r = fin.parse_statement_text(text, statement="BS", columns=COLS)
    assert {(x["raw_label"], x["value"]) for x in r["lines"]} == {
        ("Long term financing for the expansion", 50.0),
        ("Long term financing for the expansion", 40.0),
    }
    assert r["unparsed"] == []


def test_a_label_with_no_figures_on_the_next_line_is_kept_for_review():
    r = fin.parse_statement_text(
        "Statement of financial position\nTotal assets 1,000 900", statement="BS", columns=COLS
    )
    assert [x["raw_label"] for x in r["lines"]] == ["Total assets", "Total assets"]
    assert any(u["reason"] == "label without figures" for u in r["unparsed"])


def test_a_header_repeated_on_a_continuation_page_does_not_duplicate_data(tmp_path):
    pages = [
        ["Statement of profit or loss", "Rupees in thousand 2025 2024", "Net sales 1,000 800"],
        ["Rupees in thousand 2025 2024", "Cost of sales (600) (500)", "Gross profit 400 300"],
    ]
    doc = pe.extract(write_pdf(tmp_path / "cont.pdf", pages))
    r = pe.to_statement_lines(doc, "IS", [1, 2], columns=COLS)
    labels = sorted({x["raw_label"] for x in r["lines"]})
    assert labels == ["Cost of sales", "Gross profit", "Net sales"]
    assert len(r["lines"]) == 6  # three labels, two columns each: no duplicated headers


def test_a_note_split_across_pages_with_continued_heading_stays_one_note(tmp_path):
    pages = [
        ["12. Trade debts", "Not yet due 500 400", "Trade debts 500 400"],
        [
            "12. Trade debts (continued)",
            "Expected credit loss allowance (30) (25)",
            "Net trade debts 470 375",
        ],
    ]
    r = ne.extract_notes(pe.extract(write_pdf(tmp_path / "split.pdf", pages)), columns=COLS)
    assert [n["note_no"] for n in r["notes"]] == ["12"]
    ecl = [x for x in r["lines"] if x["raw_label"] == "Expected credit loss allowance"]
    assert ecl and all(x["note_ref"] == "12" for x in ecl)
    assert {x["page"] for x in ecl} == {2}
