"""Layout facts a statement extraction needs, read from the statement pages' own text. Pure: no I/O.

Facts detected: the statement pages (per statement, for ONE basis), the column dates, the unit scale, the
consolidation basis and the currency.

Rules:
* A statement page carries a statement heading as a whole line (a title split over two lines is joined) AND at
  least AMOUNT_PAGE_MIN amount-bearing lines. Contents pages, notes and the "six years at a glance" summary
  are
  excluded.
* A heading whose body has no readable amounts is a NO-TEXT-LAYER case: the statement is drawn as vector
outlines
  or images, and it cannot be read without OCR. This is reported separately from a layout the detector does
  not
  understand.
* Consolidation basis, from the statement heading itself:
    - labelled consolidated and labelled unconsolidated both present: select the consolidated set, flag
      parallel_sets_present;
    - only one labelled set: use it;
    - UNSTATED, with a single column set and no consolidated mention in the headings: STANDALONE is
    assumed, the
      flag consolidation_basis_assumed is set, and extraction proceeds;
    - UNSTATED with a consolidated mention but no clear basis: ambiguous, so the report is requires_review.
  The auditor's opinion and the notes are never read to recover the basis.
* Column dates: explicit dates first; otherwise 'as at <month> <day>' combined with the years in the
header. If the
  period end is not an exact column, the column with the same month and day is used, then the nearest, and the
  flag period_column_assumed is set. If no column can be matched, the report is requires_review.
* Detection never guesses otherwise: an absent fact is reported as missing.
"""

from __future__ import annotations

import re
from datetime import date

from engines import pdf_extraction as pe

AMOUNT_PAGE_MIN = 6  # amount-bearing lines a statement page needs
DOC_AMOUNT_PAGES_MIN = 3  # pages with amounts a report needs before it counts as having a readable body
HEADER_LINES = 30
HEADING_CONTEXT = 3
SUMMARY_MARKERS = ("six years", "at a glance", "notes to the")

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
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b")  # dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_AS_AT = re.compile(rf"\bas\s+(?:at|on)\s+{_MONTH},?\s*(\d{{1,2}})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(20\d{2})\b")
_AMOUNT = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")

_MODIFIER = (
    r"(?:(?:horizontal|vertical|condensed interim|unconsolidated|consolidated|separate|standalone"
    r"|stand-alone)\s+)*"
)
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
_SCALE_THOUSAND = re.compile(
    r"in\s+(?:thousands?|'000|’000|\"000|000s)|'000'|’000’|\(000\)|['‘’]000s|\(\s*000s?\s*\)", re.IGNORECASE
)
_SCALE_MILLION = re.compile(r"in\s+millions?|\(\s*millions?\s*\)|\(000,000\)|'000,000", re.IGNORECASE)
_BARE_RUPEES = re.compile(r"\(\s*rupees\s*\)|\(\s*pkr\s*\)", re.IGNORECASE)


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower().replace("’", "'").replace("‘", "'"))


def _undouble(text: str) -> str:
    """Undo doubled glyphs in uppercase words ("SSTTAATTEEMMEENNTT" -> "STATEMENT"), a text-layer artifact."""
    out = []
    for tok in text.split(" "):
        if len(tok) >= 4 and len(tok) % 2 == 0 and tok.isupper() and tok[0::2] == tok[1::2]:
            out.append(tok[0::2])
        else:
            out.append(tok)
    return " ".join(out)


def heading_code(line: str) -> str | None:
    for candidate in (line, _undouble(line)):
        n = _norm(candidate)
        for code, rx in _HEADINGS.items():
            if rx.match(n):
                return code
    return None


# Analytical appendix pages (trend tables, common-size analysis, ratios): never statutory statements.
ANALYSIS_HEADING = re.compile(r"horizontal|vertical|six[- ]year|analysis|summary|ratios?")


def heading_basis(text: str) -> str | None:
    """'consolidated' or 'unconsolidated' (or standalone/separate) as stated in a heading, else None."""
    n = _norm(text)
    if "unconsolidated" in n or re.search(r"\bseparate\b|stand-?alone", n):
        return "unconsolidated"
    if "consolidated" in n:
        return "consolidated"
    return None


def amount_lines(lines: list[str]) -> int:
    return sum(1 for ln in lines if _AMOUNT.search(ln))


def _text(lines: list[str]) -> str:
    return " ".join(lines)


