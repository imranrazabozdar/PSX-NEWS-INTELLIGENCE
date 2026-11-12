"""Identity checks on coordinate-read statements.

Covers column roles, total equity without circularity, A=L+E and PBT-tax=PAT.

Rules:
* Column roles come from the HEADER: a period group word ("Quarter", "Halfyear", "Nine months", "Year")
  sits over its value columns. Within a group the leftmost column is the current period (the year printed
  first). A group that cannot be matched to a band is UNRESOLVED.
* Total equity is NEVER assets minus liabilities. It is sourced independently from the balance sheet's
  equity components (share capital, reserves, surplus, retained profit) and, when printed, the equity
  subtotal. Both present and agreeing within rounding is a real cross-check; one source is accepted with
  a flag; neither is requires_review.
* A=L+E and PBT-tax=PAT are evaluated only on resolved columns. Rounding tolerance is one unit of the
  printed scale.
* A row that carries an ambiguity still blocks: nothing is resolved on it.
"""

from __future__ import annotations

import re

from engines import layout_words as lw

TOLERANCE = 1  # one unit of the printed scale (values are printed in thousands)
GROUPS = {
    "quarter": "quarter",
    "halfyear": "half_year",
    "half year": "half_year",
    "six months": "half_year",
    "nine months": "nine_months",
    "year": "year",
}
_EQUITY_COMPONENT = re.compile(
    r"sharecapital|reserve|surplus|unappropriated|retainedearnings|accumulatedprofit"
)


def _letters(label: str) -> str:
    return re.sub(r"[^a-z]", "", label.lower())


def period_group_columns(header_words: list[lw.Word], columns: list[tuple[float, int]]) -> dict[int, dict]:
    """Assign each value band to its period group and role.

    Returns {band index: {group, role}}. A band whose group cannot be found in the header is absent from the
    result (unresolved)."""
    markers: list[tuple[float, str]] = []
    texts = [w.text.lower() for w in header_words]
    for i, w in enumerate(header_words):
        t = w.text.lower()
        if t == "quarter" or t.startswith("quarter"):
            markers.append((w.x1, "quarter"))
        elif t.startswith("halfyear") or t == "half":
            markers.append((w.x1, "half_year"))
        elif t == "nine" and i + 1 < len(texts) and texts[i + 1].startswith("month"):
            markers.append((w.x1, "nine_months"))
    if not markers:
        return {}
    out: dict[int, dict] = {}
    bands = [c for c, _ in columns]
    for idx, centre in enumerate(bands):
        nearest = min(markers, key=lambda m: abs(m[0] - centre))
        if abs(nearest[0] - centre) > 90:
            continue  # the header does not reach this band
        out[idx] = {"group": nearest[1]}
    # within each group the leftmost band is current, the next is prior
    for group in {v["group"] for v in out.values()}:
        members = sorted(i for i, v in out.items() if v["group"] == group)
        for rank, i in enumerate(members):
            out[i]["role"] = "current" if rank == 0 else "prior"
    return out


def total_equity(rows: list[lw.Row], band: int, soce: float | None = None) -> dict:
    """Equity from sources that do not use assets or liabilities: the balance-sheet components, the printed
    subtotal, and the Statement of Changes in Equity closing balance (passed in as `soce`)."""
    components, printed = [], None
    for r in rows:
        if band not in r.cells:
            continue
        value = _to_number(r.cells[band][0])
        key = _letters(r.label)
        if "liabilities" in key:
            continue
        if _EQUITY_COMPONENT.search(key) and "total" not in key:
            components.append((r.label, value))
        elif ("totalequity" in key or "sharecapitalandreserves" in key) and "liabilities" not in key:
            printed = value
    comp_sum = sum(v for _, v in components) if components else None
    if soce is not None and comp_sum is not None:
        agree = abs(comp_sum - soce) <= TOLERANCE
        return {
            "source": "both_agree" if agree else "disagree",
            "value": soce if agree else None,
            "components": comp_sum,
            "printed": soce,
            "soce": soce,
        }
    if soce is not None:
        return {"source": "soce_only", "value": soce, "components": None, "printed": None, "soce": soce}
    if comp_sum is not None and printed is not None:
        agree = abs(comp_sum - printed) <= TOLERANCE
        return {
            "source": "both_agree" if agree else "disagree",
            "value": printed if agree else None,
            "components": comp_sum,
            "printed": printed,
        }
    if comp_sum is not None:
        return {"source": "components_only", "value": comp_sum, "components": comp_sum, "printed": None}
    if printed is not None:
        return {"source": "printed_only", "value": printed, "components": None, "printed": printed}
    return {"source": "none", "value": None, "components": None, "printed": None}


def soce_closing_equity(rows: list[lw.Row], band: int) -> float | None:
    """The closing total-equity balance at the foot of the Statement of Changes in Equity.

    The row labelled as a closing balance. Used as an independent source; never derived from assets or
    liabilities."""
    for r in rows:
        key = _letters(r.label)
        if band in r.cells and ("closingbalance" in key or "balanceasat" in key or "balanceas" in key):
            return _to_number(r.cells[band][0])
    return None


def _to_number(text: str) -> float | None:
    t = text.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _row_value(rows: list[lw.Row], band: int, predicate) -> float | None:
    for r in rows:
        if band in r.cells and predicate(_letters(r.label)):
            return _to_number(r.cells[band][0])
    return None


def balance_identity(rows: list[lw.Row], band: int, soce_rows: list[lw.Row] | None = None) -> dict:
    assets = _row_value(rows, band, lambda k: k.startswith("totalassets"))
    liabilities = _row_value(rows, band, lambda k: "totalliabilities" in k and "equity" not in k)
    soce = soce_closing_equity(soce_rows, band) if soce_rows else None
    equity = total_equity(rows, band, soce=soce)
    if equity["source"] in ("none", "disagree"):
        # neither independent source is available, or the two disagree: never resolved on one figure
        return {
            "status": "requires_review",
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "flag": f"equity source {equity['source']}",
        }
    if assets is None or liabilities is None:
        return {"status": "insufficient_data", "assets": assets, "liabilities": liabilities, "equity": equity}
    delta = assets - (liabilities + equity["value"])
    status = "reconciled" if abs(delta) <= TOLERANCE else "unreconciled"
    flag = None if equity["source"] == "both_agree" else f"equity from {equity['source']}"
    return {
        "status": status,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "delta": delta,
        "flag": flag,
    }


def tax_identity(rows: list[lw.Row], band: int) -> dict:
    pbt = _row_value(
        rows, band, lambda k: "beforeincometax" in k or ("beforetaxation" in k and "levies" not in k)
    )
    tax = _row_value(rows, band, lambda k: k.startswith("taxation") or k.startswith("taxa"))
    pat = _row_value(rows, band, lambda k: "aftertaxation" in k or "aftertax" in k)
    if pbt is None or tax is None or pat is None:
        return {"status": "insufficient_data", "pbt": pbt, "tax": tax, "pat": pat}
    delta = pbt + tax - pat
    return {
        "status": "reconciled" if abs(delta) <= TOLERANCE else "unreconciled",
        "pbt": pbt,
        "tax": tax,
        "pat": pat,
        "delta": delta,
    }
