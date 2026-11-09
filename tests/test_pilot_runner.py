"""Offline tests for collectors.pilot_runner. No network: the transport and clock are fakes."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from collectors.permissioned_fetch import (
    APPROVED_USER_AGENT,
    DATA_DELAY_MINUTES,
    OffPeakRefused,
    PermissionedFetcher,
)
from collectors.pilot_runner import (
    PILOT_APPROVAL_ID,
    PILOT_CHART_HOST,
    PILOT_MAX_REQUESTS,
    PILOT_SYMBOLS,
    PilotRefused,
    PilotReport,
    build_url,
    dry_run_plan,
    parse_and_filter,
    run_pilot,
    settlement_time,
    window,
)
from engines.market_calendar import load_calendar

CAL = load_calendar()
PKT = timezone(timedelta(hours=5))


def trading_day(start: str = "2026-11-10") -> tuple[str, int, int]:
    d = date.fromisoformat(start)
    for _ in range(60):
        day = d.isoformat()
        if CAL.is_trading_day(day) and CAL.hours(day):
            o, c = CAL.hours(day)
            return day, o, c
        d += timedelta(days=1)
    raise AssertionError("no trading day in calendar")


def pkt(day: str, minutes_after_midnight: int) -> datetime:
    base = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=PKT)
    return (base + timedelta(minutes=minutes_after_midnight)).astimezone(UTC)


class FakeChart:
    """Answers robots.txt with 404 and each symbol's history with a canned UDF payload."""

    def __init__(self, payloads: dict[str, dict] | None = None):
        self.payloads = payloads or {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        if url.endswith("/robots.txt"):
            return 404, b""
        for sym, payload in self.payloads.items():
            if f"symbol={sym}&" in url:
                return 200, json.dumps(payload).encode()
        return 200, json.dumps({"s": "no_data"}).encode()


def fetcher_at(now: datetime, chart: FakeChart, requests_made: int = 0) -> PermissionedFetcher:
    f = PermissionedFetcher(allowed_hosts=frozenset({PILOT_CHART_HOST}), calendar=CAL,
                            transport=chart, rng=random.Random(3),  # noqa: S311 - jitter, not security
                            sleep=lambda s: None, now=lambda: now)
    f.requests_made = requests_made
    return f


# ------------------------------------------------------------------ plan and URL construction
def test_dry_run_plan_lists_exactly_the_four_symbols_on_the_chart_host_with_no_live_end():
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    urls = dry_run_plan(now)
    assert len(urls) == 4
    for sym, url in zip(PILOT_SYMBOLS, urls, strict=True):
        assert url.startswith(f"https://{PILOT_CHART_HOST}/history?")
        assert f"symbol={sym}" in url and "resolution=D" in url
        to_epoch = int(url.split("to=")[1])
        assert to_epoch == int((now - timedelta(minutes=DATA_DELAY_MINUTES)).timestamp())


def test_symbols_are_exactly_the_approved_four():
    assert PILOT_SYMBOLS == ("APL", "BAHL", "PACE", "DFML")
    assert PILOT_MAX_REQUESTS == 10


def test_window_refuses_naive_time_and_caps_end_at_the_delay():
    with pytest.raises(ValueError):
        window(datetime(2026, 11, 10, 12, 0), 30)
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    _, to_epoch, as_of = window(now, 30)
    assert as_of == now - timedelta(minutes=DATA_DELAY_MINUTES)
    assert to_epoch == int(as_of.timestamp())


# ------------------------------------------------------------------ approval and scope refusals
def test_run_refuses_without_the_recorded_approval_id():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    with pytest.raises(PilotRefused, match="approval ID"):
        run_pilot(fetcher_at(now, FakeChart()), CAL, now, approval_id="PILOT-WRONG")
    assert FakeChart().calls == []


def test_run_refuses_any_symbol_outside_the_pilot_list():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    chart = FakeChart()
    with pytest.raises(PilotRefused, match="approved pilot list"):
        run_pilot(fetcher_at(now, chart), CAL, now, approval_id=PILOT_APPROVAL_ID,
                  symbols=("OGDC",))
    assert chart.calls == []


def test_run_refuses_any_host_other_than_the_chart_host():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    chart = FakeChart()
    bad = PermissionedFetcher(allowed_hosts=frozenset({"dps.psx.com.pk"}), calendar=CAL,
                              transport=chart, sleep=lambda s: None, now=lambda: now)
    with pytest.raises(PilotRefused, match="approved chart host"):
        run_pilot(bad, CAL, now, approval_id=PILOT_APPROVAL_ID)
    assert chart.calls == []


def test_run_is_refused_during_trading_hours():
    day, o, c = trading_day()
    now = pkt(day, o + 30)  # inside regular hours
    chart = FakeChart()
    with pytest.raises(OffPeakRefused):
        run_pilot(fetcher_at(now, chart), CAL, now, approval_id=PILOT_APPROVAL_ID)
    assert chart.calls == []


# ------------------------------------------------------------------ 15-minute filter
def test_live_future_unsettled_and_invalid_timestamps_are_dropped_and_settled_bars_kept():
    day, o, c = trading_day()
    now = pkt(day, c + 5)  # after the close, but only 5 minutes after it
    latest = now - timedelta(minutes=DATA_DELAY_MINUTES)
    settled_day = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    while not CAL.is_trading_day(settled_day):
        settled_day = (date.fromisoformat(settled_day) - timedelta(days=1)).isoformat()
    settled_epoch = int(pkt(settled_day, 0).timestamp())
    payload = {"s": "ok",
               "t": [settled_epoch,
                     int(pkt(day, 0).timestamp()),                # today's session: not settled yet
                     int((now - timedelta(minutes=5)).timestamp()),  # live bar
                     int((now + timedelta(hours=1)).timestamp()),    # future bar
                     "1700000000"],                                   # non-integer timestamp
               "c": [100.0, 101.0, 102.0, 103.0, 104.0],
               "v": [1000, 2000, 3000, 4000, 5000]}
    report = PilotReport(approval_id=PILOT_APPROVAL_ID)
    rows = parse_and_filter(payload, "APL", now, CAL, report)
    assert [r["session_date_pkt"] for r in rows] == [settled_day]
    assert rows[0]["close"] == 100.0 and rows[0]["volume"] == 1000.0
    assert report.dropped_unsettled == 1
    assert report.dropped_live_or_future == 2
    assert report.dropped_invalid_timestamp == 1
    assert latest < pkt(day, c)  # sanity: today's close is not yet 15 minutes old


def test_settlement_time_is_session_close_on_trading_days():
    day, o, c = trading_day()
    assert settlement_time(day, CAL) == pkt(day, c)


def test_no_data_response_yields_no_rows_and_is_reported():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    chart = FakeChart({sym: {"s": "no_data"} for sym in PILOT_SYMBOLS})
    rows, report = run_pilot(fetcher_at(now, chart), CAL, now, approval_id=PILOT_APPROVAL_ID)
    assert rows == []
    assert report.symbols_without_data == list(PILOT_SYMBOLS)


# ------------------------------------------------------------------ request limits and headers
def test_full_pilot_makes_one_robots_check_and_four_pages_with_the_approved_user_agent_only():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    chart = FakeChart()
    rows, report = run_pilot(fetcher_at(now, chart), CAL, now, approval_id=PILOT_APPROVAL_ID)
    assert report.requests_made == 5 <= PILOT_MAX_REQUESTS
    assert len(chart.calls) == 5
    for _url, headers in chart.calls:
        assert set(headers) == {"User-Agent"}
        assert headers["User-Agent"] == APPROVED_USER_AGENT


def test_the_request_cap_stops_the_run_before_it_is_exceeded():
    day, _, c = trading_day()
    now = pkt(day, c + 60)
    chart = FakeChart()
    with pytest.raises(PilotRefused, match="request cap"):
        run_pilot(fetcher_at(now, chart, requests_made=PILOT_MAX_REQUESTS - 1), CAL, now,
                  approval_id=PILOT_APPROVAL_ID)


def test_build_url_uses_only_the_documented_udf_parameters():
    url = build_url("APL", 1, 2)
    assert url == f"https://{PILOT_CHART_HOST}/history?symbol=APL&resolution=D&from=1&to=2"
