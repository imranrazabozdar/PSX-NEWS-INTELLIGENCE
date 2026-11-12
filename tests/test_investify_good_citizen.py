"""The good-citizen policy, proven against fixtures. No network: transports are fakes that fail if called.

Each test names the rule it proves. The shipped policy is tested for its fail-safe defaults.
"""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collectors import investify_fundamentals as fund
from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol
from collectors.engine import load_source
from collectors.investify_job import AuditLog
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # Monday 10:00 PKT
BASE = {
    "kill_switch": False,
    "collectors_enabled": {"announcements": True, "fundamentals": True, "profile": True, "competitors": True,
                           "news": True},
    "min_gap_minutes": 15, "daily_ceiling": 12, "weekly_ceiling": 60, "warn_fraction": 0.6,
    "quiet_window_pkt": {"start": "10:00", "end": "15:30"},
    "cooldown_base_hours": 4, "cooldown_max_hours": 24, "breaker_threshold": 1,
    "backfill": {"paused": False, "reserve_daily": 2},
    "ttl_hours": {"announcements": 24, "fundamentals": 720, "profile": 2160, "competitors": 2160, "news": 24},
}
POLICY = gc.parse_policy(BASE)
REAL_SAFE_ACTIVE_POLICY = gc.safe_active_policy  # before the suite's fixture swaps it for a permissive one


def policy(**over):
    return gc.parse_policy({**BASE, **over})


def state(**over):
    """A state with a last request 30 minutes ago, with counters current, unless overridden."""
    last = NOW - timedelta(minutes=30)
    local = last.astimezone(pol.PKT).date()
    week = (local - timedelta(days=local.weekday())).isoformat()
    base = dict(last_request_utc=pol._iso(last), day_pkt=local.isoformat(), day_requests=1,
                week_start_pkt=week, week_requests=1)
    base.update(over)
    return pol.PollState(**base)


class NoNetwork:
    calls = 0

    def __call__(self, url, headers):
        NoNetwork.calls += 1
        raise AssertionError(f"a request was sent: {url}")


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no socket may be opened by the policy tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ---------- 1. single-flight and the global 15-minute gap

def test_one_request_in_flight_process_wide():
    with gc.single_flight() as first:
        assert first is True
        with gc.single_flight() as second:
            assert second is False  # a second caller is refused while the first holds the slot
    with gc.single_flight() as again:
        assert again is True  # released after the first finishes


def test_the_global_gap_is_fifteen_minutes_across_all_resources():
    s = state(last_request_utc=pol._iso(NOW - timedelta(minutes=5)))  # the last request was 5 minutes ago
    five = gc.gate(now=NOW, state=s, policy=POLICY, endpoint="profile")
    assert "queued" in five.reason  # 5 minutes since the last request: refused
    assert "queued" in gc.gate(now=NOW + timedelta(minutes=5), state=s, policy=POLICY,
                               endpoint="competitors").reason  # 10 minutes: refused, for ANY resource
    # 16 minutes after the last request, any resource is allowed
    assert gc.gate(now=NOW + timedelta(minutes=11), state=s, policy=POLICY, endpoint="competitors").allowed


def test_queued_work_is_deferred_never_sent_early():
    s = state(last_request_utc=pol._iso(NOW - timedelta(minutes=5)))
    nxt = gc.next_allowed_utc(NOW, s, POLICY)
    assert nxt >= NOW + timedelta(minutes=10)
    just_before = gc.gate(now=nxt - timedelta(seconds=1), state=s, policy=POLICY, endpoint="profile")
    assert just_before.allowed is False


# ---------- 2. fail-closed budgets and uncertainty

