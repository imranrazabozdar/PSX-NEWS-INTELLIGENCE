"""Session completeness grading, historical gap detection and cheap coverage for stored market bars.

Principles:
* Presence of a bar is what counts. Volume is never used: a zero-volume bar is a real observation, and a
  missing bar is never read as "no trading".
* Expected bars come from the market itself: the union of bar starts that any tracked symbol has for that
  session (the consensus). Market breaks (e.g. a Friday break), early closes and special sessions
  therefore never raise false gaps. Recorded official hours (engines/market_calendar.py) are used only
  to flag bars outside them as ANOMALY.
* Non-trading days (weekends, recorded holidays and closures) are never reported as missing. A weekday
  on which no tracked symbol has any bar, inside the collected range, is MARKET_CLOSED_INFERRED (no
  alert; the owner can confirm it in the calendar).
* PROVIDER_UNAVAILABLE: data for a session older than the provider's retention horizon for that
  timeframe that is still missing. It cannot be recovered and is not a collection failure.
* Limitation: with a single tracked symbol the consensus is that symbol, so gaps inside its own sessions
  cannot be detected. The five-symbol universe gives a meaningful consensus.

Grades: COMPLETE, INCOMPLETE, ANOMALY, MISSING, PROVIDER_UNAVAILABLE. Ungraded states: NON_TRADING,
MARKET_CLOSED_INFERRED, NOT_COLLECTED (after the symbol's latest bar, or backfill not started),
CURRENT_SESSION (today, still open or not yet final).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from engines.market_calendar import NON_TRADING, TradingCalendar, load_calendar

PKT = timedelta(hours=5)
SLOT_SECONDS = {"1m": 60, "1h": 3600, "4h": 14400, "1d": 86400}
# How far back each timeframe is assessed, and how long the provider is observed to keep history
# (collectors/market_ohlcv.TIMEFRAMES first-run windows: 1m about 5 days).
ASSESS_DAYS = {"1m": 7, "1h": 30, "4h": 60, "1d": 365}
RETENTION_DAYS = {"1m": 5, "1h": 90, "4h": 365, "1d": 5 * 365}
# A 1-minute session is INCOMPLETE only if it lacks a run of more than this many consecutive minutes that
# other symbols traded (thinly traded minutes are normal). Other timeframes: any missing consensus slot.
TOLERANCE_SLOTS = {"1m": 60, "1h": 0, "4h": 0, "1d": 0}
GRADES = ("COMPLETE", "INCOMPLETE", "ANOMALY", "MISSING", "PROVIDER_UNAVAILABLE")


def _epoch(iso: str) -> int:
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pkt_date(now: datetime) -> str:
    return (now.astimezone(UTC) + PKT).strftime("%Y-%m-%d")


@dataclass
class SessionGrade:
    symbol: str
    timeframe: str
    session_date: str
    state: str
    bars: int = 0
    expected: int = 0
    reason: str = ""
    missing_runs: list[tuple[str, str]] = field(default_factory=list)  # (first, last) missing bar starts


def load_bars(db, source_id: str, symbols, timeframe: str, since_date: str) -> dict:
    """{symbol: {session_date: [bar_start_utc...]}} plus first/last bar per symbol, via the primary-key
    index (one range read per symbol; MIN and MAX as separate single-aggregate lookups)."""
    since = (datetime.fromisoformat(since_date).replace(tzinfo=UTC) - PKT).strftime("%Y-%m-%dT%H:%M:%SZ")
    stmts = []
    for s in symbols:
        key = (source_id, s, timeframe)
        stmts += [
            ("SELECT bar_start_utc, session_date_pkt FROM market_bars WHERE source_id = ? AND symbol = ? "
             "AND timeframe = ? AND bar_start_utc >= ? ORDER BY bar_start_utc", (*key, since)),
            ("SELECT MIN(bar_start_utc) AS v FROM market_bars WHERE source_id = ? AND symbol = ? "
             "AND timeframe = ?", key),
            ("SELECT MAX(bar_start_utc) AS v FROM market_bars WHERE source_id = ? AND symbol = ? "
             "AND timeframe = ?", key),
        ]
    res = db.batch(stmts) if stmts else []
    out = {}
    for i, s in enumerate(symbols):
        rows, lo, hi = res[3 * i], res[3 * i + 1], res[3 * i + 2]
        days: dict[str, list[str]] = {}
        for r in rows:
            days.setdefault(r["session_date_pkt"], []).append(r["bar_start_utc"])
        out[s] = {"days": days, "first": lo[0]["v"] if lo else None, "last": hi[0]["v"] if hi else None}
    return out


def _runs(missing: list[int], step: int) -> list[list[int]]:
    runs: list[list[int]] = []
    for t in missing:
        if runs and t - runs[-1][-1] <= step:
            runs[-1].append(t)
        else:
            runs.append([t])
    return runs


def retention_start(today: str, timeframe: str) -> str:
    return (date.fromisoformat(today) - timedelta(days=RETENTION_DAYS[timeframe])).isoformat()


def _pkt_day(iso: str | None) -> str | None:
    return (datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ") + PKT).date().isoformat() if iso else None


def _outside_hours(own: list[int], hours: tuple[int, int] | None, timeframe: str) -> int:
    # only 1-minute bars: hour-aligned 1h/4h bars (e.g. starting 09:00 PKT) and daily bars legitimately
    # start before the official pre-open time
    if not hours or timeframe != "1m":
        return 0
    o, c = hours
    mins = [(datetime.fromtimestamp(t, UTC) + PKT) for t in own]
    return sum(1 for m in mins if not o <= m.hour * 60 + m.minute < c)


def _grade_one(g: SessionGrade, own: list[int], union: list[int], series: dict, ctx: dict) -> None:
    day, cal, tf = g.session_date, ctx["calendar"], g.timeframe
    old = day < ctx["retention_start"]
    day_type = cal.day_type(day)
    if day_type in NON_TRADING:
        g.state, g.reason = ("ANOMALY", f"bars on a non-trading day ({day_type})") if own \
            else ("NON_TRADING", day_type)
    elif day >= ctx["today"]:
        g.state, g.reason = "CURRENT_SESSION", "today's session is not final"
    elif series["last"] is None or day > _pkt_day(series["last"]):
        g.state, g.reason = ("PROVIDER_UNAVAILABLE", "older than the provider's retention") if old \
            else ("NOT_COLLECTED", "after the latest stored bar (incremental fetch pending)")
    elif not union:
        g.state, g.reason = "MARKET_CLOSED_INFERRED", "no tracked symbol has bars for this weekday"
    elif not own:
        if old:
            g.state, g.reason = "PROVIDER_UNAVAILABLE", "missing and older than the provider's retention"
        else:
            before = series["first"] and day < _pkt_day(series["first"])
            g.state = "MISSING"
            note = " (before its first stored bar)" if before else ""
            g.reason = "other symbols traded; no bar stored" + note
            g.missing_runs = [(_iso(union[0]), _iso(union[-1]))]
    elif n := _outside_hours(own, cal.hours(day), tf):
        g.state, g.reason = "ANOMALY", f"{n} bar(s) outside the recorded session hours"
    else:
        ownset = set(own)
        missing = [t for t in union if t not in ownset]
        runs = [r for r in _runs(missing, SLOT_SECONDS[tf]) if len(r) > TOLERANCE_SLOTS[tf]]
        if not runs:
            g.state = "COMPLETE"
            return
        g.state = "INCOMPLETE"
        lost = "provider retention passed" if old else "recoverable"
        g.reason = f"{sum(map(len, runs))} slot(s) traded by other symbols are missing ({lost})"
        g.missing_runs = [(_iso(r[0]), _iso(r[-1])) for r in runs]


def grade_sessions(
    data: dict, timeframe: str, start_date: str, end_date: str, *, today: str,
    calendar: TradingCalendar | None = None,
) -> list[SessionGrade]:
    ctx = {
        "calendar": calendar or load_calendar(),
        "today": today,
        "retention_start": retention_start(today, timeframe),
    }
    out: list[SessionGrade] = []
    d = date.fromisoformat(start_date)
    while d.isoformat() <= end_date:
        day = d.isoformat()
        d += timedelta(days=1)
        union = sorted({_epoch(b) for s in data.values() for b in s["days"].get(day, [])})
        for sym, series in data.items():
            own = sorted(_epoch(b) for b in series["days"].get(day, []))
            g = SessionGrade(sym, timeframe, day, "", bars=len(own), expected=len(union))
            _grade_one(g, own, union, series, ctx)
            out.append(g)
    return out


def assess(db, source_id: str, symbols, timeframe: str, *, now: datetime | None = None,
           calendar: TradingCalendar | None = None) -> list[SessionGrade]:
    now = now or datetime.now(UTC)
    today = _pkt_date(now)
    start = (date.fromisoformat(today) - timedelta(days=ASSESS_DAYS[timeframe])).isoformat()
    data = load_bars(db, source_id, list(symbols), timeframe, start)
    return grade_sessions(data, timeframe, start, today, today=today, calendar=calendar)


def recoverable_gaps(grades: list[SessionGrade], *, today: str) -> list[tuple[str, str, int, int]]:
    """(symbol, timeframe, from_epoch, to_epoch) still inside the provider's retention, 1-minute first,
    newest first within a timeframe (older sessions expire first, so they come first)."""
    order = {"1m": 0, "1h": 1, "4h": 2, "1d": 3}
    gaps = []
    for g in grades:
        if g.state not in ("MISSING", "INCOMPLETE"):
            continue
        if g.session_date < retention_start(today, g.timeframe):
            continue
        for a, b in g.missing_runs:
            gaps.append((g.symbol, g.timeframe, _epoch(a), _epoch(b)))
    return sorted(gaps, key=lambda x: (order[x[1]], x[2]))


def coverage_summary(db, source_id: str, symbols, timeframes) -> list[dict]:
    """First and latest bar per series with two indexed single-aggregate lookups each: a few rows read in
    total instead of scanning every bar (the market_coverage view reads all bars)."""
    series = [(s, t) for t in timeframes for s in symbols]
    stmts = []
    for s, t in series:
        key = (source_id, s, t)
        stmts += [
            ("SELECT MIN(bar_start_utc) AS v FROM market_bars WHERE source_id = ? AND symbol = ? "
             "AND timeframe = ?", key),
            ("SELECT MAX(bar_start_utc) AS v FROM market_bars WHERE source_id = ? AND symbol = ? "
             "AND timeframe = ?", key),
        ]
    res = db.batch(stmts) if stmts else []
    return [
        {"symbol": s, "timeframe": t, "first_bar_utc": res[2 * i][0]["v"] if res[2 * i] else None,
         "last_bar_utc": res[2 * i + 1][0]["v"] if res[2 * i + 1] else None}
        for i, (s, t) in enumerate(series)
    ]
