"""Consent-bound polling policy for the Investify announcements source (the good-citizen client's rules).

Governed by docs/consent/investify-2026-11-12.md. Collection is under WRITTEN CONSENT, so this client is
honestly identifiable: a stable User-Agent with a contact, never a spoofed browser, never rotated identities.
The goal is minimal load and transparency, never evasion.

Every rule below is enforced in code, and every decision is a pure function of (now, state, config):

* hard floor: at most one request per 15 minutes; a longer crawl-delay from robots.txt raises it;
* Monday to Friday, 09:00-16:30 PKT only (the existing gate, engines.termux_node_runner.within_trading_hours);
* a hard daily request cap (PSXNI_INVESTIFY_DAILY_CAP, default 32), counted in Pakistan time;
* single-flight: a persisted in-flight marker refuses a second request until the first one has finished;
* Cache-Control max-age is honoured (capped at 6 hours) in addition to ETag / If-Modified-Since;
* a circuit breaker opens after repeated 403 / 429 / 503 responses, or when robots.txt begins to disallow the
  announcements path, and stays open until the next Pakistan midnight;
* a kill switch (PSXNI_INVESTIFY_KILL or PSXNI_KILL_SWITCH = "true") disables collection instantly;
* no consent before the effective date.

This module makes no network calls and writes only its own state file.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser

from engines.termux_node_runner import PKT, within_trading_hours

SOURCE_ID = "investify_announcements"
CONSENT_RECORD = "docs/consent/investify-2026-11-12.md"
CONSENT_EFFECTIVE_UTC = datetime(2026, 11, 12, tzinfo=UTC)
MIN_INTERVAL = timedelta(minutes=15)
ANNOUNCEMENTS_URL = "https://www.investify.pk/announcements"
ROBOTS_URL = "https://www.investify.pk/robots.txt"
ROBOTS_MAX_AGE = timedelta(hours=24)
BACKOFF_DEFAULT = timedelta(minutes=60)
BACKOFF_CAP = timedelta(hours=6)
FRESH_CAP = timedelta(hours=6)  # longest Cache-Control max-age honoured
IN_FLIGHT_STALE = timedelta(minutes=30)  # an in-flight marker older than this belongs to a dead run
JITTER_MIN_S = 1
JITTER_MAX_S = 180
DEFAULT_DAILY_CAP = 32
DAILY_CAP_CEILING = 96  # a sanity bound: 15-minute cycles in a trading day are ~30
BREAKER_THRESHOLD = 3  # consecutive 403 / 429 / 503 responses
ROBOTS_TOKEN = "psx-news-intelligence"  # noqa: S105 - a robots.txt user-agent token, not a secret
# One stable, honest identity: what the client is and how to reach its operator. It is never rotated and never
# imitates a browser.
USER_AGENT = ("psx-news-intelligence/0.3 (+https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE; "
              "contact: https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE/issues; "
              "consented research client for Investify; at most one request per 15 minutes)")
ATTRIBUTION = "Source: Investify (investify.pk)"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_pkt(now: datetime) -> str:
    return now.astimezone(PKT).date().isoformat()


def next_pkt_midnight_utc(now: datetime) -> datetime:
    tomorrow = now.astimezone(PKT).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=PKT).astimezone(UTC)


@dataclass(frozen=True)
class PolicyConfig:
    daily_cap: int = DEFAULT_DAILY_CAP
    breaker_threshold: int = BREAKER_THRESHOLD
    kill_switch: bool = False
    jitter_min: int = JITTER_MIN_S
    jitter_max: int = JITTER_MAX_S

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> PolicyConfig:
        env = os.environ if environ is None else environ
        kill = any(env.get(k, "").lower() == "true" for k in ("PSXNI_INVESTIFY_KILL", "PSXNI_KILL_SWITCH"))
        try:
            cap = int(env.get("PSXNI_INVESTIFY_DAILY_CAP", DEFAULT_DAILY_CAP))
        except ValueError:
            cap = DEFAULT_DAILY_CAP
        cap = min(max(cap, 1), DAILY_CAP_CEILING)  # never zero-by-typo, never above the sanity ceiling
        return cls(daily_cap=cap, kill_switch=kill)


DEFAULT_CONFIG = PolicyConfig()


@dataclass(frozen=True)
class PollState:
    last_request_utc: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    backoff_until_utc: str | None = None
    robots_txt: str | None = None
    robots_fetched_utc: str | None = None
    crawl_delay_s: int | None = None
    fresh_until_utc: str | None = None  # from Cache-Control: max-age
    day_pkt: str | None = None
    day_requests: int = 0
    consecutive_blocks: int = 0  # consecutive 403 / 429 / 503
    breaker_until_utc: str | None = None
    in_flight_since_utc: str | None = None
    week_start_pkt: str | None = None  # Monday of the current week, Pakistan time
    week_requests: int = 0  # requests counted in that week
    cooldown_until_utc: str | None = None  # multi-hour cooldown after any 403, 429 or 503
    # Per-URL conditional-request cache: {url: {etag, last_modified}} (fundamentals and profile endpoints).
    endpoint_cache: dict = field(default_factory=dict)
    # Event triggers for fundamentals: queued financial-result announcements not yet consumed.
    pending_triggers: list = field(default_factory=list)
    consumed_triggers: list = field(default_factory=list)  # announcement ids already acted on
    seen_announcements: list = field(default_factory=list)  # every announcement id seen, to detect NEW ones
    seen_result_keys: list = field(default_factory=list)  # symbol|date|headline of every result seen
    first_filled_symbols: list = field(default_factory=list)  # companies whose first fill is queued
    last_result_at: dict = field(default_factory=dict)  # symbol -> newest result time seen


def load_state(path: Path) -> PollState:
    p = Path(path)
    if not p.exists():
        return PollState()
    return PollState(**json.loads(p.read_text(encoding="utf-8")))


def save_state(path: Path, state: PollState) -> None:
    """Atomic write: a crash cannot leave a half-written state file behind."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def effective_interval(state: PollState) -> timedelta:
    """The floor, raised to robots.txt Crawl-delay when that is longer."""
    if state.crawl_delay_s:
        return max(MIN_INTERVAL, timedelta(seconds=state.crawl_delay_s))
    return MIN_INTERVAL


