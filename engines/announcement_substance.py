"""How substantial is an announcement? Read from the facts, never guessed. Deterministic, no model.

For every announcement fact (`announcements.<label>`), this reads the quantities stated in its text (a stake
percentage, a rupee amount) and sets them against the company's own size (market capitalisation on file),
then reports a size band WITH the numbers behind it. Where the text states no quantity, the result says
"unquantified" instead of pretending to know: a headline such as "significant discovery" gets no
invented size.

Size bands are plain ratios, set in one place below so the owner can change them. They are not calibrated to
outcomes. Nothing here says whether the news is good or bad, or where the price will go.

Roles matter for a deal: "IGI Investments intends to acquire up to 60% of Nimir Resins" is a control event for
the TARGET (Nimir Resins) and says nothing about IGI's own size. The stake is only graded for a company the
text shows to be the target; for any other company the result is "unquantified".
"""

from __future__ import annotations

import re
from typing import Any

# amount / market cap bands, and stake bands (share of the target's ordinary shares)
AMOUNT_BANDS = ((0.10, "major"), (0.03, "significant"), (0.01, "moderate"))
STAKE_BANDS = ((50.0, "major"), (25.0, "significant"), (10.0, "moderate"))
POINTS = {"major": 25.0, "significant": 18.0, "moderate": 10.0, "minor": 5.0, "unquantified": 8.0}
SCHEDULED_POINTS = 3.0

MATERIAL_LABELS = {
    "Material Disclosure",
    "Management Change",
    "Financing / Restructuring",
    "M&A / Public Offer",
    "Legal / Regulatory",
    "Capacity / Shutdown",
    "Operations Update",
    "Unusual Movement Reply",
    "Share Buyback",
    "Share Split",
    "Credit Rating",
    "Scheme / Arrangement",
    "Rights / Bonus",
    "Corporate Action",
}
DEAL_LABELS = {"M&A / Public Offer", "Scheme / Arrangement"}
_UNITS = {
    "trillion": 1e12,
    "tn": 1e12,
    "t": 1e12,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mn": 1e6,
    "m": 1e6,
    "crore": 1e7,
    "cr": 1e7,
    "lac": 1e5,
    "lakh": 1e5,
}
_PKR = re.compile(
    r"(?:Rs\.?|PKR|Rupees)\s?([\d,]+(?:\.\d+)?)\s?(trillion|billion|million|crore|lakh|lac|tn|bn|mn|cr|b|m)?\b",
    re.I,
)
_USD = re.compile(r"(?:USD|US\$|\$)\s?([\d,]+(?:\.\d+)?)\s?(billion|million|bn|mn|b|m)?\b", re.I)
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?(?:%|pc\b|per\s?cent)", re.I)
_MCAP = re.compile(r"Market Cap:\s*Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(T|B|M)\b", re.I)
_PER_SHARE = re.compile(r"^\s*(?:per\s+(?:ordinary\s+)?share|/share|a share|each)", re.I)
_TARGET = re.compile(
    r"\b(?:acquire|acquisition of|purchase of|purchase|stake in|sell|sale of|divest)\b", re.I
)


def market_cap(facts: list[dict[str, Any]]) -> float | None:
    """The newest 'Market Cap: Rs. 885.19B' fact, in rupees."""
    rows = [f for f in facts if f.get("topic") == "fundamentals.market_cap"]
    for f in sorted(rows, key=lambda f: str(f.get("source_date")), reverse=True):
        m = _MCAP.search(str(f.get("fact_text", "")))
        if m:
            return float(m.group(1).replace(",", "")) * {"T": 1e12, "B": 1e9, "M": 1e6}[m.group(2).upper()]
    return None


def rupee_amounts(text: str) -> list[float]:
    """Rupee amounts that state a size. A bare 'Rs 5 per share' is a per-share figure, not a size."""
    out = []
    for m in _PKR.finditer(text):
        unit = (m.group(2) or "").lower()
        if not unit and _PER_SHARE.match(text[m.end() :]):
            continue
        value = float(m.group(1).replace(",", ""))
        if unit:
            out.append(value * _UNITS[unit])
        elif value >= 1e6:
            out.append(value)
    return out


def usd_amounts(text: str) -> list[float]:
    out = []
    for m in _USD.finditer(text):
        unit = (m.group(2) or "").lower()
        if unit:
            out.append(float(m.group(1).replace(",", "")) * _UNITS[unit])
    return out


def stake_percent(text: str) -> float | None:
    values = [float(p) for p in _PCT.findall(text) if 0 < float(p) <= 100]
    return max(values) if values else None


_SELL = re.compile(r"\b(?:sell|sale of|divest)\b", re.I)
_BUY = re.compile(r"\b(?:acquire|acquisition of|purchase of|purchase|stake in)\b", re.I)


def _is_target(text: str, names: list[str]) -> bool:
    """True when the company is the one whose shares change hands.

    'X intends to acquire up to 60% of Y': Y, named after the verb, is the target.
    'Y's controlling shareholders agree to sell 51% stake to X': Y, named before the verb, is the target."""
    lowered = text.lower()
    usable = [n.lower() for n in names if len(n) >= 4]
    sell, buy = _SELL.search(text), _BUY.search(text)
    if sell and any(n in lowered[: sell.start()] for n in usable):
        return True
    if buy and any(n in lowered[buy.end() :] for n in usable):
        return True
    return False


def _band(value: float, bands: tuple[tuple[float, str], ...]) -> str:
    for floor, name in bands:
        if value >= floor:
            return name
    return "minor"


def assess(label: str, text: str, *, company_names: list[str], mcap: float | None) -> dict[str, Any]:
    """Size band and the numbers behind it for one announcement. `text` is the stored fact text."""
    body = text.split(": ", 1)[1] if ": " in text[:14] else text
    basis: list[str] = []
    if label not in MATERIAL_LABELS:
        return {"tier": "routine", "points": SCHEDULED_POINTS, "quantified": False, "basis": []}
    pct = stake_percent(body)
    if label in DEAL_LABELS and pct is not None:
        if _is_target(body, company_names):
            tier = _band(pct, STAKE_BANDS)
            basis.append(f"stake of {pct:g}% of the company's shares is the subject of the deal")
            if pct >= 50:
                basis.append("above 50%: a change of control if completed")
            return {"tier": tier, "points": POINTS[tier], "quantified": True, "basis": basis}
        basis.append(f"stake of {pct:g}% found, but this company is not shown to be the target")
        return {"tier": "unquantified", "points": POINTS["unquantified"], "quantified": False, "basis": basis}
    amounts = rupee_amounts(body)
    if amounts and mcap:
        top = max(amounts)
        ratio = top / mcap
        tier = _band(ratio, AMOUNT_BANDS)
        basis.append(f"amount Rs {top / 1e9:.2f}bn is {ratio * 100:.1f}% of market cap Rs {mcap / 1e9:.1f}bn")
        return {"tier": tier, "points": POINTS[tier], "quantified": True, "basis": basis}
    if amounts:
        basis.append(f"amount Rs {max(amounts) / 1e9:.2f}bn stated, company size not on file")
    elif usd_amounts(body):
        basis.append(
            f"a US dollar amount (${max(usd_amounts()) if False else max(usd_amounts(body)) / 1e6:.0f}m) "
            "is stated but not converted"
        )
    else:
        basis.append("no quantity stated in the announcement text")
    return {"tier": "unquantified", "points": POINTS["unquantified"], "quantified": False, "basis": basis}
