"""Good-citizen policy for the Investify client: structural limits, enforced in code, fail-closed.

Every request to Investify goes through `gate()` and runs inside `single_flight()`. The limits are read from
ONE policy file (config/investify_good_citizen.json):

* one request in flight at a time, process-wide (`single_flight`), and at least 15 minutes between ANY two
  requests across all resources (the shared state file);
* hard daily and weekly ceilings (Pakistan time). A warning is raised at `warn_fraction` of a ceiling.
  Reaching a
  ceiling halts all Investify traffic for that period;
* fail-closed: a missing, invalid or unreadable policy refuses; missing counters refuse; a clock that moved
  backwards refuses;
* event-driven only: nothing in this module schedules anything. Cache-first: a record younger than its TTL
  is not
  re-fetched;
* any single 403, 429 or 503 starts a multi-hour cooldown (floor 4 hours, doubling, capped) and trips the
  breaker;
* backfill yields to pending event triggers, can be paused, and keeps a daily reserve;
* cache-only mode and the kill switch refuse before anything is sent.

Pure decisions plus one process lock. No network access here."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from engines.termux_node_runner import PKT

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "investify_good_citizen.json"
ENV_KILL = ("PSXNI_INVESTIFY_KILL", "PSXNI_KILL_SWITCH")
COLLECTORS = ("announcements", "fundamentals", "profile", "competitors", "news")
BLOCK_STATUSES = frozenset({403, 429, 503})
MIN_GAP_FLOOR = timedelta(minutes=15)  # the floor; the policy may only be stricter
COOLDOWN_FLOOR = timedelta(hours=4)  # any block is a multi-hour cooldown at least
IN_FLIGHT_STALE = timedelta(minutes=30)
_FLIGHT = threading.Lock()  # process-wide: one Investify request in flight at a time


class PolicyError(ValueError):
    """The policy file is missing, unreadable, or outside its floors. The caller must refuse."""


@dataclass(frozen=True)
class Policy:
    mode: str
    kill_switch: bool
    collectors_enabled: dict[str, bool]
    min_gap: timedelta
    daily_ceiling: int
    weekly_ceiling: int
    warn_fraction: float
    quiet_start: time
    quiet_end: time
    cooldown_base: timedelta
    cooldown_max: timedelta
    breaker_threshold: int
    backfill_paused: bool
    backfill_reserve: int
    ttl: dict[str, timedelta] = field(default_factory=dict)


def _hhmm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def parse_policy(data: dict[str, Any]) -> Policy:
    try:
        mode = data["mode"]
        if mode not in ("cache_only", "live"):
            raise PolicyError(f"mode must be cache_only or live, not {mode!r}")
        enabled = {c: bool(data["collectors_enabled"].get(c, False)) for c in COLLECTORS}
        gap = timedelta(minutes=float(data["min_gap_minutes"]))
        if gap < MIN_GAP_FLOOR:
            raise PolicyError("min_gap_minutes is below the 15-minute floor")
        daily, weekly = int(data["daily_ceiling"]), int(data["weekly_ceiling"])
        if not (1 <= daily <= 96 and daily * 7 >= 1 and 1 <= weekly <= 672):
            raise PolicyError("ceilings are outside their sanity range")
        warn = float(data["warn_fraction"])
        if not 0 < warn < 1:
            raise PolicyError("warn_fraction must be between 0 and 1")
        base = timedelta(hours=float(data["cooldown_base_hours"]))
        cmax = timedelta(hours=float(data["cooldown_max_hours"]))
        if base < COOLDOWN_FLOOR or cmax < base:
            raise PolicyError("cooldown must be multi-hour (at least 4 hours) and max must not be below base")
        quiet = data["quiet_window_pkt"]
        qs, qe = _hhmm(quiet["start"]), _hhmm(quiet["end"])
        if not qs < qe:
            raise PolicyError("quiet window must start before it ends")
        ttl = {k: timedelta(hours=float(v)) for k, v in data["ttl_hours"].items()}
        return Policy(
            mode=mode, kill_switch=bool(data["kill_switch"]), collectors_enabled=enabled, min_gap=gap,
            daily_ceiling=daily, weekly_ceiling=weekly, warn_fraction=warn, quiet_start=qs, quiet_end=qe,
            cooldown_base=base, cooldown_max=cmax, breaker_threshold=int(data["breaker_threshold"]),
            backfill_paused=bool(data["backfill"]["paused"]),
            backfill_reserve=int(data["backfill"]["reserve_daily"]),
            ttl=ttl)
    except PolicyError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PolicyError(f"invalid policy: {type(exc).__name__}: {exc}") from exc


def load_policy(path: Path = POLICY_PATH) -> Policy:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"policy unreadable: {type(exc).__name__}") from exc
    return parse_policy(data)


def safe_active_policy(path: Path = POLICY_PATH) -> Policy | None:
    """The shipped policy, or None if it cannot be read or is invalid. None means: refuse everything."""
    try:
        return load_policy(path)
    except PolicyError:
        return None


@contextmanager
def single_flight() -> Iterator[bool]:
    """Yields True if this caller holds the one in-flight slot, False if another request is in flight."""
    got = _FLIGHT.acquire(blocking=False)
    try:
        yield got
    finally:
        if got:
            _FLIGHT.release()


# ------------------------------------------------------------------ week and day (Pakistan time)

def _pkt_day(now: datetime) -> str:
    return now.astimezone(PKT).date().isoformat()


def week_start(now: datetime) -> str:
    local = now.astimezone(PKT).date()
    return (local - timedelta(days=local.weekday())).isoformat()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str
    warning: str | None = None


def gate(*, now: datetime, state: Any, policy: Policy | None, endpoint: str,
         cache_age: timedelta | None = None, backfill: bool = False,
         env: dict[str, str] | None = None) -> Verdict:
    """Every rule that must pass before one request. Pure: no I/O. Refuses on any uncertainty."""
    if policy is None:
        return Verdict(False, "policy missing or invalid: fail closed")
    env = os.environ if env is None else env
    if policy.mode == "cache_only":
        return Verdict(False, "cache-only mode: zero Investify requests")
    if policy.kill_switch or any(env.get(k, "").lower() == "true" for k in ENV_KILL):
        return Verdict(False, "kill switch is on")
    if endpoint not in COLLECTORS and endpoint != "robots":
        return Verdict(False, f"unknown endpoint {endpoint!r}")
    if endpoint != "robots" and not policy.collectors_enabled.get(endpoint, False):
        return Verdict(False, f"collector {endpoint!r} is off (fail-safe default)")
    if state.last_request_utc:
        if state.day_pkt is None or state.week_start_pkt is None:
            return Verdict(False, "budget counters missing: fail closed")
        if now < _utc(state.last_request_utc):
            return Verdict(False, "clock moved backwards: fail closed")
    if state.cooldown_until_utc and now < _utc(state.cooldown_until_utc):
        return Verdict(False, f"multi-hour cooldown until {state.cooldown_until_utc}")
    if state.last_request_utc and now - _utc(state.last_request_utc) < policy.min_gap:
        minutes = int(policy.min_gap.total_seconds() // 60)
        return Verdict(False, f"queued: at most one request per {minutes} min")
    if state.in_flight_since_utc and now - _utc(state.in_flight_since_utc) < IN_FLIGHT_STALE:
        return Verdict(False, "single-flight: a request is already in flight")
    day_n = state.day_requests if state.day_pkt == _pkt_day(now) else 0
    week_n = state.week_requests if state.week_start_pkt == week_start(now) else 0
    if day_n >= policy.daily_ceiling:
        return Verdict(False, f"daily ceiling of {policy.daily_ceiling} reached: halted for the day")
    if week_n >= policy.weekly_ceiling:
        return Verdict(False, f"weekly ceiling of {policy.weekly_ceiling} reached: halted for the week")
    if cache_age is not None and endpoint in policy.ttl and cache_age < policy.ttl[endpoint]:
        return Verdict(False, f"cache-first: stored record is younger than its TTL ({endpoint})")
    if backfill:
        if policy.backfill_paused:
            return Verdict(False, "backfill is paused")
        if state.pending_triggers:
            return Verdict(False, "backfill yields to pending event-driven fetches")
        if policy.daily_ceiling - day_n <= policy.backfill_reserve:
            return Verdict(False, "backfill keeps a daily reserve for event-driven fetches")
    local = now.astimezone(PKT).time()
    if not (policy.quiet_start <= local <= policy.quiet_end):
        return Verdict(False, "outside the quiet mid-session window (no open or close bursts)")
    warning = None
    if (day_n + 1) >= policy.warn_fraction * policy.daily_ceiling:
        warning = f"WARN: {day_n + 1} of {policy.daily_ceiling} daily requests (at or above the warn level)"
    return Verdict(True, "allowed", warning)


def cooldown_until(now: datetime, consecutive_blocks: int, policy: Policy,
                   retry_after: str | None = None) -> datetime:
    """A multi-hour cooldown. The floor doubles with each consecutive block, up to the cap.

    Retry-After is honoured but never shortens the cooldown."""
    hours = min(policy.cooldown_max, policy.cooldown_base * (2 ** max(consecutive_blocks - 1, 0)))
    until = now + hours
    if retry_after:
        text = retry_after.strip()
        try:
            if text.isdigit():
                asked = now + timedelta(seconds=int(text))
            else:
                asked = parsedate_to_datetime(text).astimezone(UTC)
            until = max(until, min(asked, now + policy.cooldown_max))
        except (TypeError, ValueError):
            pass
    return until


def next_allowed_utc(now: datetime, state: Any, policy: Policy) -> datetime:
    """The earliest moment a request could be sent. Queued work waits for this; it is never sent early."""
    candidates = [now]
    if state.last_request_utc:
        candidates.append(_utc(state.last_request_utc) + policy.min_gap)
    if state.cooldown_until_utc:
        candidates.append(_utc(state.cooldown_until_utc))
    return max(candidates)


# ------------------------------------------------------------------ footprint (owner proof)

def footprint(audit_events: list[dict[str, Any]], now: datetime, policy: Policy | None) -> dict[str, Any]:
    """The owner's view, from the audit log alone.

    Requests today and this week, the share answered 304, errors, the count per resource, and WARN lines
    before a ceiling is approached."""
    requests = [e for e in audit_events if e.get("event") in ("request", "endpoint_request")]

    def pkt_day(e: dict[str, Any]) -> str:
        return _utc(e["ts_utc"]).astimezone(PKT).date().isoformat()

    today = _pkt_day(now)
    week = week_start(now)
    today_n = sum(1 for e in requests if pkt_day(e) == today)
    week_n = sum(1 for e in requests if week_start(_utc(e["ts_utc"])) == week)
    total = len(requests)
    not_modified = sum(1 for e in requests if e.get("outcome") == "not_modified" or e.get("status") == 304)
    errors = [e for e in requests if e.get("outcome") not in (None, "ok", "not_modified")]
    per_resource: dict[str, int] = {}
    for e in requests:
        key = e.get("endpoint") or e.get("cycle") or "unknown"
        per_resource[key] = per_resource.get(key, 0) + 1
    warnings = []
    if policy is not None:
        if today_n >= policy.warn_fraction * policy.daily_ceiling:
            warnings.append(f"WARN: {today_n} of {policy.daily_ceiling} daily requests today")
        if week_n >= policy.warn_fraction * policy.weekly_ceiling:
            warnings.append(f"WARN: {week_n} of {policy.weekly_ceiling} weekly requests this week")
    return {
        "requests_today": today_n, "requests_this_week": week_n, "requests_total": total,
        "share_304_percent": round(100 * not_modified / total, 1) if total else None,
        "errors": len(errors), "per_resource": per_resource, "warnings": warnings,
    }
