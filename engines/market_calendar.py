"""PSX trading calendar for market-data quality checks.

Data: config/psx_calendar.json, owner-maintained from official PSX notices (each entry cites its notice).
Nothing is assumed beyond what it records:
* Weekends (Saturday, Sunday) are non-trading days.
* `holidays` and `closures` (unexpected closures) are non-trading days.
* `special_sessions` are trading days with their own hours (e.g. a weekend session or shorter hours).
* `regular_hours`, keyed by weekday ("0" Monday ... "4" Friday) or "default", gives official hours as
  "HH:MM" PKT. When none are recorded, hours are None and callers infer the session window from the
  bars the market actually traded. Weekdays are never assumed to share identical hours.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "psx_calendar.json"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

WEEKEND, HOLIDAY, CLOSURE, SPECIAL, WEEKDAY = "WEEKEND", "HOLIDAY", "CLOSURE", "SPECIAL", "WEEKDAY"
NON_TRADING = (WEEKEND, HOLIDAY, CLOSURE)


class CalendarError(ValueError):
    pass


def _minutes(hhmm: str) -> int:
    if not _HHMM.match(hhmm or ""):
        raise CalendarError(f"invalid time {hhmm!r}; use HH:MM PKT")
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hours(entry: dict, where: str) -> tuple[int, int]:
    o, c = _minutes(entry.get("open", "")), _minutes(entry.get("close", ""))
    if o >= c:
        raise CalendarError(f"{where}: open must be before close")
    return o, c


@dataclass
class TradingCalendar:
    weekend: frozenset[int] = frozenset({5, 6})
    regular_hours: dict[str, tuple[int, int]] = field(default_factory=dict)
    holidays: dict[str, str] = field(default_factory=dict)
    closures: dict[str, str] = field(default_factory=dict)
    special: dict[str, tuple[int, int] | None] = field(default_factory=dict)

    def day_type(self, day: str) -> str:
        if day in self.closures:
            return CLOSURE
        if day in self.holidays:
            return HOLIDAY
        if day in self.special:
            return SPECIAL
        return WEEKEND if date.fromisoformat(day).weekday() in self.weekend else WEEKDAY

    def is_trading_day(self, day: str) -> bool:
        return self.day_type(day) not in NON_TRADING

    def hours(self, day: str) -> tuple[int, int] | None:
        """Official (open, close) in PKT minutes after midnight, or None when not recorded."""
        t = self.day_type(day)
        if t in NON_TRADING:
            return None
        if t == SPECIAL:
            return self.special[day]
        wd = str(date.fromisoformat(day).weekday())
        return self.regular_hours.get(wd) or self.regular_hours.get("default")


def load_calendar(path: Path | str = DEFAULT_PATH) -> TradingCalendar:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cal = TradingCalendar(weekend=frozenset(int(d) for d in raw.get("weekend_weekdays", [5, 6])))
    for key, entry in (raw.get("regular_hours") or {}).items():
        if key not in {"default", "0", "1", "2", "3", "4", "5", "6"}:
            raise CalendarError(f"regular_hours key {key!r}: use 'default' or a weekday number 0-6")
        cal.regular_hours[key] = _hours(entry, f"regular_hours[{key}]")
    for section, target in (("holidays", cal.holidays), ("closures", cal.closures)):
        for day, entry in (raw.get(section) or {}).items():
            if not _DATE.match(day) or not isinstance(entry, dict) or not entry.get("source"):
                raise CalendarError(f"{section}[{day}]: needs a YYYY-MM-DD date and a cited 'source'")
            target[day] = entry.get("name", section)
    for day, entry in (raw.get("special_sessions") or {}).items():
        if not _DATE.match(day) or not isinstance(entry, dict) or not entry.get("source"):
            raise CalendarError(f"special_sessions[{day}]: needs a YYYY-MM-DD date and a cited 'source'")
        cal.special[day] = _hours(entry, f"special_sessions[{day}]") if entry.get("open") else None
    return cal