def detect_unit_scale(lines: list[str]) -> int | None:
    """1000 for 'in thousands', "Rupees in '000", "(Rs. '000s)"; 1000000 for 'in millions', "Rs.
    (Millions)"; 1 for a
    bare '(Rupees)'. Ambiguous (both scales stated) is None, never guessed."""
    text = _text(lines)
    thousand = bool(_SCALE_THOUSAND.search(text))
    million = bool(_SCALE_MILLION.search(text))
    if million and not thousand:
        return 1_000_000
    if thousand and not million:
        return 1000
    if thousand and million:
        return None
    if _BARE_RUPEES.search(text):
        return 1
    return None


def detect_currency(lines: list[str]) -> str | None:
    t = _text(lines).lower()
    return "PKR" if ("pkr" in t or "rupees" in t or "rs." in t) else None


def _safe(month: int, day: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def detect_column_dates(lines: list[str]) -> list[date]:
    """The value columns in order. Explicit dates first; otherwise 'as at <month> <day>' with the header's
    years."""
    explicit: list[date] = []
    for line in lines:
        for m in _DATE_MDY.finditer(line):
            explicit.append(_safe(_MONTHS[m.group(1).lower()[:3]], int(m.group(2)), int(m.group(3))))
        for m in _DATE_DMY.finditer(line):
            explicit.append(_safe(_MONTHS[m.group(2).lower()[:3]], int(m.group(1)), int(m.group(3))))
        for m in _DATE_NUMERIC.finditer(line):
            explicit.append(_safe(int(m.group(2)), int(m.group(1)), int(m.group(3))))
        for m in _DATE_ISO.finditer(line):
            explicit.append(_safe(int(m.group(2)), int(m.group(3)), int(m.group(1))))
    distinct: list[date] = []
    for d in explicit:
        if d is not None and d not in distinct:
            distinct.append(d)
    if len(distinct) >= 2:
        return distinct
    joined = _text(lines)
    as_at = _AS_AT.search(joined)
    if not as_at:
        return distinct
    month, day = _MONTHS[as_at.group(1).lower()[:3]], int(as_at.group(2))
    years: list[int] = []
    for y in _YEAR.findall(joined):
        if int(y) not in years:
            years.append(int(y))
    return [d for d in (_safe(month, day, y) for y in years) if d is not None]


def _is_summary(lines: list[str]) -> bool:
    top = " ".join(lines[:3]).lower()
    return any(marker in top for marker in SUMMARY_MARKERS)


def _scan_statement_pages(doc: pe.DocumentText) -> dict:
    """Heading-bearing pages: readable (with amounts) and unreadable (heading but no amounts), by code and
    basis."""
    readable: dict[str, list[dict]] = {}
    unreadable: dict[str, list[int]] = {}
    summaries: list[int] = []
    for page in doc.pages:
        if _is_summary(page.lines):
            if any(heading_code(ln) for ln in page.lines):
                summaries.append(page.number)
            continue
        lines = page.lines
        for idx, line in enumerate(lines):
            joined = line
            consumed = 1
            code = heading_code(line)
            if code is None and idx + 1 < len(lines):
                joined = f"{line} {lines[idx + 1]}"
                code = heading_code(joined)
                consumed = 2
            if code is None:
                continue
            basis = heading_basis(joined)
            if ANALYSIS_HEADING.search(_norm(_undouble(joined))):
                summaries.append(page.number)  # an analytical page carrying a statement title
                break
            if amount_lines(lines) >= AMOUNT_PAGE_MIN:
                readable.setdefault(code, []).append(
                    {
                        "page": page.number,
                        "basis": basis,
                        "heading": joined,
                        "amounts": amount_lines(lines),
                        "columns": len(detect_column_dates(lines[:HEADER_LINES])),
                    }
                )
            else:
                unreadable.setdefault(code, []).append(page.number)
            _ = consumed
            break
    return {"readable": readable, "unreadable": unreadable, "summaries_excluded": summaries}


def _prefer_statutory(entries: list[dict]) -> list[dict]:
    """A statutory statement has two period columns (current and comparative). Pages with more are analysis or
    history tables and are never selected; among two-column pages the statutory layout is preferred."""
    two = [e for e in entries if e["columns"] == 2]
    if two:
        return two
    return [e for e in entries if e["columns"] <= 2]


def _primary_run(entries: list[dict]) -> list[dict]:
    """Alternative presentations (horizontal and vertical) or stray mentions sit on separate page runs.
    Keep the one run with the most amounts, reduced to its first page, so a statement is never read twice."""
    if not entries:
        return entries
    runs: list[list[dict]] = [[entries[0]]]
    for e in entries[1:]:
        if e["page"] == runs[-1][-1]["page"] + 1:
            runs[-1].append(e)
        else:
            runs.append([e])
    best = max(runs, key=lambda r: sum(e["amounts"] for e in r))
    return best[:1]


def _choose_basis(entries: list[dict]) -> tuple[str | None, list[dict], bool]:
    """(basis, chosen entries, parallel) for one statement code."""
    labelled = {e["basis"] for e in entries if e["basis"]}
    if "consolidated" in labelled:
        chosen = [e for e in entries if e["basis"] == "consolidated"]
        return "consolidated", chosen, "unconsolidated" in labelled
    if "unconsolidated" in labelled:
        return "unconsolidated", [e for e in entries if e["basis"] == "unconsolidated"], False
    return None, entries, False


def detect_layout(doc: pe.DocumentText, period_end: str) -> dict:
    """Facts for one report: statement pages for one basis, unit, basis, columns and any blocker."""
    scan = _scan_statement_pages(doc)
    readable = {c: p for c, p in ((c, _prefer_statutory(e)) for c, e in scan["readable"].items()) if p}
    unreadable = scan["unreadable"]
    pages_with_amounts = sum(1 for p in doc.pages if amount_lines(p.lines) >= 1)
    base = {"summaries_excluded": scan["summaries_excluded"], "unreadable_pages": unreadable}
    if not readable and unreadable:
        return {
            **base,
            "blocker": "no_text_layer",
            "missing": ["statement bodies have no text layer"],
            "statement_pages": {},
        }
    if not readable and pages_with_amounts < DOC_AMOUNT_PAGES_MIN:
        return {
            **base,
            "blocker": "no_text_layer",
            "missing": [
                "no amount text in the report: statement bodies are drawn as vector outlines or images"
            ],
            "statement_pages": {},
        }
    if "BS" not in readable:
        return {
            **base,
            "blocker": "layout",
            "missing": ["no balance sheet found with its heading and amounts"],
            "statement_pages": {},
        }

    chosen_pages: dict[str, list[int]] = {}
    basis_of: dict[str, str | None] = {}
    parallel = False
    for code, entries in readable.items():
        basis, chosen, par = _choose_basis(entries)
        chosen = _primary_run(chosen) if chosen else chosen
        chosen_pages[code] = sorted({e["page"] for e in chosen})
        basis_of[code] = basis
        parallel = parallel or par
    labelled = {b for b in basis_of.values() if b}
    unstated_consolidated_mention = any(
        "consolidated" in _norm(e["heading"]) for entries in readable.values() for e in entries
    )
    flags: list[str] = []
    missing: list[str] = []
    if not labelled:
        if unstated_consolidated_mention:
            consolidation = None
            missing.append("consolidation basis ambiguous: 'consolidated' appears but no basis is labelled")
        else:
            consolidation = (
                "unconsolidated"  # STANDALONE: single set, no consolidated mention in the headings
            )
            flags.append("consolidation_basis_assumed")
    else:
        consolidation = "consolidated" if "consolidated" in labelled else "unconsolidated"
    if parallel:
        flags.append("parallel_sets_present")

    bs_page = chosen_pages["BS"][0]
    by_number = {p.number: p for p in doc.pages}
    bs_lines = by_number[bs_page].lines
    head = bs_lines[:HEADER_LINES]
    unit = detect_unit_scale(head) or detect_unit_scale(
        [
            ln
            for code in chosen_pages
            for n in chosen_pages[code][:1]
            for ln in by_number[n].lines[:HEADER_LINES]
        ]
    )
    currency = detect_currency(head)
    dates = detect_column_dates(head)
    if unit is None:
        missing.append("unit scale not stated in the balance sheet header")
    if currency is None:
        missing.append("currency not stated in the balance sheet header")
    if not dates:
        missing.append("no column dates in the balance sheet header")
    target = date.fromisoformat(period_end)
    matched = None
    if dates:
        if target in dates:
            matched = target
        else:
            same_md = [d for d in dates if (d.month, d.day) == (target.month, target.day)]
            if same_md:
                matched = same_md[0]
            else:
                matched = min(dates, key=lambda d: abs((d - target).days))
            flags.append("period_column_assumed")
    if matched is None and dates:
        missing.append(f"period end {period_end} could not be matched to a column")
    return {
        **base,
        "blocker": None if not missing else "layout",
        "unit_scale": unit,
        "consolidation": consolidation,
        "currency": currency,
        "columns": [d.isoformat() for d in dates],
        "period_column": matched.isoformat() if matched else None,
        "statement_pages": chosen_pages,
        "basis_by_statement": basis_of,
        "flags": flags,
        "missing": missing,
    }
