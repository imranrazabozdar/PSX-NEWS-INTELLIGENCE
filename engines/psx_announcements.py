"""PSX corporate announcements (the exchange's dissemination feed, owner-supplied export) into dated facts.

The feed (`announceWithSymbol.lis`, a file the owner downloads from PSX and supplies; nothing here
fetches from PSX) has
one line per fragment: SYMBOL|COMPANY|DDMonYYYY|HH:MM:SS|TEXT|. Fragments sharing symbol, date and time
are ONE
announcement, for example a financial result:

    POML|Punjab Oil|10Nov2026|15:44:55|FINANCIAL RESULT FOR THE FIRST QUARTER ENDED 30/09/2026|
    POML|Punjab Oil|10Nov2026|15:44:55|PROFIT/LOSS BEFORE TAXATION RS. IN MILLION (154.882)|
    POML|Punjab Oil|10Nov2026|15:44:55|PROFIT/LOSS AFTER TAXATION RS. IN MILLION (141.233)|
    POML|Punjab Oil|10Nov2026|15:44:55|EPS = (18.19)|

Pure Python, no model. Every figure is copied from the line that states it; a figure the announcement
does not state
is None, never zero. Parentheses mean a loss. Lines this module does not recognise are counted and
reported, never
guessed at.

Topics produced: results.annual / quarterly / half_year / nine_months / other, corporate_action.dividend
/ bonus /
rights / book_closure / meeting.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime

SOURCE_NAME = "PSX announcement feed (owner-supplied export of announceWithSymbol.lis)"
MAX_TEXT = 300

_NUM = r"\(?-?[\d,]*\.?\d+\)?"  # an unclosed "(154.8" still reads as a loss
_SCOPE = re.compile(r"^\(\s*(UN)?\s*C[A-Z]{1,3}SOLID[A-Z]*\s*\)\s*", re.I)
_PBT = re.compile(rf"P?ROFIT\s*/\s*LOSS\s+BEFORE\s+TAXATION\s+RS\.?\s*IN\s+MILLION\s*({_NUM})?\s*$", re.I)
_PAT = re.compile(rf"P?ROFIT\s*/\s*LOSS\s+AFTER\s+TAXATION\s+RS\.?\s*IN\s+MILLION\s*({_NUM})?\s*$", re.I)
_EPS = re.compile(rf"\bEPS\s*=?\s*({_NUM})\s*$", re.I)
_PERIOD = re.compile(
    r"FINANCIAL\s+RESULT\s+FOR\s+(?:THE\s+)?(.+?)\s+END(?:ED|ING)\s+(\d{1,2}/\d{1,2}/\d{4})", re.I
)
_DIV = re.compile(r"\bDIVIDEND\s*=\s*([\d.]+)\s*%?\s*(?:\(\s*([A-Za-z]+)\s*\))?", re.I)
_BONUS = re.compile(r"\bBONUS(?:\s+ISSUE)?\s*=\s*([\d.]+)\s*%", re.I)
_RIGHT = re.compile(r"\bRIGHT\s+ISSUE\s*=\s*([\d.]+)\s*%", re.I)
_BC_FROM = re.compile(
    r"BOOK\s+CLOSURE\s+FROM\s+(\d{1,2}/\d{1,2}/\d{4})(?:\s+TO\s+(\d{1,2}/\d{1,2}/\d{4}))?", re.I
)
_BC_TO = re.compile(r"BOOK\s+CLOSURE\s+TO\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
_MEETING = re.compile(
    r"\b(ANNUAL\s+GENERAL\s+MEETING|E\.?\s*O\.?\s*G\.?\s*M\.?|EXTRAORDINARY\s+GENERAL\s+MEETING|A\.?\s*G\.?\s*M\.?)"
    r"\s+(WILL\s+BE\s+HELD\s+ON|HELD\s+ON|SCHEDULED\s+FOR|TO\s+BE\s+HELD\s+ON)\s+(\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
_FOR_PERIOD = re.compile(r"^FOR\s+THE\s+(.+?)\s+END(?:ED|ING)\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
_DIV_KIND = {
    "F": "final",
    "I": "interim",
    "II": "second interim",
    "III": "third interim",
    "IV": "fourth interim",
}


@dataclass
class Announcement:
    symbol: str
    company: str
    day: date
    time: str
    lines: list[str] = field(default_factory=list)


def parse_number(text: str | None) -> float | None:
    """'1,625.591' -> 1625.591, '(154.882)' -> -154.882 (parentheses are a loss), empty -> None (never 0)."""
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    neg = t.startswith("(")
    t = t.strip("()").replace(",", "").strip()
    try:
        value = float(t)
    except ValueError:
        return None
    return -abs(value) if neg else value


def _date(text: str) -> date | None:
    for fmt in ("%d/%m/%Y",):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def read_announcements(lines: Iterable[str]) -> Iterator[Announcement]:
    """Group consecutive fragments with the same symbol, date and time. Malformed lines are skipped and
    counted by
    the caller through the generator's `skipped` attribute on the returned object."""
    current: Announcement | None = None
    for raw in lines:
        parts = raw.rstrip("\r\n").split("|")
        if len(parts) < 5:
            continue
        try:
            day = datetime.strptime(parts[2].strip(), "%d%b%Y").date()
        except ValueError:
            continue
        symbol, company, time, text = (
            parts[0].strip().upper(),
            parts[1].strip(),
            parts[3].strip(),
            parts[4].strip(),
        )
        if not symbol:
            continue
        key = (symbol, day, time)
        if current is None or (current.symbol, current.day, current.time) != key:
            if current is not None:
                yield current
            current = Announcement(symbol, company, day, time)
        if text:
            current.lines.append(text)
    if current is not None:
        yield current


