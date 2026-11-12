"""Layout detector: standalone default, labelled parallel sets, notes exclusion, no-text blocker.

Every PDF here is SYNTHETIC (tests/pdf_fixture_builder.py). Its figures are invented for testing and are not a
company's data. The standalone case mirrors the layout of a single-set annual report, so a change to the
consolidation default is caught here rather than in the pilot reports.
"""

from __future__ import annotations

from datetime import date

from engines import pdf_reader
from engines import report_metadata as rm
from tests.pdf_fixture_builder import write_pdf

BS_LINES = [
    "Statement of Financial Position",
    "As at June 30, 2026 2025",
    "Rupees in million",
    "Fixed assets 68,249 67,882",
    "Long term loans 6.50 12.59",
    "Stock-in-trade 1,000 900",
    "Trade debts 2,000 1,800",
    "Cash and bank balances 3,000 2,500",
    "Total assets 74,000 72,000",
    "Share capital 1,200 1,200",
    "Reserves 5,000 4,000",
]
IS_LINES = [
    "Statement of Profit or Loss",
    "For the year ended June 30, 2026 2025",
    "Rupees in million",
    "Turnover 100,000 90,000",
    "Cost of sales (80,000) (70,000)",
    "Gross profit 20,000 20,000",
    "Other income 10 20",
    "Finance cost (50) (60)",
    "Administrative expenses (1,000) (900)",
    "Selling expenses (500) (400)",
    "Taxation (2,000) (1,500)",
    "Profit after taxation 9,000 8,000",
]


def _layout(tmp_path, pages, period_end="2026-06-30"):
    pdf = write_pdf(tmp_path / "report.pdf", pages)
    return rm.detect_layout(pdf_reader.read(pdf), period_end)


def test_a_single_unstated_set_is_standalone_by_assumption_and_extraction_proceeds(tmp_path):
    lay = _layout(tmp_path, [BS_LINES, IS_LINES])
    assert lay["blocker"] is None and lay["missing"] == []
    assert lay["consolidation"] == "unconsolidated"  # standalone
    assert "consolidation_basis_assumed" in lay["flags"]
    assert lay["unit_scale"] == 1_000_000
    assert lay["currency"] == "PKR"
    assert lay["columns"] == ["2026-06-30", "2025-06-30"]
    assert lay["period_column"] == "2026-06-30"
    assert lay["statement_pages"]["BS"] == [1] and lay["statement_pages"]["IS"] == [2]


def test_a_labelled_consolidated_set_is_used_and_not_assumed(tmp_path):
    bs = ["Consolidated Statement of Financial Position", *BS_LINES[1:]]
    lay = _layout(tmp_path, [bs, IS_LINES])
    assert lay["consolidation"] == "consolidated"
    assert "consolidation_basis_assumed" not in lay["flags"]


def test_parallel_labelled_sets_select_the_consolidated_one_and_say_so(tmp_path):
    cons = ["Consolidated Statement of Financial Position", *BS_LINES[1:]]
    unc = ["Unconsolidated Statement of Financial Position", *BS_LINES[1:]]
    lay = _layout(tmp_path, [cons, unc, IS_LINES])
    assert lay["consolidation"] == "consolidated"
    assert "parallel_sets_present" in lay["flags"]
    assert lay["statement_pages"]["BS"] == [1]  # the unconsolidated copy is not read a second time


def test_a_non_matching_period_end_uses_the_column_with_the_same_day_and_month(tmp_path):
    lay = _layout(tmp_path, [BS_LINES, IS_LINES], period_end="2026-06-30")
    assert lay["period_column"] == "2026-06-30"
    (tmp_path / "prior").mkdir()
    prior = _layout(tmp_path / "prior", [BS_LINES, IS_LINES], period_end="2025-06-30")
    assert prior["period_column"] == "2025-06-30"  # the prior-year column is matched exactly, not assumed


def test_a_statement_with_no_readable_amounts_is_a_no_text_blocker(tmp_path):
    bare = ["Statement of Financial Position", "As at June 30, 2026"]
    lay = _layout(tmp_path, [bare, bare])
    assert lay["blocker"] == "no_text_layer"


