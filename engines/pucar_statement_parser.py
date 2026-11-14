"""Financial figures from PSX statutory earnings declarations (PUCAR letterheads, 1 to 3 pages).

Standard library only. The input is the raw text of one declaration (for example text extracted from a
PDF stream, or a text fixture). Nothing here reads a file, opens a URL or calls a PDF library.

Conventions
* The `*` fields are as printed. Units come from the text: "in thousand" or "'000" gives scale 1000,
  "in million" gives scale 1000000, and nothing stated gives scale 1. Values are never rescaled.
* `currency` is "PKR" or "USD" from the text, or None when neither is stated.
* The `*_pkr` properties are the canonical rupee figures (printed value x scale). They are None unless
  `currency` is "PKR", so a dollar statement is never labelled as rupees.
* Brackets mean negative: "(1,234,567)" -> -1234567.0. A cost printed in brackets is therefore negative.
* A dash or "nil" printed as a value is 0.0. A figure that is not printed at all is None.
* The first figure on a row is the current period. Statements with several columns print the current
  period first. A note reference (1 to 2 digits) before the figures is dropped when the statement has a
  Note column, or when the row has three or more figures.
* A label printed on more than one line is joined back together.
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
_UNIT_THOUSAND = re.compile(r"in thousands?|[‘’']000|rupees? in thousand", re.IGNORECASE)
_UNIT_MILLION = re.compile(r"in millions?", re.IGNORECASE)
_NOTE_HEADER = re.compile(r"\bNote\b")
_USD = re.compile(r"\bUS\s*Dollars?\b|\bUSD\b", re.IGNORECASE)
_PKR = re.compile(r"\bRs\b|\bRupees\b|\bPKR\b", re.IGNORECASE)
_CONNECTORS = frozenset({"to", "of", "and", "with", "from", "for", "in", "the", "by", "on", "-", "–", "/"})
# When a label occurs more than once, a line that ends like a statement total is preferred.
_PREFERRED_ENDINGS = {
    "profit_before_tax": ("tax", "taxation"),
    "profit_after_tax": ("tax", "taxation", "period", "year"),
}
_FIELDS = (
    "turnover",
    "cost_of_sales",
    "gross_profit",
    "operating_profit",
    "profit_before_tax",
    "profit_after_tax",
    "eps",
    "dividend_pkr",
)


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
    scale: int = 1
    currency: str | None = None
    warnings: tuple[str, ...] = ()

    def _pkr(self, value: float | None) -> float | None:
        if value is None or self.currency != "PKR":
            return None
        return value * self.scale

    @property
    def turnover_pkr(self) -> float | None:
        return self._pkr(self.turnover)

    @property
    def cost_of_sales_pkr(self) -> float | None:
        return self._pkr(self.cost_of_sales)

    @property
    def gross_profit_pkr(self) -> float | None:
        return self._pkr(self.gross_profit)

    @property
    def operating_profit_pkr(self) -> float | None:
        return self._pkr(self.operating_profit)

    @property
    def profit_before_tax_pkr(self) -> float | None:
        return self._pkr(self.profit_before_tax)

    @property
    def profit_after_tax_pkr(self) -> float | None:
        return self._pkr(self.profit_after_tax)

    @property
    def pat_pkr(self) -> float | None:
        """Alias of profit_after_tax_pkr."""
        return self.profit_after_tax_pkr


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


def _numeric_run(cell: str) -> list[tuple[str, float]] | None:
    """The figures in a cell when every token of it is a figure; None when any token is not."""
    items = []
    for token in cell.split():
        value = parse_number(token)
        if value is None:
            return None
        items.append((token, value))
    return items or None


def _split_row(line: str, has_note: bool) -> tuple[str, list[float]] | None:
    """Split one line into its label and its figures. Returns None for lines without figures.

    Cells are separated by runs of two or more spaces. The label is the first cell, and figures are taken
    only from the numeric cells directly after it, so a table printed further along the same line is never
    read as this row's figures."""
    cells = [c for c in re.split(r"\s{2,}", line.strip()) if c]
    if not cells:
        return None
    head = cells[0].split()
    items: list[tuple[str, float]] = []
    i = len(head)
    while i > 0:
        value = parse_number(head[i - 1])
        if value is None:
            break
        items.insert(0, (head[i - 1], value))
        i -= 1
    label = " ".join(head[:i]).strip(" .:")
    for cell in cells[1:]:
        run = _numeric_run(cell)
        if run is None:
            break
        items.extend(run)
    if not items or not label or not re.search(r"[A-Za-z]", label):
        return None
    values = [v for _, v in items]
    if _NOTE_REF.match(items[0][0]) and (len(values) >= 3 or (has_note and len(values) >= 2)):
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
    if n.startswith("gross revenue"):
        return None  # before sales tax and rebates; turnover is the net figure
    if "dividend" in n and "income" not in n and ("per share" in n or " rs" in f" {n}"):
        return "dividend_pkr"  # a per-share dividend, not the dividend income a bank earns
    if "per share" in n or n.startswith(("eps", "basic eps")):
        return "eps"
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
    if n.startswith(
        ("sales", "net sales", "net revenue", "turnover", "revenue", "net markup", "net mark up")
    ):
        return "turnover"
    return None