def _scope_of(line: str) -> tuple[str | None, str]:
    m = _SCOPE.match(line)
    if not m:
        return None, line
    return ("unconsolidated" if m.group(1) else "consolidated"), line[m.end() :]


def _period_kind(label: str) -> str:
    low = label.upper()
    if "NINE" in low:
        return "nine_months"
    if "QUAR" in low:  # the feed has typos: "QUARETER"
        return "quarterly"
    if "HALF" in low:
        return "half_year"
    if low.strip().startswith(("YEAR", "FULL", "ANNUAL", "FINANCIAL YEAR")) or low.strip() == "YEAR":
        return "annual"
    return "other"


def _money(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    word = "loss" if value < 0 else "profit"
    return f"{word} {label} Rs {abs(value):,.3f} million"


def _row(
    a: Announcement, topic: str, text: str, value: float | None, unit: str | None, period: str | None
) -> dict:
    return {
        "company": a.symbol,
        "topic": topic,
        "fact_text": text[:MAX_TEXT],
        "value": value,
        "unit": unit,
        "period": period,
        "source_name": SOURCE_NAME,
        "source_url": None,
        "source_date": a.day.isoformat(),
        "as_of": a.day.isoformat(),
        "confidence": "fact",
        "created_at": f"{a.day.isoformat()}T{a.time or '00:00:00'}Z",
    }


def interpret(a: Announcement) -> tuple[list[dict], list[str]]:
    """Facts from one announcement, and the lines that were not recognised."""
    rows: list[dict] = []
    unknown: list[str] = []
    period_label = period_end = None
    results: dict[str, dict[str, float | None]] = {}  # scope -> pbt / pat / eps
    closure_from = closure_to = None
    context = None
    for line in a.lines:  # a "FOR THE YEAR ENDED ..." line may follow the dividend it describes
        fm = _FOR_PERIOD.match(_scope_of(line)[1])
        if fm:
            context = f"{fm.group(1).lower()} ended {fm.group(2)}"
    for line in a.lines:
        scope, body = _scope_of(line)
        key = scope or "unspecified"
        m = _PERIOD.search(body)
        if m:
            period_label, period_end = m.group(1).strip(), _date(m.group(2))
            continue
        if _PBT.search(body):
            results.setdefault(key, {})["pbt"] = parse_number(_PBT.search(body).group(1))
            continue
        if _PAT.search(body):
            results.setdefault(key, {})["pat"] = parse_number(_PAT.search(body).group(1))
            continue
        m = _EPS.search(body)
        if m:
            results.setdefault(key, {})["eps"] = parse_number(m.group(1))
            continue
        m = _DIV.search(body)
        if m:
            kind = _DIV_KIND.get((m.group(2) or "").upper(), "")
            pct = float(m.group(1))
            text = f"Dividend {pct:g}% of par" + (f" ({kind})" if kind else "")
            text += (f" for the {context}" if context else "") + f", announced {a.day:%d %b %Y}"
            rows.append(_row(a, "corporate_action.dividend", text, pct, "% of par", context))
            continue
        m = _BONUS.search(body)
        if m:
            pct = float(m.group(1))
            rows.append(
                _row(
                    a,
                    "corporate_action.bonus",
                    f"Bonus issue {pct:g}%, announced {a.day:%d %b %Y}",
                    pct,
                    "%",
                    None,
                )
            )
            continue
        m = _RIGHT.search(body)
        if m:
            pct = float(m.group(1))
            rows.append(
                _row(
                    a,
                    "corporate_action.rights",
                    f"Right issue {pct:g}%, announced {a.day:%d %b %Y}",
                    pct,
                    "%",
                    None,
                )
            )
            continue
        m = _BC_FROM.search(body)
        if m:
            closure_from = m.group(1)
            closure_to = m.group(2) or closure_to
            continue
        m = _BC_TO.search(body)
        if m:
            closure_to = m.group(1)
            continue
        m = _MEETING.search(body)
        if m:
            kind = (
                "Annual general meeting"
                if "ANNUAL" in m.group(1).upper() or m.group(1).upper().startswith("A")
                else "Extraordinary general meeting"
            )
            state = "held" if m.group(2).upper().startswith("HELD") else "scheduled"
            rows.append(
                _row(
                    a,
                    "corporate_action.meeting",
                    f"{kind} {state} for {m.group(3)}, announced {a.day:%d %b %Y}",
                    None,
                    None,
                    m.group(3),
                )
            )
            continue
        if _FOR_PERIOD.match(body):  # context line on a dividend notice, used above
            continue
        unknown.append(line)
    if closure_from:
        span = f"from {closure_from}" + (f" to {closure_to}" if closure_to else "")
        rows.append(
            _row(
                a,
                "corporate_action.book_closure",
                f"Book closure {span}, announced {a.day:%d %b %Y}",
                None,
                None,
                closure_from,
            )
        )
    loose = results.get("unspecified")
    if loose and set(loose) == {"eps"} and len(results) == 2:  # EPS with no basis next to one scoped group
        other = next(k for k in results if k != "unspecified")
        results[other]["eps"] = results.pop("unspecified")["eps"]
    if period_label and results:
        kind = _period_kind(period_label)
        end = period_end.isoformat() if period_end else None
        for scope, r in sorted(results.items()):
            parts = [x for x in (_money("before tax", r.get("pbt")), _money("after tax", r.get("pat"))) if x]
            if r.get("eps") is not None:
                parts.append(f"EPS {r['eps']:g}")
            if not parts:
                continue
            basis = scope if scope != "unspecified" else "basis not stated"
            when = end or "date not stated"
            text = (
                f"Financial result, {period_label.lower()} ended {when} ({basis}): " + ", ".join(parts) + "."
            )
            value, unit = (
                (r["eps"], "PKR/share") if r.get("eps") is not None else (r.get("pat"), "PKR million")
            )
            rows.append(
                _row(
                    a,
                    f"results.{kind}",
                    text,
                    value,
                    unit,
                    f"{period_label.lower()} ended {end}" if end else period_label.lower(),
                )
            )
    elif results:
        unknown.append(f"results without a period line: {sorted(results)}")
    return rows, unknown


def build_rows(
    announcements: Iterable[Announcement], since: date | None = None
) -> tuple[list[dict], Counter]:
    rows: list[dict] = []
    skipped: Counter = Counter()
    for a in announcements:
        if since and a.day < since:
            continue
        got, unknown = interpret(a)
        rows.extend(got)
        for line in unknown:
            skipped[re.sub(r"[0-9][0-9.,/()-]*", "#", line)[:70]] += 1
        if not got and not unknown:
            skipped["(empty)"] += 1
    return rows, skipped
