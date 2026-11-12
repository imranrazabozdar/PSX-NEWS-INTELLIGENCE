"""Statement rows that carry a note-reference column, and labels printed twice by a text-layer overprint.

Every figure here is SYNTHETIC. The layout (Description | Note | Current | Comparative) follows the common
Pakistani statement form; the numbers are invented for testing.
"""

from __future__ import annotations

from engines.financials import _dedupe_label, parse_statement_text

COLUMNS = ["2025-09-30", "2025-06-30"]


def _values(text: str) -> dict[tuple[str, str], float | None]:
    rows = parse_statement_text(text, statement="BS", columns=COLUMNS)
    return {(r["raw_label"], r["column_period_end"]): r["value"] for r in rows["lines"]}


def test_a_note_reference_before_two_amounts_is_stripped_and_both_amounts_kept():
    values = _values("Long-term loans 5 1,000 900")
    assert values[("Long-term loans", "2025-09-30")] == 1000
    assert values[("Long-term loans", "2025-06-30")] == 900


def test_a_dotted_note_reference_is_stripped_too():
    values = _values("Stock-in-trade 4.1 2,500 2,100")
    assert values[("Stock-in-trade", "2025-09-30")] == 2500
    assert values[("Stock-in-trade", "2025-06-30")] == 2100


def test_a_label_only_row_is_left_untouched_and_yields_no_values():
    rows = parse_statement_text("NON-CURRENT ASSETS", statement="BS", columns=COLUMNS)
    assert rows["lines"] == []


def test_a_label_printed_twice_is_read_once():
    assert _dedupe_label("TOTAL ASSETSTOTAL ASSETS") == "TOTAL ASSETS"
    assert _dedupe_label("Stock-in-tradeStock-in-trade") == "Stock-in-trade"


def test_a_label_that_is_not_an_exact_doubling_is_left_as_printed():
    assert (
        _dedupe_label("Property,plantProperty,plant and equipment")
        == "Property,plantProperty,plant and equipment"
    )
    assert _dedupe_label("Long-term loans") == "Long-term loans"


def test_a_doubled_total_row_parses_to_a_single_label_with_its_values():
    values = _values("TOTAL ASSETSTOTAL ASSETS 155,815,229 155,815,229")
    assert values[("TOTAL ASSETS", "2025-09-30")] == 155815229
