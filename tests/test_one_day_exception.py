"""The owner's one-day exception: lifts today's cap to 12, for 13 Nov 2026 only. No network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from engines import autonomous_tick as at
from engines import market_calendar as mc

ROOT = Path(__file__).resolve().parents[1]
CAL = mc.load_calendar(ROOT / "config" / "psx_calendar.json")
POLICY = json.loads((ROOT / "config" / "investify_good_citizen.json").read_text(encoding="utf-8"))
# Test data for the mechanism. The shipped policy has no live exception (13 Nov 2026 expired).
EXC = {"2026-11-13": {"ceiling": 12, "note": "Owner's one-day exception (13 Nov 2026 only)."}}
ROBOTS = "User-agent: *\nDisallow: /admin\n"


def _decide(pkt_text: str, count: int, day_pkt: str):
    local = datetime.fromisoformat(pkt_text).replace(tzinfo=at.gc.PKT).astimezone(UTC)
    control = at.Control(kill_switch=False, robots_txt=ROBOTS, robots_fetched_utc="2026-11-13T04:00:00Z",
                         daily_day_pkt=day_pkt, daily_count=count, first_live_day="2026-11-13",
                         global_last_request_utc="2026-11-13T05:00:00Z")
    return at.decide(local, control, calendar=CAL, resources=[("MEBL", "fundamentals")], done=set(),
                     first_live_day="2026-11-13", env={}, exceptions=EXC)


def test_the_shipped_policy_carries_no_live_one_day_exception():
    assert POLICY["one_day_exceptions"] == {}


def test_today_the_cap_is_lifted_so_a_third_request_is_allowed():
    # 13 Nov 2026, 11:13 PKT, inside the Friday session; two requests already made today
    d = _decide("2026-11-13 11:13", count=2, day_pkt="2026-11-13")
    assert d.action == "fetch" and d.resource == ("MEBL", "fundamentals")


def test_the_exception_does_not_apply_on_another_day():
    # 16 Nov 2026 (Monday) 10:00 PKT, the first-day cap of 2 applies again only if it is the first live day;
    # here it is the next day, so the default ceiling of 12 applies, and count 2 is still allowed.
    d = _decide("2026-11-16 10:00", count=2, day_pkt="2026-11-16")
    assert d.action == "fetch"
    # the exception's ceiling does not raise the limit beyond 12 on any day
    d = _decide("2026-11-16 10:00", count=12, day_pkt="2026-11-16")
    assert d.action == "noop" and "daily ceiling reached (12)" in d.reason


def test_the_gap_and_the_windows_still_apply_today():
    assert _decide("2026-11-13 11:13", count=2, day_pkt="2026-11-13").action == "fetch"
    assert _decide("2026-11-13 12:30", count=2, day_pkt="2026-11-13").action == "noop"  # Jumma break
    throttled = at.Control(kill_switch=False, robots_txt=ROBOTS, robots_fetched_utc="2026-11-13T04:00:00Z",
                           daily_day_pkt="2026-11-13", daily_count=2, first_live_day="2026-11-13",
                           global_last_request_utc="2026-11-13T06:05:00Z")
    local = datetime.fromisoformat("2026-11-13 11:13").replace(tzinfo=at.gc.PKT).astimezone(UTC)
    d = at.decide(local, throttled, calendar=CAL, resources=[("MEBL", "fundamentals")], done=set(),
                  first_live_day="2026-11-13", env={}, exceptions=EXC)
    assert d.action == "noop" and "throttled" in d.reason
