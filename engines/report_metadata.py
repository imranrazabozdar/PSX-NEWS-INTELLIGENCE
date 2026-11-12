"""Layout facts a statement extraction needs, read from the statement pages' own text. Pure: no I/O.

The extraction needs four facts per report: the statement pages, the column dates, the unit scale and the
consolidation basis (plus the currency). They are detected here.

Rules:
* A statement page is a page that carries a statement HEADING as a whole line (not a phrase inside a note
or the
  contents page) AND carries amount-bearing lines (a contents page has page numbers, not amounts).
* A heading with no amounts on its page, where the page has no text, is reported as a NO-TEXT-LAYER
blocker: the
  statement is drawn as vector outlines or images and cannot be read without OCR. That is not a layout
  problem.
* Detection never guesses. A fact that is absent or ambiguous is reported as missing, and the report is then
  marked requires_review with the reason.
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
# 'as at June 30' or 'AS AT JUNE, 30' (the day may sit on the same line as the month)
_AS_AT = re.compile(rf"\bas\s+(?:at|on)\s+{_MONTH},?\s*(\d{{1,2}})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_AMOUNT = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")

# Heading lines, matched against the whole normalised line. Optional modifiers are the common report styles.
_MODIFIER = r"(?:(?:horizontal|vertical|condensed interim|consolidated|separate|standalone|stand-alone)\s+)*"
_HEADINGS = {
    "BS": re.compile(
        rf"^{_MODIFIER}(?:statement of financial position|balance sheet|statement of assets and liabilities)"
        r"(?:\s*-\s*(?:liability|asset) side)?$"
    ),
    "IS": re.compile(
        rf"^{_MODIFIER}(?:statement of profit or loss|profit and loss account|income statement)$"
    ),
    "OCI": re.compile(rf"^{_MODIFIER}statement of comprehensive income$"),
    "CF": re.compile(rf"^{_MODIFIER}(?:statement of cash flows|cash flow statement)$"),
    "EQ": re.compile(rf"^{_MODIFIER}statement of changes in equity$"),
}
_SCALE_THOUSAND = re.compile(r"in\s+(?:thousands?|'000|’000|\"000|000s)|'000'|’000’|\(000\)", re.IGNORECASE)
_SCALE_MILLION = re.compile(r"in\s+millions?|\(000,000\)|'000,000", re.IGNORECASE)
_BARE_RUPEES = re.compile(r"\(\s*rupees\s*\)|\(\s*pkr\s*\)", re.IGNORECASE)
HEADER_LINES = 30  # the column dates sit in the statement's header block
HEADING_CONTEXT = 3  # lines above a heading that may say consolidated or separate


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower().replace("’", "'"))


def _text(lines: list[str]) -> str:
    return " ".join(lines)


def heading_code(line: str) -> str | None:
    n = _norm(line)
    for code, rx in _HEADINGS.items():
        if rx.match(n):
            return code
    return None


def amount_lines(lines: list[str]) -> int:
    return sum(1 for ln in lines if _AMOUNT.search(ln))


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
    if "unconsolidated" in t or "separate financial statements" in t or re.search(r"stand-?alone", t):
        return "unconsolidated"
    if "consolidated" in t:
        return "consolidated"
    return None


def detect_currency(lines: list[str]) -> str | None:
    t = _text(lines).lower()
    if "pkr" in t or "rupees" in t or "rs." in t:
        return "PKR"
    return None


def _safe(month: int, day: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def detect_column_dates(lines: list[str]) -> list[date]:
    """The statement's value columns, in order. Explicit dates first; otherwise the 'as at <month> <day>'
    phrase is
    combined with each year printed in the header, which is how many reports split the date across lines."""
    explicit: list[date] = []
    for line in lines:
        for m in _DATE_MDY.finditer(line):
            explicit.append(_safe(_MONTHS[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))))
        for m in _DATE_DMY.finditer(line):
            explicit.append(_safe(_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), int(m.group(3))))
    distinct_explicit: list[date] = []
    for d in explicit:
        if d is not None and d not in distinct_explicit:
            distinct_explicit.append(d)
    if len(distinct_explicit) >= 2:
        return distinct_explicit
    joined = _text(lines)
    as_at = _AS_AT.search(joined)
    if not as_at:
        return distinct_explicit
    month, day = _MONTHS[as_at.group(1).lower()[:3]], int(as_at.group(2))
    years: list[int] = []
    for y in _YEAR.findall(joined):
        if int(y) not in years:
            years.append(int(y))
    dates = [d for d in (_safe(month, day, y) for y in years) if d is not None]
    return dates


def _statement_pages(doc: pe.DocumentText) -> dict[str, list[int]]:
    """Pages whose heading line is a statement title AND that carry amounts. Contents and notes are
    excluded."""
    found: dict[str, list[int]] = {}
    no_text: dict[str, list[int]] = {}
    for page in doc.pages:
        for line in page.lines:
            code = heading_code(line)
            if code is None:
                continue
            if amount_lines(page.lines) >= 6:
                if page.number not in found.setdefault(code, []):
                    found[code].append(page.number)
            else:
                no_text.setdefault(code, []).append(page.number)  # heading present, body not readable
            break  # one heading per page is enough to classify it
    return {"found": found, "no_text": no_text}


def detect_layout(doc: pe.DocumentText, period_end: str) -> dict:
    """Facts for one report, the statement pages, the blocker class (if any) and what is missing."""
    located = _statement_pages(doc)
    found, no_text = located["found"], located["no_text"]
    if not found and no_text:
        return {
            "blocker": "no_text_layer",
            "missing": ["statement bodies have no text layer"],
            "statement_pages": {},
            "no_text_pages": no_text,
        }
    if not found and not any(amount_lines(p.lines) for p in doc.pages):
        return {
            "blocker": "no_text_layer",
            "missing": [
                "no amount text anywhere in the report: statement bodies are "
                "drawn as vector outlines or images"
            ],
            "statement_pages": {},
            "no_text_pages": {},
        }
    if "BS" not in found:
        blocker = "no_text_layer" if "BS" in no_text else "layout"
        reason = (
            "balance sheet body has no text layer"
            if blocker == "no_text_layer"
            else "no balance sheet found with its heading and amounts"
        )
        return {"blocker": blocker, "missing": [reason], "statement_pages": found, "no_text_pages": no_text}
    by_number = {p.number: p for p in doc.pages}
    statement_lines: list[str] = []
    for code in found:
        for number in found[code]:
            statement_lines += by_number[number].lines
    bs_head = by_number[found["BS"][0]].lines[:HEADER_LINES]
    context: list[str] = []
    for code in ("BS", "IS", "CF", "EQ"):
        for number in found.get(code, [])[:1]:
            lines = by_number[number].lines
            for idx, line in enumerate(lines):
                if heading_code(line) == code:
                    context += lines[max(0, idx - HEADING_CONTEXT) : idx + 1]
                    break
    missing: list[str] = []
    unit = detect_unit_scale(statement_lines)
    consolidation = detect_consolidation(context)
    currency = detect_currency(statement_lines)
    dates = detect_column_dates(bs_head)
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
        "blocker": None if not missing else "layout",
        "unit_scale": unit,
        "consolidation": consolidation,
        "currency": currency,
        "columns": [d.isoformat() for d in dates],
        "statement_pages": found,
        "no_text_pages": no_text,
        "missing": missing,
    }
