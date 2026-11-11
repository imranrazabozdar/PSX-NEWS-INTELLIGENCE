"""Financial figures from PSX statutory earnings declarations (PUCAR letterheads, 1 to 3 pages).

Standard library only. The input is the raw text of one declaration (for example text extracted from a
PDF stream, or a text fixture). Nothing here reads a file, opens a URL or calls a PDF library.

Conventions
* Figures are returned exactly as printed, in the units the document prints (usually PKR thousands). A
  warning says so when the text states the units. Nothing is rescaled.
* Brackets mean negative: "(1,234,567)" -> -1234567.0. A cost printed in brackets is therefore negative.
* A dash or "nil" printed as a value is 0.0. A figure that is not printed at all is None.
* The first figure on a row is the current period. Statements with several columns print the current
  quarter first. A leading 1-2 digit note reference before three or more figures is dropped.
* The symbol is an argument, never guessed from the text.
* Only the labels listed in _classify() are read. An unrecognised label is ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

_DASH_VALUES = frozenset({"-", "—", "–", "nil"})
_NUMBER = re.compile(r"^\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")
_NOTE_REF = re.compile(r"^\d{1,2}$")
_PERIOD = re.compile(
    r"for the (?P<kind>quarter|three months|half year|six months|nine months|year|period)\s+ended\s+"
    r"(?:on\s+)?(?P<date>[A-Za-z0-9 ,/.\-]{6,30})",
    re.IGNORECASE,
)
_PERIOD_TYPE = {
    "quarter": "quarterly",
    "three months": "quarterly",
    "half year": "half_yearly",
    "six months": "half_yearly",
    "nine months": "nine_months",
    "year": "annual",
    "period": None,  # the length of the period is not stated
}
_DIVIDEND_SENTENCE = re.compile(
    r"dividend[^.]{0,80}?Rs\.?\s*(\d+(?:\.\d+)?)\s*(?:per share|/share)", re.IGNORECASE
)
_THOUSANDS = re.compile(r"in thousands?|'000|rupees? in thousand", re.IGNORECASE)
_MILLIONS = re.compile(r"in millions?", re.IGNORECASE)


@dataclass(frozen=True)
class PucarFinancialResult:
    symbol: str
    period_ended: date | None
    period_type: str | None
    turnover: float | None
    cost_of_sales: float | None
    gross_profit: float | None
    operating_profit: float | None
    profit_before_tax: float | None
    profit_after_tax: float | None
    eps: float | None
    dividend_pkr: float | None
    warnings: tuple[str, ...] = ()


# --------------------------------------------------------------------------- numbers


def parse_number(token: str) -> float | None:
    """One printed figure as a float, or None when the token is not a figure."""
    t = token.strip()
    if t.lower() in _DASH_VALUES:
        return 0.0
    if not _NUMBER.match(t):
        return None
    negative = (t.startswith("(") and t.endswith(")")) or t.startswith("-")
    value = float(t.strip("()-").replace(",", ""))
    return -value if negative else value


def _split_row(line: str) -> tuple[str, list[float]] | None:
    """Split one line into its label and its trailing figures. Returns None for lines without figures."""
    tokens = line.split()
    values: list[float] = []
    i = len(tokens)
    while i > 0:
        value = parse_number(tokens[i - 1])
        if value is None:
            break
        values.append(value)
        i -= 1
    label = " ".join(tokens[:i]).strip(" .:")
    if not values or not label or not re.search(r"[A-Za-z]", label):
        return None
    values.reverse()
    if len(values) >= 3 and _NOTE_REF.match(tokens[i]):
        values = values[1:]  # a note reference, not a figure
    return label, values


# --------------------------------------------------------------------------- labels


def _normalise(label: str) -> str:
    s = label.lower()
    s = re.sub(r"\((loss|profit)\)", " ", s)
    s = re.sub(r"[/\-–—:.,()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _classify(label: str) -> str | None:
    n = _normalise(label)
    if "per share" in n and "dividend" in n:
        return "dividend_pkr"
    if "per share" in n or n.startswith(("eps", "basic eps")):
        return "eps"
    if "dividend" in n:
        return "dividend_pkr"
    if n.startswith("cost of"):
        return "cost_of_sales"
    if n.startswith("gross"):
        return "gross_profit"
    if n.startswith(
        (
            "operating profit",
            "operating loss",
            "operating income",
            "profit from operations",
            "loss from operations",
        )
    ):
        return "operating_profit"
    if "before tax" in n:
        return "profit_before_tax"
    if n.startswith(("net profit", "profit", "net loss", "loss")) and (
        "after tax" in n or re.search(r"for the (period|year|quarter|half year|nine months)", n)
    ):
        return "profit_after_tax"
    if n.startswith(("sales", "net sales", "turnover", "revenue", "net markup", "net mark up")):
        return "turnover"
    return None


def _period(text: str, warnings: list[str]) -> tuple[date | None, str | None]:
    m = _PERIOD.search(text)
    if not m:
        warnings.append("period end date not found")
        return None, None
    period_end = _parse_date(m.group("date"))
    if period_end is None:
        warnings.append("period end date could not be read")
    kind = m.group("kind").lower()
    period_type = _PERIOD_TYPE[kind]
    if period_type is None:
        warnings.append("period length not stated (period ended)")
    return period_end, period_type


def _parse_date(raw: str) -> date | None:
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw.strip(" ,."))
    s = re.sub(r"\s+", " ", s)
    m = re.match(r"^(\d{1,2}) ([A-Za-z]+),? (\d{4})", s)
    if m:
        d, mon, y = m.groups()
    else:
        m = re.match(r"^([A-Za-z]+) (\d{1,2}),? (\d{4})", s)
        if m:
            mon, d, y = m.groups()
        else:
            m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
            if not m:
                return None
            d, mo, y = m.groups()
            try:
                return date(int(y), int(mo), int(d))
            except ValueError:
                return None
    for fmt in ("%B", "%b"):
        try:
            return datetime.strptime(f"{int(d)} {mon} {y}", f"%d {fmt} %Y").date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- parser


def parse_pucar_text(text: str, symbol: str) -> PucarFinancialResult:
    """Extract the headline figures from the raw text of one PUCAR earnings declaration."""
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required; it is never inferred from the text")
    warnings: list[str] = []
    period_ended, period_type = _period(text, warnings)
    if _THOUSANDS.search(text):
        warnings.append("figures are printed in thousands; returned as printed, not rescaled")
    elif _MILLIONS.search(text):
        warnings.append("figures are printed in millions; returned as printed, not rescaled")

    found: dict[str, list[float]] = {}
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.replace(" ", " ")).strip()
        row = _split_row(line)
        if row is None:
            continue
        label, values = row
        field = _classify(label)
        if field is not None:
            found.setdefault(field, []).append(values[0])

    if "dividend_pkr" not in found:
        sentence = _DIVIDEND_SENTENCE.search(text)
        if sentence:
            found["dividend_pkr"] = [float(sentence.group(1))]

    values: dict[str, float | None] = {}
    for field in (
        "turnover",
        "cost_of_sales",
        "gross_profit",
        "operating_profit",
        "profit_before_tax",
        "profit_after_tax",
        "eps",
        "dividend_pkr",
    ):
        seen = found.get(field, [])
        values[field] = seen[0] if seen else None
        if len(set(seen)) > 1:
            warnings.append(f"{field} appears {len(seen)} times with different values; the first is used")

    missing = [f for f, v in values.items() if v is None]
    if missing:
        warnings.append("not found: " + ", ".join(missing))

    return PucarFinancialResult(
        symbol=sym,
        period_ended=period_ended,
        period_type=period_type,
        warnings=tuple(warnings),
        **values,
    )
