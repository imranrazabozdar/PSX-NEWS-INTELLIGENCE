"""De-shadow (collapse copy-columns), the distinct-column gate, and the glued-heading split.

Every page here is SYNTHETIC: characters are placed at chosen coordinates. The figures are invented.
Rules under test: copy-columns collapse to their representative; a page with other than two distinct value
columns is requires_review; a statement heading glued to a label is split off, and total equity is never read
from the equity-and-liabilities row.
"""

from __future__ import annotations

from engines import layout_words as lw

WIDTH = 4.0


def place(text: str, x_right: float, top: float) -> list[dict]:
    x0 = x_right - WIDTH * len(text)
    return [
        {"text": ch, "x0": x0 + i * WIDTH, "x1": x0 + (i + 1) * WIDTH, "top": top}
        for i, ch in enumerate(text)
    ]


def page(rows, column_x: list[float], years: list[tuple[str, float]]) -> list[dict]:
    """rows: (label, [value per column], top). column_x: right edges of the value columns.
    years: header years."""
    chars: list[dict] = []
    for text, x in years:
        chars += place(text, x, 40)
    for label, values, top in rows:
        chars += place(label, 150, top)
        for value, x in zip(values, column_x, strict=True):
            if value is not None:
                chars += place(value, x, top)
    return chars


ROWS_TWO = [
    ("Fixed assets", ["68,249", "67,882"], 100.0),
    ("Stock-in-trade", ["3,420", "1,609"], 110.0),
    ("Trade debts", ["32,431", "28,966"], 120.0),
    ("Cash and bank", ["25,824", "31,248"], 130.0),
]


def _gate(chars, expected=2):
    raw = lw.read_page(chars)
    ds = lw.apply_deshadow(raw)
    words = lw.words_from_chars(lw.dedupe_chars(chars)[0])
    top = min((r.top for r in ds["rows"] if r.cells), default=1e9)
    header = lw.header_year_columns(words, above_top=top)
    return ds, lw.integrity_verdict(ds, expected_columns=expected, header_columns=header)


def test_a_copy_column_collapses_and_a_two_column_page_extracts():
    # each value is printed again 37 points to the right (a shadow copy), with the same figure
    column_x = [330.0, 367.0, 410.0, 447.0]
    rows = [(label, [vals[0], vals[0], vals[1], vals[1]], top) for label, vals, top in ROWS_TWO]
    chars = page(rows, column_x, years=[("2026", 330.0), ("2025", 410.0)])
    ds, verdict = _gate(chars)
    assert ds["distinct_columns"] == 2
    assert verdict["verdict"] == "ok", verdict
    row = next(r for r in ds["rows"] if r.label == "Fixed assets")
    assert row.cells[0][0] == "68,249" and row.cells[1][0] == "67,882"


def test_three_distinct_value_columns_are_requires_review():
    column_x = [330.0, 390.0, 450.0]
    third = {
        "Fixed assets": "1,111",
        "Stock-in-trade": "2,222",
        "Trade debts": "3,333",
        "Cash and bank": "4,444",
    }
    rows = [(label, [vals[0], vals[1], third[label]], top) for label, vals, top in ROWS_TWO]
    chars = page(rows, column_x, years=[("2026", 330.0), ("2025", 390.0), ("2024", 450.0)])
    ds, verdict = _gate(chars)
    assert ds["distinct_columns"] == 3
    assert verdict["verdict"] == "requires_review"
    assert any("3 distinct value columns" in r for r in verdict["reasons"])


def test_a_glued_equity_and_liabilities_heading_is_split_off_and_total_equity_is_not_taken_from_it():
    assert lw.split_heading_label("TOTAL EQUITY AND LIABILITIES") == ("TOTAL", "EQUITY AND LIABILITIES")
    # a true total-equity label is a data label of its own and is kept whole
    assert lw.split_heading_label("TOTAL EQUITY") == ("TOTAL EQUITY", None)
    assert lw.split_heading_label("TOTAL LIABILITIES") == ("TOTAL LIABILITIES", None)
    assert lw.split_heading_label("Trade debts") == ("Trade debts", None)


def test_a_row_that_stays_ambiguous_after_de_shadow_is_requires_review_not_reconciled():
    rows = list(ROWS_TWO)
    chars = page(
        [(label, vals, top) for label, vals, top in rows],
        [330.0, 410.0],
        years=[("2026", 330.0), ("2025", 410.0)],
    )
    chars += place("1,305,584", 370, 150.0)  # a figure between the two columns: outside every band
    ds, verdict = _gate(chars)
    assert verdict["verdict"] == "requires_review"
    assert ds["ambiguous"]
