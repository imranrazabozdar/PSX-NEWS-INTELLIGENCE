"""Deterministic disclosure-note extraction: receivables (incl. ageing), borrowings, payables, contingencies,
and segments.

Method (no guessing):
  * A note starts at a numbered heading ("12. Trade debts", "Note 12 Borrowings"). A repeated heading marked
    "(continued)" on a later page continues the same note; it does not start a new one.
  * Lines inside a note are parsed by the statement-line parser (brackets negative, dashes not reported).
  * A canonical code is given only by an explicit rule. Every other line is KEPT with no code.
  * Missing amounts are never stored as zero.
  * Contingent figures are partitioned: every contingency record carries recognised=False and never maps to a
    balance-sheet code.
"""

from __future__ import annotations

import re

from engines import financials as fin

EXTRACTOR_RULE_VERSION = "notes-rules-2026.11.2"
_TITLE = r"([A-Za-z][A-Za-z ,&()/'\-]{2,80})"
HEADING_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[\.\)\-:]\s*" + _TITLE + r"\s*$")
HEADING_NOTE = re.compile(r"^\s*note\s+(\d{1,2})\s*[\.\)\-:]?\s*" + _TITLE + r"\s*$", re.IGNORECASE)
CONTINUED = re.compile(r"\s*\(?\s*continued\s*\)?\s*$", re.IGNORECASE)

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

# ---- receivables ageing and disputes
_NOT_DUE = re.compile(r"not\s+(?:yet\s+)?(?:past\s+)?due|neither\s+past\s+due|\bcurrent\b", re.I)
_RANGE = re.compile(r"(\d{1,4})\s*(?:-|–|—|to)\s*(\d{1,4})\s*days?", re.I)
_LESS = re.compile(r"(?:less\s+than|up\s+to|within)\s+(\d{1,4})\s*days?", re.I)
_OVER = re.compile(r"(?:over|more\s+than|above|exceeding|beyond)\s+(\d{1,4})\s*days?|>\s*(\d{1,4})", re.I)
_DISPUTED = re.compile(r"\bundisputed\b", re.I)
_DISPUTED_ONLY = re.compile(r"(?<!un)disputed", re.I)


def classify_ageing(label: str) -> dict | None:
    """The ageing bracket a row describes, or None.

    Brackets keep their own label; the bucket is derived from it.
    """
    lab = label.strip()
    if _DISPUTED_ONLY.search(lab) and not _DISPUTED.search(lab) and not _RANGE.search(lab):
        return {"role": "disputed_status", "bucket": None, "lower_days": None, "disputed": "disputed"}
    if _DISPUTED.search(lab) and not _RANGE.search(lab) and not _OVER.search(lab):
        return {"role": "disputed_status", "bucket": None, "lower_days": None, "disputed": "undisputed"}
    if _NOT_DUE.search(lab):
        return {"role": "bracket", "bucket": "not_due", "lower_days": 0, "disputed": None}
    m = _RANGE.search(lab)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return {"role": "bracket", "bucket": f"{a}-{b}", "lower_days": a, "disputed": None}
    m = _LESS.search(lab)
    if m:
        b = int(m.group(1))
        return {"role": "bracket", "bucket": f"0-{b}", "lower_days": 0, "disputed": None}
    m = _OVER.search(lab)
    if m:
        n = int(m.group(1) or m.group(2))
        return {"role": "bracket", "bucket": f">{n}", "lower_days": n + 1, "disputed": None}
    return None


# ---- contingencies: partitioned from balance-sheet liabilities
CONTINGENCY_TYPES = [
    (
        "tax",
        re.compile(
            r"income\s+tax|sales\s+tax|federal\s+excise|customs|\bPRA\b|\bSRB\b|\bWWF\b|"
            r"workers.?\s+welfare|\btax\b",
            re.I,
        ),
    ),
    ("guarantee", re.compile(r"guarantee|letters?\s+of\s+credit|\bL/C\b", re.I)),
    ("commitment", re.compile(r"commitment|capital\s+expenditure|contractual|purchase\s+obligation", re.I)),
    (
        "litigation",
        re.compile(
            r"court|litigation|lawsuit|petition|arbitrat|suit\s+filed|claim|regulat|"
            r"\bNEPRA\b|\bOGRA\b|\bSECP\b|\bPSX\b|\bSBP\b",
            re.I,
        ),
    ),
]


