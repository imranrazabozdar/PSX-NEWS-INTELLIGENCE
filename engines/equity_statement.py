"""Statement of changes in equity: the closing total for a period, read from the closing row.

The statement has component columns, not period columns, so the period-based parser does not read it.
Its closing total ("Balance as at <period end>") is checked against the balance sheet's total equity
(a cross-statement identity). Pure functions.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?|(?<![\w])[–-](?![\w])")
_DATE_FORMS = {
    "2025-12-31": ("December 31, 2025", "31 December 2025"),
    "2026-06-30": ("June 30, 2026", "30 June 2026"),
    "2025-06-30": ("June 30, 2025", "30 June 2025"),
}


def _value(token: str) -> float:
    if token in ("–", "-"):
        return 0.0
    neg = token.startswith("(") and token.endswith(")")
    value = float(token.strip("()-").replace(",", ""))
    return -value if neg else value


def closing_total(lines: list[str], period_end: str) -> dict | None:
    """The total of the last "Balance as at <period end>" row, or None when no such row or no figure is on it.
    The total is the last figure on the row; the row's text is returned for evidence."""
    forms = _DATE_FORMS.get(period_end)
    if not forms:
        return None
    hit = None
    for ln in lines:
        text = " ".join(ln.split())
        if "balance as at" in text.lower() and any(f in text for f in forms):
            hit = text
    if hit is None:
        return None
    figures = _NUMBER.findall(hit)
    if not figures:
        return None
    return {"total": _value(figures[-1]), "row": hit}