def requests_today(now: datetime, state: PollState) -> int:
    return state.day_requests if state.day_pkt == today_pkt(now) else 0


def may_poll(now: datetime, state: PollState, cfg: PolicyConfig = DEFAULT_CONFIG, *,
             rate_at: datetime | None = None) -> Decision:
    """Every gate that must pass before a request. Pure: no I/O.

    `rate_at` is the time the request would be sent, for the rate floor; it defaults to `now`. Before the
    jitter is applied, the job passes the LATEST possible send time, so a cycle is skipped without sleeping
    only when no send in that cycle could be valid.
    """
    if cfg.kill_switch:
        return Decision(False, "kill switch is on")
    if now < CONSENT_EFFECTIVE_UTC:
        return Decision(False, f"consent not yet effective (from {_iso(CONSENT_EFFECTIVE_UTC)})")
    if not within_trading_hours(now.astimezone(PKT)):
        return Decision(False, "outside trading hours (Mon-Fri 09:00-16:30 PKT)")
    if state.breaker_until_utc and now < _utc(state.breaker_until_utc):
        return Decision(False, f"circuit breaker open until {state.breaker_until_utc}")
    if requests_today(now, state) >= cfg.daily_cap:
        return Decision(False, f"daily request cap of {cfg.daily_cap} reached for {today_pkt(now)} (PKT)")
    if state.in_flight_since_utc and now - _utc(state.in_flight_since_utc) < IN_FLIGHT_STALE:
        return Decision(False, "single-flight: a request is already in flight")
    if state.fresh_until_utc and now < _utc(state.fresh_until_utc):
        return Decision(False, f"Cache-Control max-age: fresh until {state.fresh_until_utc}")
    if state.backoff_until_utc and now < _utc(state.backoff_until_utc):
        return Decision(False, f"backing off until {state.backoff_until_utc}")
    if state.last_request_utc:
        wait = effective_interval(state)
        if (rate_at or now) - _utc(state.last_request_utc) < wait:
            minutes = int(wait.total_seconds() // 60)
            return Decision(False, f"rate limit: at most one request per {minutes} minutes")
    return Decision(True, "allowed")


def jitter_seconds(rng: random.Random, cfg: PolicyConfig = DEFAULT_CONFIG) -> int:
    """Random delay in [jitter_min, jitter_max] seconds, applied before each request."""
    return rng.randint(cfg.jitter_min, cfg.jitter_max)


def robots_needs_refresh(now: datetime, state: PollState) -> bool:
    if state.robots_txt is None or state.robots_fetched_utc is None:
        return True
    return now - _utc(state.robots_fetched_utc) >= ROBOTS_MAX_AGE


def robots_allows(robots_txt: str, url: str) -> bool:
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(ROBOTS_TOKEN, url)


def robots_crawl_delay(robots_txt: str) -> int | None:
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    delay = rp.crawl_delay(ROBOTS_TOKEN) or rp.crawl_delay("*")
    if delay is None:
        return None
    try:
        return max(0, int(float(delay)))
    except (TypeError, ValueError):
        return None


def parse_max_age(cache_control: str | None) -> int | None:
    if not cache_control:
        return None
    for part in cache_control.split(","):
        key, _, value = part.strip().partition("=")
        if key.lower() == "max-age" and value.strip().isdigit():
            return int(value.strip())
    return None


def backoff_until(now: datetime, retry_after: str | None) -> datetime:
    """Stop for Retry-After if the site gave one, otherwise 60 minutes; clamped to 15 minutes to 6 hours."""
    delay = BACKOFF_DEFAULT
    if retry_after:
        text = retry_after.strip()
        if text.isdigit():
            delay = timedelta(seconds=int(text))
        else:
            try:
                delay = parsedate_to_datetime(text).astimezone(UTC) - now
            except (TypeError, ValueError):
                delay = BACKOFF_DEFAULT
    delay = min(max(delay, MIN_INTERVAL), BACKOFF_CAP)
    return now + delay


def registry_problem(entry: dict, source_id: str = SOURCE_ID,
                     consent_record: str = CONSENT_RECORD) -> str | None:
    """Why the registry entry does not permit collection under this consent, or None if it does.

    The database's own constraints only allow the values checked here; the consent record is the evidence."""
    if entry.get("source_id") != source_id:
        return f"entry is not {source_id}"
    if not entry.get("enabled"):
        return "source is disabled in the registry"
    if entry.get("lifecycle_status") != "APPROVED":
        return f"lifecycle is {entry.get('lifecycle_status')!r}, not APPROVED (consent-governed)"
    if entry.get("terms_status") != "approved":
        return f"terms_status is {entry.get('terms_status')!r}, not approved"
    if entry.get("access_status") != "verified_permitted":
        return f"access_status is {entry.get('access_status')!r}, not verified_permitted"
    if entry.get("access_method") != "html_permitted":
        return f"access_method is {entry.get('access_method')!r}, not html_permitted"
    if not (REPO_ROOT / consent_record).is_file():
        return f"consent record {consent_record} is missing"
    return None


def mark_in_flight(state: PollState, now: datetime) -> PollState:
    return replace(state, in_flight_since_utc=_iso(now))


def finish_request(state: PollState, now: datetime, **changes) -> PollState:
    """Record that a request was sent: the rate clock, the daily and weekly counts, and clear the in-flight
    marker."""
    day = today_pkt(now)
    count = requests_today(now, state) + 1
    local = now.astimezone(PKT).date()
    week = (local - timedelta(days=local.weekday())).isoformat()
    week_count = (state.week_requests if state.week_start_pkt == week else 0) + 1
    return replace(state, last_request_utc=_iso(now), day_pkt=day, day_requests=count,
                   week_start_pkt=week, week_requests=week_count, in_flight_since_utc=None, **changes)


def trip_breaker(state: PollState, now: datetime) -> PollState:
    return replace(state, breaker_until_utc=_iso(next_pkt_midnight_utc(now)))
