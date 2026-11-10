"""Deterministic extraction of disclosure notes: receivables, borrowings, payables, contingencies, segments.

Method (no guessing):
  * A note starts at a numbered heading ("12. Trade debts", "Note 12 Borrowings") whose title matches a
    category.
  * Lines inside that note are parsed by the existing statement-line parser: label, period column, amount,
    brackets as negatives, dashes as not reported. Each record keeps its page and note number.
  * A canonical code is given only when a label rule matches explicitly. Every other line is KEPT with
    canonical_code None. Nothing is discarded because it is unmapped.
  * Missing amounts are not reported; they are never zero.

Output lines use statement "NOTE" and the same evidence fields as statement lines
(see statement_pipeline.tag).
"""

from __future__ import annotations

import re

from engines import financials as fin

EXTRACTOR_RULE_VERSION = "notes-rules-2026.11.1"
_TITLE = r"([A-Za-z][A-Za-z ,&()/'\-]{2,80})"
HEADING_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[\.\)\-:]\s*" + _TITLE + r"\s*$")
HEADING_NOTE = re.compile(r"^\s*note\s+(\d{1,2})\s*[\.\)\-:]?\s*" + _TITLE + r"\s*$", re.IGNORECASE)


def _heading(line: str) -> tuple[str, str] | None:
    """(note number, title) for a note heading, else None. Accepts '12. Title' and 'Note 12 Title'."""
    m = HEADING_NOTE.match(line) or HEADING_NUMBERED.match(line)
    return (m.group(1), m.group(2).strip()) if m else None


CATEGORIES = {
    "trade_receivables": ("trade debts", "trade receivables", "receivables", "debtors"),
    "borrowings": ("borrowings", "long term financing", "short term borrowings", "financing", "loans"),
    "trade_payables": (
        "trade and other payables",
        "trade payables",
        "creditors",
        "accrued liabilities",
        "payables",
    ),
    "contingencies": ("contingencies", "commitments", "contingent liabilities"),
    "segment_reporting": ("segment reporting", "segment information", "segments"),
}

# (category, lowercase substring of the label, canonical code, confidence). First match wins.
LABEL_RULES = [
    ("trade_receivables", "net trade", "trade_receivables_net", 0.8),
    ("trade_receivables", "expected credit loss", "ecl_allowance", 0.8),
    ("trade_receivables", "doubtful", "ecl_allowance", 0.8),
    ("trade_receivables", "impairment allowance", "ecl_allowance", 0.8),
    ("trade_receivables", "trade debts", "trade_receivables_gross", 0.8),
    ("trade_receivables", "trade receivables", "trade_receivables_gross", 0.8),
    ("borrowings", "current portion", "current_portion_of_long_term_debt", 0.8),
    ("borrowings", "long term", "long_term_borrowings", 0.8),
    ("borrowings", "short term", "short_term_borrowings", 0.8),
    ("borrowings", "finance cost", "finance_cost", 0.8),
    ("borrowings", "markup", "finance_cost", 0.8),
    ("trade_payables", "trade payables", "trade_payables", 0.8),
    ("trade_payables", "trade and other payables", "trade_payables", 0.8),
    ("trade_payables", "accrued", "accrued_liabilities", 0.8),
    ("segment_reporting", "revenue", "segment_revenue", 0.7),
    ("segment_reporting", "operating profit", "segment_operating_profit", 0.7),
]


def _category_for_title(title: str) -> str | None:
    t = title.lower()
    for cat, keys in CATEGORIES.items():
        if any(k in t for k in keys):
            return cat
    return None


def canonical_for(category: str, label: str) -> tuple[str | None, float | None]:
    lab = fin.normalise_label(label)
    for cat, sub, code, conf in LABEL_RULES:
        if cat == category and sub in lab:
            return code, conf
    return None, None


def extract_notes(doc, *, columns: list[str]) -> dict:
    """Walk the document's pages. Returns categorised note lines, the notes found, and unparsed lines."""
    lines, notes, unparsed = [], [], []
    current = None  # (note_no, title, category, page)
    line_counter = 0
    for pg in doc.pages:
        if not pg.has_text:
            continue
        for raw in pg.lines:
            h = _heading(raw)
            if h:
                cat = _category_for_title(h[1])
                current = (h[0], h[1], cat, pg.number) if cat else None
                if cat:
                    notes.append({"note_no": h[0], "title": h[1], "category": cat, "page": pg.number})
                continue
            if current is None:
                continue
            parsed = fin.parse_statement_text(raw, statement="NOTE", columns=columns, page=pg.number)
            unparsed.extend({**u, "note_no": current[0], "category": current[2]} for u in parsed["unparsed"])
            label_rows = {}
            for rec in parsed["lines"]:
                label_rows.setdefault(rec["raw_label"], []).append(rec)
            for label, recs in label_rows.items():
                code, conf = canonical_for(current[2], label)
                line_counter += 1
                for rec in recs:
                    lines.append(
                        {
                            "statement": "NOTE",
                            "line_no": line_counter,
                            "raw_label": label,
                            "column_period_end": rec["column_period_end"],
                            "value": rec["value"],
                            "page": pg.number,
                            "note_ref": current[0],
                            "note_title": current[1],
                            "category": current[2],
                            "canonical_code": code,
                            "confidence": conf,
                            "extraction_method": "pdf_text",
                            "extractor_version": EXTRACTOR_RULE_VERSION,
                        }
                    )
    return {"lines": lines, "notes": notes, "unparsed": unparsed}


def summary_by_category(result: dict) -> dict[str, dict]:
    """Per category: note, line, mapped and unmapped counts.

    Unmapped lines are counted, not dropped.
    """
    out: dict[str, dict] = {}
    for n in result["notes"]:
        out.setdefault(n["category"], {"notes": 0, "lines": 0, "mapped": 0, "unmapped": 0})["notes"] += 1
    for ln in result["lines"]:
        s = out.setdefault(ln["category"], {"notes": 0, "lines": 0, "mapped": 0, "unmapped": 0})
        s["lines"] += 1
        s["mapped" if ln["canonical_code"] else "unmapped"] += 1
    return out
