"""Offline tests for collectors.permissioned_fetch. No network: transport and clock are fakes."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from collectors.permissioned_fetch import (
    APPROVED_USER_AGENT,
    DATA_DELAY_MINUTES,
    JITTER_MAX_SECONDS,
    JITTER_MIN_SECONDS,
    DelayRefused,
    OffPeakRefused,
    PermissionedFetcher,
    PermissionRefused,
    is_off_peak,
    jitter_seconds,
)
from engines.market_calendar import load_calendar

CAL = load_calendar()
OLD = datetime(2026, 11, 1, tzinfo=UTC)  # settled data, well outside the 15-minute delay
PKT = timezone(timedelta(hours=5))
HOST = "dps.psx.com.pk"


def trading_day_after(start: str) -> tuple[str, int, int]:
    """First trading day on/after `start` with recorded hours: (day, open_min, close_min)."""
    d = date.fromisoformat(start)
    for _ in range(60):
        day = d.isoformat()
        if CAL.is_trading_day(day) and CAL.hours(day):
            o, c = CAL.hours(day)
            return day, o, c
        d += timedelta(days=1)
    raise AssertionError("no trading day found in calendar")


def pkt_to_utc(day: str, hour: int, minute: int) -> datetime:
    local = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=PKT)
    return (local + timedelta(hours=hour, minutes=minute)).astimezone(UTC)


class FakeTransport:
    def __init__(self, responses: dict[str, tuple[int, bytes]] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        return self.responses.get(url, (404, b""))


def make_fetcher(now_utc: datetime, transport: FakeTransport, sleeps: list[float] | None = None,
                 seed: int = 7) -> PermissionedFetcher:
    sleeps = sleeps if sleeps is not None else []
    return PermissionedFetcher(
        allowed_hosts=frozenset({HOST}), calendar=CAL, transport=transport,
        rng=random.Random(seed),  # noqa: S311 - jitter, not security
        sleep=sleeps.append, now=lambda: now_utc)


# ------------------------------------------------------------------ identity
def test_user_agent_is_exactly_the_approved_string():
    assert APPROVED_USER_AGENT == "PSX-NEWS-INTELLIGENCE research bot, contact owner"


def test_no_browser_identity_or_extra_headers_are_sent():
    day, o, c = trading_day_after("2026-11-10")
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/x": (200, b"ok")})
    f = make_fetcher(pkt_to_utc(day, 0, 0) + timedelta(days=0), t)
    f.fetch(f"https://{HOST}/x", data_as_of_utc=OLD)
    for _, headers in t.calls:
        assert set(headers) == {"User-Agent"}
        assert headers["User-Agent"] == APPROVED_USER_AGENT
        low = headers["User-Agent"].lower()
        assert not any(b in low for b in ("mozilla", "chrome", "safari", "firefox", "python", "playwright"))


# ------------------------------------------------------------------ jitter
def test_jitter_stays_within_3_5_and_8_5_seconds():
    rng = random.Random(1)  # noqa: S311 - seeded jitter in a test, not a security value
    values = [jitter_seconds(rng) for _ in range(5000)]
    assert min(values) >= JITTER_MIN_SECONDS
    assert max(values) <= JITTER_MAX_SECONDS
    assert max(values) - min(values) > 4.0  # actually randomised, not a constant


def test_a_delay_is_applied_before_every_request_including_robots():
    day, _, _ = trading_day_after("2026-11-10")
    sleeps: list[float] = []
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a"),
                       f"https://{HOST}/b": (200, b"b")})
    f = make_fetcher(pkt_to_utc(day, 0, 0), t, sleeps)
    f.fetch(f"https://{HOST}/a", data_as_of_utc=OLD)
    f.fetch(f"https://{HOST}/b", data_as_of_utc=OLD)
    assert len(t.calls) == 3  # robots once, then two pages
    assert len(sleeps) == 3   # one delay per request
    assert all(JITTER_MIN_SECONDS <= s <= JITTER_MAX_SECONDS for s in sleeps)


# ------------------------------------------------------------------ timing
def test_collection_refused_during_trading_hours():
    day, o, c = trading_day_after("2026-11-10")
    during = pkt_to_utc(day, o // 60, o % 60) + timedelta(minutes=5)
    assert not is_off_peak(during, CAL)
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a")})
    with pytest.raises(OffPeakRefused):
        make_fetcher(during, t).fetch(f"https://{HOST}/a", data_as_of_utc=OLD)
    assert t.calls == []  # no network access at all


def test_collection_allowed_after_market_close():
    day, o, c = trading_day_after("2026-11-10")
    after = pkt_to_utc(day, c // 60, c % 60) + timedelta(minutes=1)
    assert is_off_peak(after, CAL)
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a")})
    assert make_fetcher(after, t).fetch(f"https://{HOST}/a", data_as_of_utc=OLD) == b"a"


def test_collection_allowed_before_market_open_and_on_non_trading_days():
    day, o, c = trading_day_after("2026-11-10")
    before = pkt_to_utc(day, 0, 1)
    assert is_off_peak(before, CAL)
    holiday = next(d for d in (date(2026, 11, 9) + timedelta(days=i) for i in range(30))
                   if not CAL.is_trading_day(d.isoformat()))
    assert is_off_peak(pkt_to_utc(holiday.isoformat(), 12, 0), CAL)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        is_off_peak(datetime(2026, 11, 10, 12, 0), CAL)


# ------------------------------------------------------------------ host and robots
def test_hosts_outside_the_approved_list_are_refused_without_network():
    day, _, _ = trading_day_after("2026-11-10")
    t = FakeTransport()
    f = make_fetcher(pkt_to_utc(day, 0, 0), t)
    with pytest.raises(PermissionRefused, match="not in the approved list"):
        f.fetch("https://example.com/x", data_as_of_utc=OLD)
    assert t.calls == []


def test_plain_http_is_refused():
    day, _, _ = trading_day_after("2026-11-10")
    with pytest.raises(PermissionRefused, match="only https"):
        make_fetcher(pkt_to_utc(day, 0, 0), FakeTransport()).fetch(f"http://{HOST}/x", data_as_of_utc=OLD)


def test_robots_disallow_stops_the_request():
    day, _, _ = trading_day_after("2026-11-10")
    robots = b"User-agent: *\nDisallow: /private/\n"
    t = FakeTransport({f"https://{HOST}/robots.txt": (200, robots),
                       f"https://{HOST}/private/x": (200, b"secret")})
    with pytest.raises(PermissionRefused, match="robots.txt disallows"):
        make_fetcher(pkt_to_utc(day, 0, 0), t).fetch(f"https://{HOST}/private/x", data_as_of_utc=OLD)
    assert all("/private/x" not in url for url, _ in t.calls)


def test_robots_refusal_status_stops_collection_for_that_host():
    day, _, _ = trading_day_after("2026-11-10")
    t = FakeTransport({f"https://{HOST}/robots.txt": (403, b"")})
    with pytest.raises(PermissionRefused, match="robots.txt refused"):
        make_fetcher(pkt_to_utc(day, 0, 0), t).fetch(f"https://{HOST}/a", data_as_of_utc=OLD)


def test_robots_is_fetched_once_per_host():
    day, _, _ = trading_day_after("2026-11-10")
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a"),
                       f"https://{HOST}/b": (200, b"b")})
    f = make_fetcher(pkt_to_utc(day, 0, 0), t)
    f.fetch(f"https://{HOST}/a", data_as_of_utc=OLD)
    f.fetch(f"https://{HOST}/b", data_as_of_utc=OLD)
    assert sum(1 for u, _ in t.calls if u.endswith("/robots.txt")) == 1


def test_oversized_response_is_refused():
    day, _, _ = trading_day_after("2026-11-10")
    big = b"x" * (5_000_001)
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, big)})
    with pytest.raises(PermissionRefused, match="larger than"):
        make_fetcher(pkt_to_utc(day, 0, 0), t).fetch(f"https://{HOST}/a", data_as_of_utc=OLD)


def test_empty_allow_list_is_rejected():
    with pytest.raises(ValueError):
        PermissionedFetcher(allowed_hosts=frozenset(), calendar=CAL, transport=FakeTransport())


# ------------------------------------------------------------------ 15-minute exchange delay
def test_data_inside_the_15_minute_delay_is_refused_with_no_network_access():
    day, _, _ = trading_day_after("2026-11-10")
    now = pkt_to_utc(day, 0, 0)  # off-peak, so only the delay rule can refuse
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a")})
    f = make_fetcher(now, t)
    with pytest.raises(DelayRefused):
        f.fetch(f"https://{HOST}/a", data_as_of_utc=now - timedelta(minutes=DATA_DELAY_MINUTES - 1))
    with pytest.raises(DelayRefused):
        f.fetch(f"https://{HOST}/a", data_as_of_utc=now)  # live data
    assert t.calls == []


def test_data_exactly_15_minutes_old_is_permitted():
    day, _, _ = trading_day_after("2026-11-10")
    now = pkt_to_utc(day, 0, 0)
    t = FakeTransport({f"https://{HOST}/robots.txt": (404, b""), f"https://{HOST}/a": (200, b"a")})
    body = make_fetcher(now, t).fetch(f"https://{HOST}/a",
                                      data_as_of_utc=now - timedelta(minutes=DATA_DELAY_MINUTES))
    assert body == b"a"


def test_future_dated_data_is_refused():
    day, _, _ = trading_day_after("2026-11-10")
    now = pkt_to_utc(day, 0, 0)
    with pytest.raises(DelayRefused):
        make_fetcher(now, FakeTransport()).fetch(f"https://{HOST}/a",
                                                 data_as_of_utc=now + timedelta(hours=1))


def test_the_data_as_of_argument_is_required_and_timezone_aware():
    day, _, _ = trading_day_after("2026-11-10")
    now = pkt_to_utc(day, 0, 0)
    f = make_fetcher(now, FakeTransport())
    with pytest.raises(TypeError):
        f.fetch(f"https://{HOST}/a")  # no data_as_of_utc given
    with pytest.raises(ValueError):
        f.fetch(f"https://{HOST}/a", data_as_of_utc=datetime(2026, 11, 1))  # naive
