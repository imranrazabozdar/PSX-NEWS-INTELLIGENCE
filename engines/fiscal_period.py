"""Fiscal-period arithmetic: the period-end date is the key; the fiscal label is derived from it.

Rules:
* The canonical key of a report is its PERIOD-END DATE (for example 2025-12-31), exactly as the report
states it.
* The fiscal year is never inferred from the calendar year alone. It is derived from the company's fiscal
year-end
  (fye, given as MM-DD). A period ends in fiscal year FY when it lies after the previous fiscal year-end
  and on or
  before the fiscal year-end of FY.
* The label follows from how many months into the fiscal year the period ends, and from the report type:
    - a 12-month period is the full year:        "FY2026"
    - a 6-month period is the first half:         "H1 FY2026"   (a half-year report)
    - a 3, 6 or 9-month period is a quarter:      "Q1 FY2026", "Q2 FY2026", "Q3 FY2026" (a quarterly report)

Example: a June year-end company's half-year to 31 December 2025 is H1 FY2026. A December year-end company's
31 December 2025 report is FY2025.

Pure functions only: no I/O.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

REPORT_TYPES = ("annual_report", "half_year", "quarterly", "financial_statements")
_FYE = re.compile(r"^(0[1-9]|1[0-2])-(\d{2})$")


def parse_fye(fye: str) -> tuple[int, int]:
    """'06-30' -> (6, 30). Refuses anything that is not a real month-end day."""
    m = _FYE.match(fye or "")
    if not m:
        raise ValueError(f"fiscal year-end must be MM-DD, got {fye!r}")
    month, day = int(m.group(1)), int(m.group(2))
    if day > calendar.monthrange(2026, month)[1]:  # 2026 is not a leap year: 02-29 is refused
        raise ValueError(f"{fye!r} is not a real date")
    return month, day


def fye_date(fiscal_year: int, fye: str) -> date:
    month, day = parse_fye(fye)
    return date(fiscal_year, month, day)


def fiscal_year_of(period_end: date, fye: str) -> int:
    """The fiscal year that contains this period end (the year of the next fiscal year-end on or after it)."""
    candidate = fye_date(period_end.year, fye)
    return period_end.year if candidate >= period_end else period_end.year + 1


def months_into_fiscal_year(period_end: date, fye: str) -> int:
    """How many whole months of the fiscal year have elapsed at this period end. Period ends must be
    month-ends."""
    if period_end.day != calendar.monthrange(period_end.year, period_end.month)[1]:
        raise ValueError(f"{period_end.isoformat()} is not a month-end period end")
    prior = fye_date(fiscal_year_of(period_end, fye) - 1, fye)
    return (period_end.year - prior.year) * 12 + (period_end.month - prior.month)


def subtract_months(end: date, months: int) -> date:
    """The month-end that is `months` months before a month-end date."""
    total = end.year * 12 + (end.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, calendar.monthrange(year, month)[1])


def fiscal_label(period_end: date, fye: str, report_type: str) -> str:
    """The fiscal label derived from the period end, the fiscal year-end and the report type."""
    if report_type not in REPORT_TYPES:
        raise ValueError(f"unknown report type {report_type!r}")
    fy = fiscal_year_of(period_end, fye)
    months = months_into_fiscal_year(period_end, fye)
    if report_type == "half_year":
        if months != 6:
            raise ValueError(f"a half-year report must end 6 months into the fiscal year, not {months}")
        return f"H1 FY{fy}"
    if report_type == "annual_report" or (report_type == "financial_statements" and months == 12):
        if months != 12:
            raise ValueError(f"an annual report must end at the fiscal year-end, not {months} months in")
        return f"FY{fy}"
    if months not in (3, 6, 9):
        raise ValueError(f"a quarterly report must end 3, 6 or 9 months into the fiscal year, not {months}")
    return f"Q{months // 3} FY{fy}"


def period_end_for_quarter(fiscal_year: int, quarter: int, fye: str) -> date:
    """Q1..Q3 of a fiscal year: 3, 6 or 9 months before its fiscal year-end (month-end aligned)."""
    if quarter not in (1, 2, 3):
        raise ValueError("quarter must be 1, 2 or 3 here; the year-end itself is the annual report")
    return subtract_months(fye_date(fiscal_year, fye), 12 - 3 * quarter)


def period_end_for_half(fiscal_year: int, fye: str) -> date:
    return subtract_months(fye_date(fiscal_year, fye), 6)


def scope_window(today: date, fye: str, years_back: int = 2) -> tuple[int, int]:
    """Inclusive fiscal-year window: the current fiscal year and the years_back-1 before it, plus the next
    one."""
    current = fiscal_year_of(today, fye)
    return current - (years_back - 1), current + 1
