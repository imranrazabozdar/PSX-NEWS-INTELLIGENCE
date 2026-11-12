"""Fiscal-period arithmetic: the period-end date is the key; the fiscal label is derived from it, never
from the
calendar year alone."""

from __future__ import annotations

from datetime import date

import pytest

from engines import fiscal_period as fp


def test_a_june_year_end_company_half_year_to_31_december_2025_is_h1_fy2026():
    end = date(2025, 12, 31)
    assert fp.fiscal_year_of(end, "06-30") == 2026  # never the calendar year 2025
    assert fp.fiscal_label(end, "06-30", "half_year") == "H1 FY2026"


def test_a_december_year_end_company_31_december_is_the_calendar_year():
    end = date(2025, 12, 31)
    assert fp.fiscal_year_of(end, "12-31") == 2025
    assert fp.fiscal_label(end, "12-31", "annual_report") == "FY2025"


@pytest.mark.parametrize(
    "end,fye,report_type,label",
    [
        (date(2026, 6, 30), "06-30", "annual_report", "FY2026"),
        (date(2025, 9, 30), "06-30", "quarterly", "Q1 FY2026"),
        (date(2025, 12, 31), "06-30", "quarterly", "Q2 FY2026"),
        (date(2026, 3, 31), "06-30", "quarterly", "Q3 FY2026"),
        (date(2026, 3, 31), "06-30", "financial_statements", "Q3 FY2026"),
        (date(2026, 9, 30), "03-31", "quarterly", "Q2 FY2027"),
    ],
)
def test_fiscal_labels_follow_the_period_end_and_the_year_end(end, fye, report_type, label):
    assert fp.fiscal_label(end, fye, report_type) == label


def test_a_report_that_does_not_fit_its_type_is_refused():
    # 31 December is the fiscal year-end for a December company: a 'half-year' there is not a half-year
    with pytest.raises(ValueError, match="6 months"):
        fp.fiscal_label(date(2025, 12, 31), "12-31", "half_year")
    # an annual report cannot end mid-year for a June company
    with pytest.raises(ValueError, match="fiscal year-end"):
        fp.fiscal_label(date(2025, 12, 31), "06-30", "annual_report")


def test_a_period_end_must_be_a_month_end():
    with pytest.raises(ValueError, match="month-end"):
        fp.fiscal_label(date(2025, 12, 15), "06-30", "quarterly")


@pytest.mark.parametrize("bad", ["", "6-30", "02-30", "13-01", "06/30", "00-10"])
def test_an_invalid_fiscal_year_end_is_refused(bad):
    with pytest.raises(ValueError):
        fp.parse_fye(bad)


def test_quarter_and_half_period_ends_are_computed_from_the_fiscal_year():
    assert fp.period_end_for_quarter(2027, 1, "06-30") == date(2026, 9, 30)
    assert fp.period_end_for_quarter(2026, 3, "06-30") == date(2026, 3, 31)
    assert fp.period_end_for_half(2026, "06-30") == date(2025, 12, 31)
    assert fp.period_end_for_half(2026, "12-31") == date(2026, 6, 30)


def test_the_scope_window_counts_fiscal_years_from_the_year_end():
    today = date(2026, 11, 12)
    assert fp.scope_window(today, "06-30", 2) == (
        2026,
        2028,
    )  # FY2027 is current; keep FY2026, FY2027, FY2028
    assert fp.scope_window(today, "12-31", 2) == (2025, 2027)  # FY2026 is current; keep FY2025 and FY2026
