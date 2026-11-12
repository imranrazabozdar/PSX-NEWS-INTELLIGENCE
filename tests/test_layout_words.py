"""Position-aware statement reading: coordinate de-overprint, two-column headers, and the integrity gate.

Every page here is SYNTHETIC: characters are placed at chosen coordinates to model the overprint pattern. The
figures are invented for testing. The integrity rule under test: a row that stays ambiguous, or a page that
does not show two non-copied period columns, is requires_review and is never reconciled.
"""

from __future__ import annotations

from engines import layout_words as lw

WIDTH = 4.0  # points per character in these fixtures


def place(text: str, x_right: float, top: float) -> list[dict]:
    """Characters of `text` laid out so that the word's right edge is at x_right, on baseline `top`."""
    x0 = x_right - WIDTH * len(text)
    return [
        {"text": ch, "x0": x0 + i * WIDTH, "x1": x0 + (i + 1) * WIDTH, "top": top}
        for i, ch in enumerate(text)
    ]


def two_column_page(rows: list[tuple[str, str, str, float]], years=("2026", "2025")) -> list[dict]:
    """A header with two year columns, then rows of (label, current, comparative, top)."""
    chars: list[dict] = []
    chars += place(years[0], 300, 40) + place(years[1], 380, 40)
    for label, cur, comp, top in rows:
        chars += place(label, 150, top) + place(cur, 330, top) + place(comp, 410, top)
    return chars


ROWS = [
    ("Fixed assets", "68,249", "67,882", 100.0),
    ("Stock-in-trade", "3,420", "1,609", 110.0),
    ("Trade debts", "32,431", "28,966", 120.0),
    ("Cash and bank", "25,824", "31,248", 130.0),
]


def test_a_label_printed_twice_at_one_position_is_read_once():
    chars = place("TOTAL", 150, 200) + place(
        "TOTAL", 150, 200
    )  # the same glyphs drawn twice, identical position
    kept, dropped = lw.dedupe_chars(chars)
    words = lw.words_from_chars(kept)
    assert [w.text for w in words] == ["TOTAL"]
    assert dropped == 5


def test_a_figure_printed_twice_at_one_position_is_read_once_and_a_second_column_is_kept():
    chars = place("68,249", 330, 100) * 2 + place("67,882", 410, 100)
    chars = chars[:6] + place("68,249", 330, 100) + place("67,882", 410, 100)
    kept, dropped = lw.dedupe_chars(chars)
    texts = [w.text for w in lw.words_from_chars(kept)]
    assert texts.count("68,249") == 1 and texts.count("67,882") == 1
    assert dropped >= 6


def test_a_two_column_header_with_the_year_repeated_yields_two_columns():
    chars = place("2026", 300, 40) + place("2026", 300, 40) + place("2025", 380, 40) + place("2025", 380, 40)
    kept, _ = lw.dedupe_chars(chars)
    words = lw.words_from_chars(kept)
    assert len(lw.header_year_columns(words, above_top=200)) == 2


def test_a_clean_two_column_page_passes_the_gate():
    page = lw.read_page(two_column_page(ROWS))
    header = lw.header_year_columns(
        lw.words_from_chars(lw.dedupe_chars(two_column_page(ROWS))[0]), above_top=90
    )
    verdict = lw.integrity_verdict(page, expected_columns=2, header_columns=header)
    assert verdict["verdict"] == "ok", verdict
    assert len(page["columns"]) == 2


def test_a_row_with_two_figures_in_one_column_stays_ambiguous_and_is_requires_review():
    chars = two_column_page(ROWS)
    chars += place("1,000", 330, 150) + place("2,000", 352, 150)  # two figures competing for the same column
    page = lw.read_page(chars)
    assert page["ambiguous"], "the two figures must be recorded as ambiguous, not resolved"
    header = lw.header_year_columns(lw.words_from_chars(lw.dedupe_chars(chars)[0]), above_top=90)
    verdict = lw.integrity_verdict(page, expected_columns=2, header_columns=header)
    assert verdict["verdict"] == "requires_review"


def test_a_page_whose_columns_are_copies_of_each_other_is_requires_review():
    # the same figure in both columns on every row: one column is a copy of the other (the overprint pattern)
    rows = [(label, cur, cur, top) for label, cur, _, top in ROWS]
    page = lw.read_page(two_column_page(rows))
    header = lw.header_year_columns(
        lw.words_from_chars(lw.dedupe_chars(two_column_page(rows))[0]), above_top=90
    )
    verdict = lw.integrity_verdict(page, expected_columns=2, header_columns=header)
    assert verdict["verdict"] == "requires_review"
    assert any("copies" in r for r in verdict["reasons"])


def test_four_year_columns_where_two_are_expected_is_requires_review():
    chars = two_column_page(ROWS, years=("2026", "2025"))
    chars += place("2024", 460, 40) + place("2023", 500, 40)
    page = lw.read_page(chars)
    header = lw.header_year_columns(lw.words_from_chars(lw.dedupe_chars(chars)[0]), above_top=90)
    verdict = lw.integrity_verdict(page, expected_columns=2, header_columns=header)
    assert verdict["verdict"] == "requires_review"