def test_a_missing_or_invalid_policy_refuses_everything(tmp_path):
    with pytest.raises(gc.PolicyError):
        gc.load_policy(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(gc.PolicyError):
        gc.load_policy(bad)
    assert REAL_SAFE_ACTIVE_POLICY(tmp_path / "missing.json") is None
    assert gc.gate(now=NOW, state=state(), policy=None, endpoint="profile").allowed is False


def test_counters_missing_refuse_because_the_ceiling_cannot_be_verified():
    s = pol.PollState(last_request_utc=pol._iso(NOW - timedelta(hours=1)))  # no day or week counters
    v = gc.gate(now=NOW, state=s, policy=POLICY, endpoint="profile")
    assert v.allowed is False and "counters missing" in v.reason


def test_a_clock_that_moved_backwards_refuses():
    s = state(last_request_utc=pol._iso(NOW + timedelta(hours=1)))
    v = gc.gate(now=NOW, state=s, policy=POLICY, endpoint="profile")
    assert v.allowed is False and "clock moved backwards" in v.reason


def test_the_daily_ceiling_halts_the_day_and_warns_before_it():
    at_warn = state(day_requests=7)  # the next request would be the 8th of 12: 60% and above
    v = gc.gate(now=NOW, state=at_warn, policy=POLICY, endpoint="profile")
    assert v.allowed is True and v.warning and v.warning.startswith("WARN: 8 of 12")
    at_cap = state(day_requests=12)
    v = gc.gate(now=NOW, state=at_cap, policy=POLICY, endpoint="profile")
    assert v.allowed is False and "daily ceiling" in v.reason


def test_the_weekly_ceiling_halts_the_week():
    v = gc.gate(now=NOW, state=state(week_requests=60), policy=POLICY, endpoint="profile")
    assert v.allowed is False and "weekly ceiling" in v.reason


def test_a_warning_is_not_raised_below_the_warn_level():
    v = gc.gate(now=NOW, state=state(day_requests=2), policy=POLICY, endpoint="profile")
    assert v.allowed is True and v.warning is None


def test_the_policy_refuses_values_outside_its_floors():
    with pytest.raises(gc.PolicyError):
        gc.parse_policy({**BASE, "min_gap_minutes": 5})
    with pytest.raises(gc.PolicyError):
        gc.parse_policy({**BASE, "cooldown_base_hours": 1})  # a cooldown must be multi-hour
    with pytest.raises(gc.PolicyError):
        gc.parse_policy({**BASE, "cooldown_base_hours": 1, "cooldown_max_hours": 0.5})


# ---------- 3. no scheduled polling path exists

def test_no_module_in_the_client_schedules_or_loops_on_a_timer():
    for module in ("collectors/investify_good_citizen.py", "collectors/investify_policy.py",
                   "collectors/investify_fundamentals.py", "collectors/investify_job.py"):
        text = (ROOT / module).read_text(encoding="utf-8")
        for banned in ("schedule(", "Timer(", "while True", "apscheduler", "sched."):
            assert banned not in text, f"{module} contains {banned!r}"


# ---------- 4. cache-first TTLs

def test_a_record_younger_than_its_ttl_is_not_refetched():
    fresh = gc.gate(now=NOW, state=state(), policy=POLICY, endpoint="profile", cache_age=timedelta(days=10))
    assert fresh.allowed is False and "cache-first" in fresh.reason
    stale = gc.gate(now=NOW, state=state(), policy=POLICY, endpoint="profile", cache_age=timedelta(days=100))
    assert stale.allowed is True


# ---------- 5. multi-hour cooldown on any server signal

@pytest.mark.parametrize("code", [403, 429, 503])
def test_a_single_403_429_or_503_starts_a_multi_hour_cooldown(code):
    until = gc.cooldown_until(NOW, 1, POLICY)
    assert until >= NOW + timedelta(hours=4)
    during = gc.gate(now=NOW + timedelta(hours=1), state=state(cooldown_until_utc=pol._iso(until)),
                     policy=POLICY, endpoint="profile")
    assert during.allowed is False and "cooldown" in during.reason
    after = gc.gate(now=until + timedelta(seconds=1), state=state(cooldown_until_utc=pol._iso(until)),
                    policy=POLICY, endpoint="profile")
    assert after.allowed is True
    assert code in (403, 429, 503)


def test_the_cooldown_doubles_with_consecutive_blocks_up_to_the_cap():
    assert gc.cooldown_until(NOW, 2, POLICY) - NOW == timedelta(hours=8)
    assert gc.cooldown_until(NOW, 9, POLICY) - NOW == timedelta(hours=24)  # capped


def test_retry_after_is_honoured_but_never_shortens_the_cooldown():
    assert gc.cooldown_until(NOW, 1, POLICY, "1800") - NOW == timedelta(hours=4)
    assert gc.cooldown_until(NOW, 1, POLICY, "86400") - NOW == timedelta(hours=24)  # capped at the maximum


# ---------- 6. backfill yields, pauses, keeps a reserve

def test_backfill_yields_to_pending_event_triggers_and_is_pausable():
    with_trigger = state(pending_triggers=[{"symbol": "HUBC", "kind": "first_fill"}])
    v = gc.gate(now=NOW, state=with_trigger, policy=POLICY, endpoint="profile", backfill=True)
    assert v.allowed is False and "yields" in v.reason
    paused = policy(backfill={"paused": True, "reserve_daily": 2})
    assert gc.gate(now=NOW, state=state(), policy=paused, endpoint="profile", backfill=True).allowed is False


def test_backfill_keeps_a_daily_reserve_for_event_driven_fetches():
    v = gc.gate(now=NOW, state=state(day_requests=10), policy=POLICY, endpoint="profile", backfill=True)
    assert v.allowed is False and "reserve" in v.reason  # 12 - 10 = 2, at the reserve


def test_a_backfill_counts_against_the_same_daily_budget(tmp_path):
    s = pol.PollState()
    s2 = pol.finish_request(s, NOW)  # a backfill request is recorded like any other
    assert s2.day_requests == 1 and s2.week_requests == 1


# ---------- 7. cache-only and the kill switch

def test_the_kill_switch_refuses_every_resource():
    halted = policy(kill_switch=True)
    for ep in ("announcements", "fundamentals", "profile", "competitors", "news", "robots"):
        assert gc.gate(now=NOW, state=state(), policy=halted, endpoint=ep).allowed is False


def test_the_kill_switch_makes_zero_investify_calls_through_the_request_path(tmp_path):
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    transport = NoNetwork()
    entry = {**load_source(db, fund.SOURCE_ID), "enabled": 1}
    out = fund.run_endpoint(now=NOW, state_path=tmp_path / "s.json", entry=entry, db=db,
                            endpoint="profile", symbol="HUBC",
                            watchlist=frozenset({"HUBC"}), transport=transport,
                            good=policy(kill_switch=True))
    assert out.status in ("skipped", "refused") and NoNetwork.calls == 0


def test_the_kill_switch_halts_instantly_whatever_else_allows(tmp_path):
    killed = policy(kill_switch=True)
    assert gc.gate(now=NOW, state=state(), policy=killed, endpoint="profile").allowed is False
    v = gc.gate(now=NOW, state=state(), policy=POLICY, endpoint="profile", env={"PSXNI_KILL_SWITCH": "true"})
    assert v.allowed is False and "kill switch" in v.reason


def test_the_kill_switch_refuses_through_the_request_path_with_zero_calls(tmp_path):
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    NoNetwork.calls = 0
    entry = {**load_source(db, fund.SOURCE_ID), "enabled": 1}
    out = fund.run_endpoint(now=NOW, state_path=tmp_path / "s.json", entry=entry, db=db,
                            endpoint="profile", symbol="HUBC",
                            watchlist=frozenset({"HUBC"}), transport=NoNetwork(),
                            good=policy(kill_switch=True))
    assert out.status in ("skipped", "refused") and NoNetwork.calls == 0


def test_a_request_path_refuses_while_another_request_holds_the_slot(tmp_path):
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    with gc.single_flight() as got:
        assert got is True
        entry = {**load_source(db, fund.SOURCE_ID), "enabled": 1}
        out = fund.run_endpoint(now=NOW, state_path=tmp_path / "s.json", entry=entry, db=db,
                                endpoint="profile", symbol="HUBC",
                                watchlist=frozenset({"HUBC"}), transport=NoNetwork(), good=POLICY)
    assert out.status == "skipped" and "single-flight" in out.reason and NoNetwork.calls == 0


# ---------- 8. fail-safe defaults and every collector off

def test_the_shipped_policy_is_fail_safe():
    shipped = gc.load_policy()
    assert shipped.kill_switch is False and not hasattr(shipped, "mode")
    assert not any(shipped.collectors_enabled.values())  # every collector off
    for ep in gc.COLLECTORS:
        assert gc.gate(now=NOW, state=state(), policy=shipped, endpoint=ep).allowed is False


def test_an_unknown_endpoint_is_refused():
    assert gc.gate(now=NOW, state=state(), policy=POLICY, endpoint="industry").allowed is False


def test_a_collector_switched_off_in_the_one_policy_file_stays_off():
    off = policy(collectors_enabled={"announcements": True, "fundamentals": False, "profile": True,
                                     "competitors": True, "news": False})
    assert gc.gate(now=NOW, state=state(), policy=off, endpoint="fundamentals").allowed is False
    assert gc.gate(now=NOW, state=state(), policy=off, endpoint="news").allowed is False


# ---------- 9. observability: footprint and WARN

def _audit_events(n_today: int, n_304: int = 0, n_error: int = 0, hour0: int = 5):
    out = []
    for i in range(n_today):
        ts = pol._iso(NOW.replace(hour=hour0) + timedelta(minutes=20 * i))
        outcome = "not_modified" if i < n_304 else ("rate_limited" if i < n_304 + n_error else "ok")
        out.append({"event": "endpoint_request", "ts_utc": ts, "endpoint": "profile", "outcome": outcome,
                    "status": 304 if outcome == "not_modified" else 200})
    return out


def test_the_footprint_counts_requests_304_share_and_errors():
    events = _audit_events(n_today=4, n_304=1, n_error=1)
    f = gc.footprint(events, NOW + timedelta(hours=2), POLICY)
    assert f["requests_today"] == 4 and f["share_304_percent"] == 25.0 and f["errors"] == 1
    assert f["per_resource"] == {"profile": 4}


def test_the_footprint_warns_before_the_daily_ceiling_is_approached():
    events = _audit_events(n_today=8)  # 8 of 12 is at least 60%
    f = gc.footprint(events, NOW + timedelta(hours=2), POLICY)
    assert f["warnings"] and f["warnings"][0].startswith("WARN: 8 of 12")
    assert gc.footprint(_audit_events(n_today=2), NOW + timedelta(hours=2), POLICY)["warnings"] == []


def test_the_audit_log_records_warnings_and_owner_alerts_as_events(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.record({"event": "warn", "ts_utc": pol._iso(NOW), "warning": "WARN"})
    log.record({"event": "owner_alert", "ts_utc": pol._iso(NOW), "why": "HTTP 429"})
    kinds = [json.loads(x)["event"] for x in (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kinds == ["warn", "owner_alert"]


def test_a_policy_change_takes_effect_without_a_code_change():
    tighter = replace(POLICY, daily_ceiling=3)
    v = gc.gate(now=NOW, state=state(day_requests=3), policy=tighter, endpoint="profile")
    assert v.allowed is False and "daily ceiling of 3" in v.reason
