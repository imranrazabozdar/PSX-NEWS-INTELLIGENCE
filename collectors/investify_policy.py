"""Consent-bound polling policy for the Investify announcements source.

Governed by docs/consent/investify-2026-11-12.md. Every condition here is enforced in code:

* at most one request per 15 minutes (the last request time persists in a state file);
* Monday to Friday, 09:00-16:30 PKT only (the existing gate, engines.termux_node_runner.within_trading_hours);
* no polling before the consent's effective date;
* robots.txt is obeyed and cached for 24 hours; fetching it counts as that run's single request;
* after HTTP 429 or 503 the collector stops and waits; it never retries inside a run.

This module makes no network calls and writes only its own state file.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
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
ROBOTS_TOKEN = "psx-news-intelligence"  # noqa: S105 - a robots.txt user-agent token, not a secret
USER_AGENT = ("psx-news-intelligence/0.2 (+https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE; "
              "consented research collector for Investify; one request per 15 minutes)")
ATTRIBUTION = "Source: Investify (investify.pk)"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PollState:
    last_request_utc: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    backoff_until_utc: str | None = None
    robots_txt: str | None = None
    robots_fetched_utc: str | None = None


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


def may_poll(now: datetime, state: PollState) -> Decision:
    """Every gate that must pass before a page request. No I/O."""
    if now < CONSENT_EFFECTIVE_UTC:
        return Decision(False, f"consent not yet effective (from {_iso(CONSENT_EFFECTIVE_UTC)})")
    if not within_trading_hours(now.astimezone(PKT)):
        return Decision(False, "outside trading hours (Mon-Fri 09:00-16:30 PKT)")
    if state.backoff_until_utc and now < _utc(state.backoff_until_utc):
        return Decision(False, f"backing off after HTTP 429/503 until {state.backoff_until_utc}")
    if state.last_request_utc and now - _utc(state.last_request_utc) < MIN_INTERVAL:
        return Decision(False, "rate limit: at most one request per 15 minutes")
    return Decision(True, "allowed")


def robots_needs_refresh(now: datetime, state: PollState) -> bool:
    if state.robots_txt is None or state.robots_fetched_utc is None:
        return True
    return now - _utc(state.robots_fetched_utc) >= ROBOTS_MAX_AGE


def robots_allows(robots_txt: str, url: str) -> bool:
    rp = RobotFileParser()
    rp.parse(robots_txt.splitlines())
    return rp.can_fetch(ROBOTS_TOKEN, url)


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


def registry_problem(entry: dict) -> str | None:
    """Why the registry entry does not permit collection under this consent, or None if it does.

    The database's own constraints only allow the values checked here; the consent record is the evidence."""
    if entry.get("source_id") != SOURCE_ID:
        return f"entry is not {SOURCE_ID}"
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
    if not (REPO_ROOT / CONSENT_RECORD).is_file():
        return f"consent record {CONSENT_RECORD} is missing"
    return None


def after_request(state: PollState, now: datetime, **changes) -> PollState:
    return replace(state, last_request_utc=_iso(now), **changes)
