"""Pilot runner: offline-testable, read-only, bounded collection of daily closes and volumes.

Restricted to:
* the four pilot symbols (APL, BAHL, PACE, DFML) and at most PILOT_MAX_REQUESTS requests in total
  (robots.txt checks count toward the cap);
* the approved chart feed host only (the UDF /history endpoint used by the approved `scs_chart`
  source), through collectors.permissioned_fetch, which applies the approved User-Agent, the
  3.5–8.5 s jitter, the off-peak gate, the https allow-list and robots.txt;
* data at least 15 minutes settled: a bar is kept only if its settlement time (the close of its
  session, PKT, from the official calendar) is at least 15 minutes before now, and its timestamp
  is an integer epoch. Live, future, naive or non-integer timestamps are dropped and counted.

The runner returns rows and a report. It writes nothing to any database and stores nothing.
It runs only when called with the approval ID recorded in docs/SOURCE_PERMISSION_LOG.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta, timezone
from urllib.parse import urlencode

from collectors.permissioned_fetch import (
    DATA_DELAY_MINUTES,
    PermissionedFetcher,
    PermissionRefused,
)
from engines.market_calendar import TradingCalendar

PILOT_APPROVAL_ID = "PILOT-2026-11-09-01"
PILOT_SYMBOLS = ("APL", "BAHL", "PACE", "DFML")
PILOT_MAX_REQUESTS = 10
PILOT_CHART_HOST = "chart.scstrade.com"
PILOT_BASE_URL = f"https://{PILOT_CHART_HOST}"
RESOLUTION = "D"
SOURCE_ID = "scs_chart"
PKT = timezone(timedelta(hours=5))


class PilotRefused(PermissionRefused):
    """The pilot was asked to do something outside its approved limits."""


@dataclass
class PilotReport:
    approval_id: str
    requests_made: int = 0
    rows_kept: int = 0
    dropped_live_or_future: int = 0
    dropped_invalid_timestamp: int = 0
    dropped_unsettled: int = 0
    symbols_without_data: list[str] = field(default_factory=list)


def _pkt_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).astimezone(PKT).date().isoformat()


def settlement_time(day: str, calendar: TradingCalendar) -> datetime:
    """When a daily bar for PKT session `day` is settled.

    On a trading day with recorded hours: the session close (PKT). Otherwise the end of that
    PKT day, which is conservative (the bar is settled no earlier than the end of the day).
    """
    d = datetime.fromisoformat(day).date()
    hours = calendar.hours(day) if calendar.is_trading_day(day) else None
    if hours is not None:
        close_min = hours[1]
        local = datetime.combine(d, time(0, 0), tzinfo=PKT) + timedelta(minutes=close_min)
    else:
        local = datetime.combine(d, time(23, 59), tzinfo=PKT)
    return local.astimezone(UTC)


def build_url(symbol: str, frm_epoch: int, to_epoch: int) -> str:
    query = urlencode({"symbol": symbol, "resolution": RESOLUTION, "from": frm_epoch, "to": to_epoch})
    return f"{PILOT_BASE_URL}/history?{query}"


def window(now: datetime, lookback_days: int) -> tuple[int, int, datetime]:
    """(from, to, data_as_of) epochs. `to` is capped at now minus the mandatory delay."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    data_as_of = now - timedelta(minutes=DATA_DELAY_MINUTES)
    to_epoch = int(data_as_of.timestamp())
    frm_epoch = to_epoch - lookback_days * 86400
    return frm_epoch, to_epoch, data_as_of


def parse_and_filter(payload: dict, symbol: str, now: datetime, calendar: TradingCalendar,
                     report: PilotReport) -> list[dict]:
    """UDF history payload -> settled daily rows. Drops anything not settled 15 minutes ago."""
    if payload.get("s") == "no_data":
        return []
    if payload.get("s") != "ok":
        raise PilotRefused(f"unexpected UDF status for {symbol}: {payload.get('s')!r}")
    times = payload.get("t") or []
    closes = payload.get("c") or []
    vols = payload.get("v") or []
    if not (len(times) == len(closes) == len(vols)):
        raise PilotRefused(f"UDF arrays differ in length for {symbol}")
    latest = now - timedelta(minutes=DATA_DELAY_MINUTES)
    rows = []
    for t, c, v in zip(times, closes, vols, strict=True):
        if not isinstance(t, int) or isinstance(t, bool):
            report.dropped_invalid_timestamp += 1
            continue
        bar_start = datetime.fromtimestamp(t, tz=UTC)
        if bar_start > latest:
            report.dropped_live_or_future += 1
            continue
        day = _pkt_date(t)
        if settlement_time(day, calendar) > latest:
            report.dropped_unsettled += 1
            continue
        rows.append({"source_id": SOURCE_ID, "symbol": symbol, "session_date_pkt": day,
                     "close": float(c), "volume": float(v)})
    return rows


def run_pilot(fetcher: PermissionedFetcher, calendar: TradingCalendar, now: datetime, *,
              approval_id: str, lookback_days: int = 30,
              symbols: tuple[str, ...] = PILOT_SYMBOLS) -> tuple[list[dict], PilotReport]:
    """Run the approved pilot. Refuses unless the approval ID and limits match the approval."""
    if approval_id != PILOT_APPROVAL_ID:
        raise PilotRefused("approval ID does not match the recorded pilot approval")
    if tuple(symbols) != PILOT_SYMBOLS:
        raise PilotRefused("symbols must be exactly the approved pilot list")
    if fetcher.allowed_hosts != frozenset({PILOT_CHART_HOST}):
        raise PilotRefused("the pilot may reach only the approved chart host")
    frm_epoch, to_epoch, data_as_of = window(now, lookback_days)
    report = PilotReport(approval_id=approval_id)
    rows: list[dict] = []
    for symbol in symbols:
        # one page request, plus one robots.txt request if the host has not been read yet
        if fetcher.requests_made + 2 > PILOT_MAX_REQUESTS:
            raise PilotRefused(f"request cap of {PILOT_MAX_REQUESTS} would be exceeded")
        body = fetcher.fetch(build_url(symbol, frm_epoch, to_epoch), data_as_of_utc=data_as_of)
        if fetcher.requests_made > PILOT_MAX_REQUESTS:
            raise PilotRefused(f"request cap of {PILOT_MAX_REQUESTS} exceeded")
        report.requests_made = fetcher.requests_made
        kept = parse_and_filter(json.loads(body.decode("utf-8")), symbol, now, calendar, report)
        if not kept:
            report.symbols_without_data.append(symbol)
        rows.extend(kept)
    report.requests_made = fetcher.requests_made
    report.rows_kept = len(rows)
    return rows, report


def dry_run_plan(now: datetime, lookback_days: int = 30) -> list[str]:
    """URLs the pilot would request, with no network access."""
    frm_epoch, to_epoch, _ = window(now, lookback_days)
    return [build_url(s, frm_epoch, to_epoch) for s in PILOT_SYMBOLS]


__all__ = ["PILOT_APPROVAL_ID", "PILOT_MAX_REQUESTS", "PILOT_SYMBOLS",
           "PilotRefused", "PilotReport", "build_url", "dry_run_plan", "parse_and_filter",
           "run_pilot", "settlement_time", "window"]