def _continues(previous: str, following: str) -> bool:
    """True when `following` is the rest of a label that began on `previous`."""
    if not previous or not following:
        return False
    if following[0].islower():
        return True
    last = previous.split()[-1].lower().rstrip(",")
    if last in _CONNECTORS or previous.rstrip().endswith(("-", "–", "/")):
        return True
    return "per share" in _normalise(previous) and _normalise(following).startswith(("basic", "diluted"))


def _pick(field: str, candidates: list[tuple[str, float]]) -> float:
    """The first candidate, unless a later one ends the way a statement total does."""
    for label, value in candidates:
        words = _normalise(label).split()
        if words and words[-1] in _PREFERRED_ENDINGS.get(field, ()):
            return value
    return candidates[0][1]


def _period(flat: str, warnings: list[str]) -> tuple[date | None, str | None]:
    m = _PERIOD.search(flat)
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


def _units(flat: str, warnings: list[str]) -> tuple[int, str | None]:
    if _USD.search(flat):
        currency = "USD"  # checked first: a dollar statement may also quote a rupee rate
    elif _PKR.search(flat):
        currency = "PKR"
    else:
        currency = None
    if _UNIT_THOUSAND.search(flat):
        scale = 1000
    elif _UNIT_MILLION.search(flat):
        scale = 1_000_000
    else:
        scale = 1
        warnings.append("units not stated; figures are taken as printed")
    if currency != "PKR":
        warnings.append(f"currency is {currency or 'not stated'}; PKR figures are not provided")
    return scale, currency


# --------------------------------------------------------------------------- parser


def parse_pucar_text(text: str, symbol: str) -> PucarFinancialResult:
    """Extract the headline figures from the raw text of one PUCAR earnings declaration."""
    sym = (symbol or "").strip().upper()
    if not sym:
        raise ValueError("symbol is required; it is never inferred from the text")
    flat = re.sub(r"\s+", " ", text.replace(" ", " "))
    warnings: list[str] = []
    period_ended, period_type = _period(flat, warnings)
    scale, currency = _units(flat, warnings)
    has_note = bool(_NOTE_HEADER.search(flat))

    found: dict[str, list[tuple[str, float]]] = {}
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.replace("\u00a0", " ").replace("\t", "    ").strip()  # keep column gaps
        if not line:
            pending = ""
            continue
        row = _split_row(line, has_note)
        if row is None:
            if re.search(r"[A-Za-z]", line):
                text_line = " ".join(line.split())
                pending = f"{pending} {text_line}" if _continues(pending, text_line) else text_line
            else:
                pending = ""
            continue
        label, values = row
        if pending and _continues(pending, label):
            label = f"{pending} {label}"
        pending = ""
        field = _classify(label)
        if field is not None:
            found.setdefault(field, []).append((label, values[0]))

    if "dividend_pkr" not in found:
        sentence = _DIVIDEND_SENTENCE.search(flat)
        if sentence:
            found["dividend_pkr"] = [("dividend sentence", float(sentence.group(1)))]

    values: dict[str, float | None] = {}
    for field in _FIELDS:
        candidates = found.get(field, [])
        values[field] = _pick(field, candidates) if candidates else None
        distinct = {v for _, v in candidates}
        if len(distinct) > 1:
            warnings.append(f"{field} appears {len(candidates)} times with different values; one is used")

    missing = [f for f, v in values.items() if v is None]
    if missing:
        warnings.append("not found: " + ", ".join(missing))

    return PucarFinancialResult(
        symbol=sym,
        period_ended=period_ended,
        period_type=period_type,
        scale=scale,
        currency=currency,
        warnings=tuple(warnings),
        **values,
    )