def test_a_notes_page_with_the_same_title_is_not_a_second_balance_sheet(tmp_path):
    notes = [
        "NOTES TO THE FINANCIAL STATEMENTS",
        "Consolidated statement of financial position details",
        *BS_LINES[3:],
    ]
    lay = _layout(tmp_path, [BS_LINES, notes])
    assert lay["statement_pages"]["BS"] == [1]


def test_the_column_dates_are_read_from_split_headers():
    assert rm.detect_column_dates(["AS AT JUNE, 30", "2026 2025"]) == [date(2026, 6, 30), date(2025, 6, 30)]
    assert rm.detect_column_dates(["As at 30 June 2026", "As at 30 June 2025"]) == [
        date(2026, 6, 30),
        date(2025, 6, 30),
    ]
    assert rm.detect_column_dates(["30.06.2026 30.06.2025"]) == [date(2026, 6, 30), date(2025, 6, 30)]


def test_units_are_read_from_the_common_forms():
    assert rm.detect_unit_scale(["(Rs. '000s)"]) == 1000
    assert rm.detect_unit_scale(["Rupees in million"]) == 1_000_000
    assert rm.detect_unit_scale(["Rs. (Millions)"]) == 1_000_000
    assert rm.detect_unit_scale(["in thousands", "in million"]) is None  # both stated: ambiguous


# ---- analysis pages are never statutory; the two-column statement is preferred ----

ANALYSIS_LINES = [
    "Horizontal Statement of Financial Position",
    "As at June 30, 2026 2025 2024 2023 2022 2021",
    "Rupees in million % Rupees in million % Rupees in million % Rupees in million %",
    "Fixed assets 68,249 218.6% 67,882 217.4% 23,559 100.0% 21,000 90.0%",
    "Long term loans 6.50 17.6% 12.59 34.0% 9.10 50.0% 8.00 40.0%",
    "Stock-in-trade 1,000 100.0% 900 90.0% 800 80.0% 700 70.0%",
    "Trade debts 2,000 50.0% 1,800 45.0% 1,600 40.0% 1,400 35.0%",
    "Cash and bank balances 3,000 12.0% 2,500 10.0% 2,000 8.0% 1,500 6.0%",
    "Total assets 74,000 100.0% 72,000 100.0% 70,000 100.0% 65,000 100.0%",
]


def test_a_horizontal_analysis_page_is_rejected_even_when_it_is_the_only_balance_sheet(tmp_path):
    lay = _layout(tmp_path, [ANALYSIS_LINES, IS_LINES])
    assert "BS" not in lay["statement_pages"]
    assert lay["blocker"] == "layout"


def test_the_statutory_two_column_statement_is_selected_over_a_horizontal_analysis_page(tmp_path):
    lay = _layout(tmp_path, [ANALYSIS_LINES, BS_LINES, IS_LINES])
    assert lay["statement_pages"]["BS"] == [2]
    assert 1 not in lay["statement_pages"].get("BS", [])


def test_a_six_column_history_table_is_never_selected_as_statutory(tmp_path):
    history = [
        "Statement of Financial Position",
        "As at June 30, 2026 2025 2024 2023 2022 2021",
        *BS_LINES[3:],
    ]
    lay = _layout(tmp_path, [history, IS_LINES])
    assert "BS" not in lay["statement_pages"]


def test_a_percent_row_reads_as_its_values_only_and_a_genuine_row_is_untouched():
    from engines.financials import parse_statement_text

    rows = parse_statement_text(
        "Fixed assets 68,249.43 218.6% 67,882.48 217.4%\nTotal assets 74,000 72,000",
        statement="BS",
        columns=["2026-06-30", "2025-06-30"],
    )
    values = {(r["raw_label"], r["column_period_end"]): r["value"] for r in rows["lines"]}
    assert values[("Fixed assets", "2026-06-30")] == 68249.43
    assert values[("Fixed assets", "2025-06-30")] == 67882.48
    assert values[("Total assets", "2025-06-30")] == 72000
