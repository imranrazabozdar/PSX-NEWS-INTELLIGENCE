"""Shared test fixtures.

The Investify client reads the good-citizen policy from its config file. Its shipped defaults are
cache-only with every collector off, which is correct for production. Existing Investify tests exercise
request logic, not the policy, so they run against a permissive policy here. The policy tests use explicit
policies.
"""

from __future__ import annotations

import pytest

from collectors import investify_good_citizen as gc


@pytest.fixture(autouse=True)
def permissive_investify_policy(monkeypatch):
    permissive = gc.parse_policy({
        "mode": "live", "kill_switch": False,
        "collectors_enabled": {"announcements": True, "fundamentals": True, "profile": True,
                               "competitors": True, "news": True},
        "min_gap_minutes": 15, "daily_ceiling": 96, "weekly_ceiling": 672, "warn_fraction": 0.99,
        "quiet_window_pkt": {"start": "00:00", "end": "23:59"},
        "cooldown_base_hours": 4, "cooldown_max_hours": 24, "breaker_threshold": 1,
        "backfill": {"paused": False, "reserve_daily": 0},
        "ttl_hours": {"announcements": 0, "fundamentals": 0, "profile": 0, "competitors": 0, "news": 0},
    })
    monkeypatch.setattr(gc, "safe_active_policy", lambda *a, **k: permissive)
    # The suite's timestamps are not the real calendar. The calendar rule is tested directly, in
    # tests/test_investify_library_calendar.py, so the wrappers are allowed here.
    monkeypatch.setattr(gc, "calendar_verdict",
                        lambda *a, **k: gc.Verdict(True, "test: calendar not under test"))
    yield permissive


@pytest.fixture(autouse=True)
def counters_follow_the_last_request(monkeypatch):
    """Existing tests write states with a last request but no budget counters. A real request always records
    its counters (finish_request does), so the test save fills them from the last request. The fail-closed
    refusal of missing counters is tested directly, on the gate, in tests/test_investify_good_citizen.py."""
    from collectors import investify_policy as pol

    real_save = pol.save_state

    def save(path, state):
        if state.last_request_utc and state.day_pkt is None:
            last = pol._utc(state.last_request_utc)
            local = last.astimezone(pol.PKT).date()
            week = (local - pol.timedelta(days=local.weekday())).isoformat()
            state = pol.replace(state, day_pkt=local.isoformat(), week_start_pkt=week)
        real_save(path, state)

    monkeypatch.setattr(pol, "save_state", save)
    yield