def classify_contingency(text: str) -> str:
    for kind, pat in CONTINGENCY_TYPES:
        if pat.search(text):
            return kind
    return "other"


def _heading(line: str) -> tuple[str, str, bool] | None:
    """(note number, title, is_continuation) for a note heading, else None."""
    m = HEADING_NOTE.match(line) or HEADING_NUMBERED.match(line)
    if not m:
        return None
    title = m.group(2).strip()
    continued = bool(CONTINUED.search(title))
    title = CONTINUED.sub("", title).strip()
    return (m.group(1), title, continued) if title else None


def _category_for_title(title: str) -> str | None:
    t = title.lower()
    for cat, keys in CATEGORIES.items():
        if any(k in t for k in keys):
            return cat
    return None


def canonical_for(category: str, label: str) -> tuple[str | None, float | None]:
    lab = fin.normalise_label(label)
    if category == "trade_receivables":
        ag = classify_ageing(label)
        if ag and ag["role"] == "bracket":
            return "receivable_ageing_bracket", 0.7
        if ag and ag["role"] == "disputed_status":
            return ("receivable_disputed" if ag["disputed"] == "disputed" else "receivable_undisputed"), 0.7
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
                note_no, title, continued = h
                cat = _category_for_title(title)
                if continued and current is not None and current[0] == note_no:
                    continue  # the same note carried onto a new page
                current = (note_no, title, cat, pg.number) if cat else None
                if cat:
                    notes.append({"note_no": note_no, "title": title, "category": cat, "page": pg.number})
                continue
            if current is None:
                continue
            parsed = fin.parse_statement_text(raw, statement="NOTE", columns=columns, page=pg.number)
            unparsed.extend({**u, "note_no": current[0], "category": current[2]} for u in parsed["unparsed"])
            if not parsed["lines"] and current[2] == "contingencies" and raw.strip():
                line_counter += 1
                lines.append(_narrative(raw, pg.number, current, line_counter, columns))
                continue
            label_rows = {}
            for rec in parsed["lines"]:
                label_rows.setdefault(rec["raw_label"], []).append(rec)
            for label, recs in label_rows.items():
                code, conf = canonical_for(current[2], label)
                ag = classify_ageing(label) if current[2] == "trade_receivables" else None
                line_counter += 1
                for rec in recs:
                    row = {
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
                        "bucket": ag["bucket"] if ag else None,
                        "disputed": ag["disputed"] if ag else None,
                        "lower_days": ag["lower_days"] if ag else None,
                    }
                    if current[2] == "contingencies":
                        row["contingency_type"] = classify_contingency(label)
                        row["recognised"] = False
                    lines.append(row)
    return {"lines": lines, "notes": notes, "unparsed": unparsed}


def _narrative(raw: str, page: int, current: tuple, line_no: int, columns: list[str]) -> dict:
    """Narrative contingency wording: no figure, kept with an exact excerpt.

    Never recognised on the balance sheet.
    """
    text = raw.strip()
    return {
        "statement": "NOTE",
        "line_no": line_no,
        "raw_label": "narrative",
        "column_period_end": columns[0],
        "value": None,
        "page": page,
        "note_ref": current[0],
        "note_title": current[1],
        "category": "contingencies",
        "canonical_code": None,
        "confidence": None,
        "extraction_method": "pdf_text",
        "extractor_version": EXTRACTOR_RULE_VERSION,
        "bucket": None,
        "disputed": None,
        "contingency_type": classify_contingency(text),
        "recognised": False,
        "excerpt": text[:300],
        "narrative": True,
    }


def summary_by_category(result: dict) -> dict[str, dict]:
    """Per category: note, line, mapped and unmapped counts. Unmapped lines are counted, not dropped."""
    out: dict[str, dict] = {}
    for n in result["notes"]:
        out.setdefault(n["category"], {"notes": 0, "lines": 0, "mapped": 0, "unmapped": 0})["notes"] += 1
    for ln in result["lines"]:
        s = out.setdefault(ln["category"], {"notes": 0, "lines": 0, "mapped": 0, "unmapped": 0})
        s["lines"] += 1
        s["mapped" if ln["canonical_code"] else "unmapped"] += 1
    return out


