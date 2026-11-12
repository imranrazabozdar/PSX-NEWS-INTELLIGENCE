"""Layout facts a statement extraction needs, read from the statement pages' own text. Pure: no I/O.

The extraction needs four facts per report: the column dates, the unit scale, the consolidation basis and the
currency. They are detected here from the statement headings. Detection never guesses: a fact that is
absent or
ambiguous is reported as missing, and the report is then marked requires_review with the reason.
"""

from __future__ import annotations

import re
from datetime import date

from engines import pdf_extraction as pe

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_MDY = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.IGNORECASE)
_DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s+(20\d{{2}})\b", re.IGNORECASE)
_SCALE_THOUSAND = re.compile(
    r"in\s+(thousands?|'000|’000|\"000|000s)|'000'|’000’|\(000\)|000s", re.IGNORECASE
)
_SCALE_MILLION = re.compile(r"in\s+millions?|\(000,000\)|'000,000", re.IGNORECASE)
_BARE_RUPEES = re.compile(r"\(\s*rupees\s*\)|\(\s*pkr\s*\)", re.IGNORECASE)
HEAD_LINES = 12  # the column dates sit in the statement's header block


def _text(lines: list[str]) -> str:
    return " ".join(lines)


def detect_unit_scale(lines: list[str]) -> int | None:
    """1000 for 'in thousands' / "Rupees in '000", 1000000 for 'in millions', 1 for a bare '(Rupees)'."""
    text = _text(lines)
    thousand = bool(_SCALE_THOUSAND.search(text))
    million = bool(_SCALE_MILLION.search(text))
    if million and not thousand:
        return 1_000_000
    if thousand and not million:
        return 1000
    if thousand and million:
        return None  # both stated: ambiguous, so not guessed
    if _BARE_RUPEES.search(text):
        return 1
    return None


def detect_consolidation(lines: list[str]) -> str | None:
    t = _text(lines).lower()
    if (
        "unconsolidated" in t
        or "separate financial statements" in t
        or "stand-alone" in t
        or "standalone" in t
    ):
        return "unconsolidated"
    if "consolidated" in t:
        return "consolidated"
    return None


def detect_currency(lines: list[str]) -> str | None:
    t = _text(lines).lower()
    if "pkr" in t or "rupees" in t or "rs." in t or "rs '" in t:
        return "PKR"
    return None


def detect_column_dates(lines: list[str]) -> list[date]:
    """The distinct dates in the header block, in the order they appear: the statement's value columns."""
    found: list[date] = []
    for line in lines:
        for m in _DATE_MDY.finditer(line):
            found.append(_safe(_MONTHS[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))))
        for m in _DATE_DMY.finditer(line):
            found.append(_safe(_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), int(m.group(3))))
    out: list[date] = []
    for d in found:
        if d is not None and d not in out:
            out.append(d)
    return out


def _safe(month: int, day: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def detect_layout(doc: pe.DocumentText, period_end: str) -> dict:
    """The layout facts for one report, plus the list of facts that could not be detected and why."""
    pages = pe.locate_statements(doc)
    missing: list[str] = []
    bs_pages = pages.get("BS", [])
    if not bs_pages:
        return {"missing": ["balance sheet heading not found"], "statement_pages": pages}
    by_number = {p.number: p for p in doc.pages}
    statement_lines: list[str] = []
    head: list[str] = []
    for code in ("BS", "IS", "CF", "EQ"):
        for number in pages.get(code, []):
            statement_lines += by_number[number].lines
    for number in bs_pages[:1]:
        head += by_number[number].lines[:HEAD_LINES]
    head_block = []
    for code in ("IS", "CF", "EQ"):
        for number in pages.get(code, [])[:1]:
            head_block += by_number[number].lines[:HEAD_LINES]
    unit = detect_unit_scale(statement_lines)
    consolidation = detect_consolidation(head + head_block)
    currency = detect_currency(statement_lines)
    dates = detect_column_dates(head)
    if unit is None:
        missing.append("unit scale not stated on the statement pages")
    if consolidation is None:
        missing.append("consolidation basis not stated in the statement headings")
    if currency is None:
        missing.append("currency not stated on the statement pages")
    if len(dates) < 2:
        missing.append("fewer than two column dates in the balance sheet header")
    target = date.fromisoformat(period_end)
    if target not in dates:
        missing.append(f"period end {period_end} is not one of the statement's column dates")
    return {
        "unit_scale": unit,
        "consolidation": consolidation,
        "currency": currency,
        "columns": [d.isoformat() for d in dates],
        "statement_pages": pages,
        "missing": missing,
    }
