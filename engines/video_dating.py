"""Date INTERVALS for videos that have no publication date.

The archive has no dates and YouTube cannot be scraped, but it is in newest-first order. That is real
information: a video is no later than any newer video, and no earlier than any older one. A few titles also
state a date, a budget year, or a year. Combining the two gives each video an honest interval
[date_from, date_to] instead of a made-up date.

How the bounds are derived
* A title that names an exact day ("16 March 2026") bounds that video to a few days around it.
* A title naming a budget ("Budget 2026") bounds it to June of that year, when Pakistan's federal budget is
  presented.
* A title naming only a year bounds it to the whole of the year before through the end of that year. A year in
  a title is the SUBJECT year ("Best Cement Company of 2025", "Better for 2027?"), not necessarily the upload
  year, and nothing says how far apart they can be, so this assumption is deliberately wide.
* Order then tightens everything: date_to is the smallest upper bound of any video at or above it in the
  newest-first order, and date_from is the largest lower bound of any video at or below it. A video with no
  anchor of its own still gets an interval from its neighbours.
* The archive's capture date is a hard ceiling: nothing was published after it.

An interval is a bound, not a date. Anything that needs a single date should say so and use `date_to` (the
latest it can be) or the midpoint, knowing the width. A real date, when one arrives, replaces the interval and
the basis becomes "verified".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

CAPTURE_DATE = date(2026, 11, 14)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_DAY = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(20\d{2})\b", re.I)
_BUDGET = re.compile(r"\bbudget\s*(20\d{2})\b|\b(20\d{2})\s+budget\b", re.I)
_YEAR = re.compile(r"\b(20\d{2})\b")


@dataclass(frozen=True)
class Anchor:
    lo: date
    hi: date
    basis: str
    note: str


@dataclass(frozen=True)
class Dating:
    video_id: str
    archive_position: int
    date_from: date | None
    date_to: date
    basis: str
    note: str

    @property
    def width_days(self) -> int | None:
        return None if self.date_from is None else (self.date_to - self.date_from).days


def anchor_from_title(title: str) -> Anchor | None:
    """The tightest date a title states about itself, or None."""
    day = _DAY.search(title)
    if day:
        d = date(int(day.group(3)), _MONTHS[day.group(2).lower()], int(day.group(1)))
        return Anchor(d - timedelta(days=1), d + timedelta(days=3), "title_exact_day", day.group(0))
    budget = _BUDGET.search(title)
    if budget:
        year = int(budget.group(1) or budget.group(2))
        return Anchor(date(year, 6, 1), date(year, 6, 30), "title_budget", budget.group(0))
    years = [int(y) for y in _YEAR.findall(title) if 2020 <= int(y) <= 2030]
    if years:
        year = min(years)
        return Anchor(date(year - 1, 1, 1), date(year, 12, 31), "title_year", str(year))
    return None


class DatingConflict(ValueError):
    """Two anchors contradict the newest-first order, so one of them is not what it appears to be."""


def estimate(videos: list[dict[str, Any]], capture: date = CAPTURE_DATE) -> list[Dating]:
    """videos: dicts with video_id, title, archive_position (0 = newest). Returns one Dating per video."""
    ordered = sorted(videos, key=lambda v: v["archive_position"])
    anchors = [anchor_from_title(v["title"]) for v in ordered]
    n = len(ordered)
    upper: list[date] = []
    running = capture
    for a in anchors:  # newest to oldest: a video is no later than any newer video's upper bound
        if a is not None:
            running = min(running, a.hi)
        upper.append(running)
    lower: list[date | None] = [None] * n
    running_lo: date | None = None
    for i in range(n - 1, -1, -1):  # oldest to newest: no earlier than any older video's lower bound
        a = anchors[i]
        if a is not None:
            running_lo = a.lo if running_lo is None else max(running_lo, a.lo)
        lower[i] = running_lo
    out = []
    for i, v in enumerate(ordered):
        lo, hi = lower[i], upper[i]
        if lo is not None and lo > hi:
            raise DatingConflict(f"{v['video_id']} ({v['title'][:50]!r}): earliest {lo} is after latest {hi}")
        a = anchors[i]
        out.append(Dating(v["video_id"], v["archive_position"], lo, hi,
                          a.basis if a else "order_bounded", a.note if a else ""))
    return out