# ---- receivables quality (pure, from the extracted lines of one column)
def receivables_quality(result: dict, column: str) -> dict:
    """Ageing ratios from extracted trade-debt rows.

    A ratio is None when a needed amount is missing; it is never zero.
    Brackets whose label is not recognised are reported in `unclassified_brackets`, not dropped or guessed."""
    rows = [
        r
        for r in result["lines"]
        if r["category"] == "trade_receivables"
        and r["column_period_end"] == column
        and not r.get("narrative")
    ]
    gross = next((r["value"] for r in rows if r["canonical_code"] == "trade_receivables_gross"), None)
    net = next((r["value"] for r in rows if r["canonical_code"] == "trade_receivables_net"), None)
    ecl = next((r["value"] for r in rows if r["canonical_code"] == "ecl_allowance"), None)
    brackets = [r for r in rows if r["canonical_code"] == "receivable_ageing_bracket"]
    unclassified = [
        r["raw_label"]
        for r in rows
        if r["category"] == "trade_receivables"
        and r["canonical_code"] is None
        and classify_ageing(r["raw_label"]) is None
        and "trade" not in r["raw_label"].lower()
        and "expected" not in r["raw_label"].lower()
    ]
    by_bucket = {}
    for r in brackets:
        if r["value"] is not None:
            by_bucket[r["bucket"]] = by_bucket.get(r["bucket"], 0.0) + r["value"]
    missing_bracket_values = [r["raw_label"] for r in brackets if r["value"] is None]
    overdue_keys = [b for b in by_bucket if b != "not_due"]
    over90_keys = [
        r["bucket"]
        for r in brackets
        if r["bucket"] != "not_due" and (r["lower_days"] or 0) >= 91 and r["value"] is not None
    ]
    over90_keys = list(dict.fromkeys(over90_keys))
    total_brackets = sum(by_bucket.values()) if by_bucket else None

    def ratio(num, den):
        if num is None or not den:
            return None
        return num / den

    overdue_total = sum(by_bucket[k] for k in overdue_keys) if overdue_keys else None  # absent, not zero
    over90_total = sum(by_bucket[k] for k in over90_keys) if over90_keys else (0.0 if by_bucket else None)
    ecl_cov = abs(ecl) / gross if (ecl is not None and gross) else None
    return {
        "column": column,
        "gross_trade_debts": gross,
        "ecl_allowance": ecl,
        "net_trade_debts_reported": net,
        "net_trade_debts_computed": (gross + ecl) if (gross is not None and ecl is not None) else None,
        "net_check": (
            None
            if None in (net, gross, ecl)
            else ("match" if abs(net - (gross + ecl)) <= 1.0 else "difference")
        ),
        "ageing_brackets": by_bucket,
        "bracket_total": total_brackets,
        "missing_bracket_values": missing_bracket_values,
        "unclassified_brackets": unclassified,
        "overdue_percentage": ratio(overdue_total, gross),
        "overdue_over_90_ratio": ratio(over90_total, gross),
        "ecl_coverage_ratio": ecl_cov,
        "disputed": [
            {"status": r["disputed"], "raw_label": r["raw_label"], "value": r["value"], "page": r["page"]}
            for r in rows
            if r["canonical_code"] in ("receivable_disputed", "receivable_undisputed")
        ],
    }


def contingency_summary(result: dict, column: str) -> dict:
    """Contingent items by type. Amounts are contingent exposures, never recognised liabilities."""
    rows = [
        r
        for r in result["lines"]
        if r["category"] == "contingencies" and not r.get("narrative") and r["column_period_end"] == column
    ]
    narrative = [r for r in result["lines"] if r["category"] == "contingencies" and r.get("narrative")]
    by_type: dict[str, dict] = {}
    for r in rows:
        t = by_type.setdefault(r["contingency_type"], {"items": [], "total_reported": 0.0, "missing": 0})
        if r["value"] is None:
            t["missing"] += 1
        else:
            t["total_reported"] += r["value"]
        t["items"].append(
            {"label": r["raw_label"], "value": r["value"], "page": r["page"], "note_ref": r["note_ref"]}
        )
    for n in narrative:
        t = by_type.setdefault(n["contingency_type"], {"items": [], "total_reported": 0.0, "missing": 0})
        t["items"].append(
            {"label": "narrative", "excerpt": n["excerpt"], "page": n["page"], "note_ref": n["note_ref"]}
        )
    return {"recognised_on_balance_sheet": False, "by_type": by_type}
