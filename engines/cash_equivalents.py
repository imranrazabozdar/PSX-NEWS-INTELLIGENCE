"""Cash and cash equivalents: note 41 and the reconciliation to the balance sheet and the cash flow.

Pure functions. The balance-sheet cash line and the cash-flow closing balance come from the statements;
note 41
supplies the split. A difference is explained only by a printed component; anything that is not printed is
reported as not explained, never as zero.

IAS 7.7: a cash equivalent is a short-term, highly liquid investment with an original maturity of three months
or less. Note 41 includes term deposits in cash equivalents. Note 26.1 prints their maturities; when those are
longer than three months the classification cannot be confirmed from the disclosure, and the reconciliation
says so.
"""

from __future__ import annotations

import re

from engines.trade_debts_note import _numbers

MONTH_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
MATURITY = re.compile(r"maturities up to (\w+) months?", re.IGNORECASE)


def parse_note_41(lines: list[str], *, pages: list[str]) -> dict:
    """The cash and cash equivalents note (OGDC note 41; LUCK note 36.2).

    Each row is read from its last two figures (current year, prior year); the note reference printed
    before them
    is dropped. The short-term row is kept under "short_term_investments": it is called term deposits in
    one report
    and short-term investments in another, and it is the same line."""
    start = None
    for i, ln in enumerate(lines):
        if re.search(r"CASH AND CASH EQUIVALENTS\s*$", ln.strip()):
            start = i
            break
    if start is None:
        return {"status": "not_found", "reason": "note 41 heading not in the supplied text", "pages": pages}
    rows: dict[str, dict] = {}
    for ln in lines[start : start + 12]:
        s = ln.strip()
        for key, pat in (
            ("cash_and_bank_balances", r"^Cash and bank balances\b"),
            (
                "short_term_investments",
                r"^(?:Short[- ]term highly liquid investments\s*-\s*Term deposits"
                r"|Short[- ]term investments)\b",
            ),
        ):
            if key not in rows and re.match(pat, s, re.I):
                vals = _numbers(s[re.match(pat, s, re.I).end() :])
                if len(vals) >= 2:
                    rows[key] = {"note": _note_ref(s, pat), "2026": vals[-2], "2025": vals[-1]}
        if "total" not in rows and re.match(r"^[\d(,]", s):
            vals = _numbers(s)
            if len(vals) == 2 and "cash_and_bank_balances" in rows:
                rows["total"] = {"2026": vals[0], "2025": vals[1]}
    if not {"cash_and_bank_balances", "short_term_investments", "total"} <= set(rows):
        return {"status": "incomplete", "found": sorted(rows), "pages": pages}
    checks = []
    for year in ("2026", "2025"):
        s = rows["cash_and_bank_balances"][year] + rows["short_term_investments"][year]
        checks.append(
            {
                "check": f"note41_total_{year}",
                "status": "RECONCILED" if s == rows["total"][year] else "UNRECONCILED",
                "detail": f"{s} vs printed {rows['total'][year]}",
            }
        )
    return {"status": "parsed", "units": "PKR '000", "pages": pages, "rows": rows, "checks": checks}


def _note_ref(s: str, pat: str) -> str | None:
    m = re.search(r"\b(\d{1,2})\s+[\d(]", s[re.match(pat, s, re.I).end() :])
    return m.group(1) if m else None


def maturity_terms(lines: list[str], *, pages: list[str]) -> dict:
    """The maturity wording printed for the term deposits (note 26.1)."""
    text = re.sub(r"\s+", " ", " ".join(lines))
    m = MATURITY.search(text)
    if not m:
        return {"status": "not_found", "max_maturity_months": None, "pages": pages}
    months = MONTH_WORDS.get(m.group(1).lower()) or (int(m.group(1)) if m.group(1).isdigit() else None)
    return {"status": "parsed", "printed": m.group(0), "max_maturity_months": months, "pages": pages}


def reconcile_cash(*, bs_cash: float | None, cf_closing: float | None, note41: dict, maturity: dict) -> dict:
    """Balance-sheet cash to cash-flow closing cash, through note 41. The difference must be exactly the
    printed
    term deposits; otherwise it is reported as not explained."""
    if bs_cash is None or cf_closing is None or note41.get("status") != "parsed":
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "balance-sheet cash, cash-flow closing or note 41 missing",
        }
    tdr = note41["rows"]["short_term_investments"]["2026"]
    cash_and_bank = note41["rows"]["cash_and_bank_balances"]["2026"]
    difference = cf_closing - bs_cash
    residual = difference - tdr
    months = maturity.get("max_maturity_months")
    if months is None:
        iias7 = "NOT_VERIFIABLE: maturity wording not found"
    elif months > 3:
        iias7 = (
            f"NOT_VERIFIABLE_FROM_DISCLOSURE: term deposits printed with maturities up to {months} months; "
            "IAS 7.7 requires original maturity of three months or less. The qualifying part cannot be "
            "split out from the disclosure."
        )
    else:
        iias7 = "CONSISTENT: printed maturities are within three months"
    return {
        "status": "EXPLAINED" if residual == 0 else "NOT_EXPLAINED",
        "balance_sheet_cash_and_bank": bs_cash,
        "note41_cash_and_bank": cash_and_bank,
        "cash_flow_closing": cf_closing,
        "difference_cf_minus_bs": difference,
        "explained_by_note41_short_term": tdr,
        "residual": residual,
        "note41_total_equals_cash_flow_closing": note41["rows"]["total"]["2026"] == cf_closing,
        "ias7_cash_equivalent_test": iias7,
        "maturity_wording": maturity.get("printed"),
    }
