"""Investify fundamentals, company profile, competitors and industry, under written consent.

Governed by docs/consent/investify-fundamentals-2026-11-12.md. It shares the announcements collector's policy
(collectors/investify_policy.py): one request per 15 minutes across ALL Investify endpoints (one state file),
trading hours, daily cap, circuit breaker, single-flight, kill switch, robots.txt, ETag / If-Modified-Since,
backoff, audit log and an honest User-Agent.

Two rules are enforced here, in code, not only in documentation:

(a) FUNDAMENTALS are fetched ONLY when a NEW financial-result announcement for that symbol has been queued by
    the announcement collector (`enqueue_from_announcements`). No qualifying announcement means no request.
(b) PROFILE, COMPETITORS and INDUSTRY are backfilled ONCE per company. A later fetch happens only through an
    explicit manual refresh (`manual=True`), never from the scheduler. Their stored copy is stale after
    90 days,
    and staleness alone never triggers a request.

Every stored record carries source = "investify.pk" and the attribution string.

Endpoint paths are NOT yet confirmed by the owner (see the consent record). Until a path is confirmed, the
endpoint is refused without any request.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from collectors import investify_policy as pol
from collectors.investify_job import (
    BLOCK_STATUSES,
    AuditLog,
    RunOutcome,
    Transport,
    _outcome_label,
    default_transport,
)
from database.repositories import record_source_item
from engines import investify_collector as ic

SOURCE_ID = "investify_fundamentals"
SOURCE_NAME = "investify.pk"  # the source recorded on every stored record
CONSENT_RECORD = "docs/consent/investify-fundamentals-2026-11-12.md"
EVENT_CATEGORY = "financial_results"  # the only announcement category that triggers a fundamentals refresh
TRIGGER_MAX_AGE = timedelta(days=3)  # an older financial result is marked seen but not queued
PROFILE_STALE_AFTER = timedelta(days=90)  # stale copies are reported, never auto-refetched
SYMBOL = re.compile(r"^[A-Z0-9&-]{1,20}$")
SITE = "https://www.investify.pk"


@dataclass(frozen=True)
class Endpoint:
    name: str  # fundamentals | profile | competitors | industry
    path_template: str | None  # e.g. "/company/{symbol}/..."; None until the owner confirms it
    cadence: str  # "announcement" (rule a) or "backfill_once" (rule b)


# Paths confirmed by the owner (2026-11-12): fundamentals and competitors. The profile path is INFERRED
# and stays unset (None) until one conditional GET confirms it (a 404 leaves it unset). There is no
# industry endpoint: sector or industry fields are derived from the profile or competitors payload.
ENDPOINTS: dict[str, Endpoint] = {
    "fundamentals": Endpoint("fundamentals", "/company/{symbol}/fundamentals", "announcement"),
    "competitors": Endpoint("competitors", "/company/{symbol}/competitors", "backfill_once"),
    "profile": Endpoint("profile", None, "backfill_once"),
}


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- rule (a): event triggers

def enqueue_from_announcements(state: pol.PollState, records: list[ic.AnnouncementRecord], *,
                               now: datetime) -> tuple[pol.PollState, list[dict[str, Any]]]:
    """Queue ONE fundamentals refresh per NEW financial-result announcement. Pure: returns the new state.

    An announcement id is seen once. Only a financial-result announcement published within TRIGGER_MAX_AGE is
    queued; everything else is recorded as seen and ignored."""
    seen = set(state.seen_announcements)
    pending = list(state.pending_triggers)
    done = set(state.consumed_triggers)
    queued: list[dict[str, Any]] = []
    for rec in records:
        announcement_id = rec.content_sha256
        if announcement_id in seen:
            continue
        seen.add(announcement_id)
        if rec.category != EVENT_CATEGORY:
            continue
        if now - _utc(rec.announced_at_utc) > TRIGGER_MAX_AGE:
            continue  # an old result is not news: recorded as seen, not queued
        if any(t["announcement_id"] == announcement_id for t in pending) or announcement_id in done:
            continue
        item = {"symbol": rec.symbol, "announcement_id": announcement_id,
                "announced_at_utc": rec.announced_at_utc, "title": rec.title, "queued_utc": _iso(now)}
        pending.append(item)
        queued.append(item)
    new_state = replace(state, seen_announcements=sorted(seen), pending_triggers=pending)
    return new_state, queued


def pending_trigger(state: pol.PollState, symbol: str) -> dict[str, Any] | None:
    """The oldest pending financial-result trigger for this symbol, if any."""
    for item in state.pending_triggers:
        if item["symbol"] == symbol:
            return item
    return None


# ---------------------------------------------------------------- storage

def _stored_record(db: Any, symbol: str, endpoint: str) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT source_item_id, collected_at_utc FROM source_items "
        "WHERE source_id = ? AND external_id = ?", (SOURCE_ID, f"{symbol}:{endpoint}"))
    return rows[0] if rows else None


def _store(db: Any, *, url: str, symbol: str, endpoint: str, body: bytes, collected_at_utc: str,
           http_status: int, trigger: dict[str, Any] | None) -> str:
    metadata = {
        "source": SOURCE_NAME,
        "attribution": pol.ATTRIBUTION,
        "symbol": symbol,
        "endpoint": endpoint,
        "fetched_at_utc": collected_at_utc,
        "triggering_announcement_id": trigger["announcement_id"] if trigger else None,
        "triggering_announced_at_utc": trigger["announced_at_utc"] if trigger else None,
        "body_bytes": len(body),
    }
    out = record_source_item(
        db, source_id=SOURCE_ID, collected_at_utc=collected_at_utc, url=url,
        external_id=f"{symbol}:{endpoint}",
        # STRUCTURED FIELDS ONLY (owner, 2026-11-12): the raw body is never persisted, only its hash.
        content_hash=hashlib.sha256(body).hexdigest(),
        title=f"{symbol} {endpoint} (Investify)", published_at_utc=None, published_at_raw=None,
        excerpt=None,
        provenance={"original_url": url, "retrieval_method": "html", "http_status": http_status,
                    "document_type": endpoint, "publication_time_status": "unknown",
                    "source_metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True)},
    )
    return out.outcome


# ---------------------------------------------------------------- the single request

def run_endpoint(*, now: datetime, state_path: Path, entry: dict[str, Any], db: Any,
                 endpoint: str, symbol: str, watchlist: frozenset[str],
                 endpoints: dict[str, Endpoint] = ENDPOINTS, manual: bool = False,
                 transport: Transport = default_transport,
                 cfg: pol.PolicyConfig = pol.DEFAULT_CONFIG,
                 sleep=lambda s: None, rng: random.Random | None = None,
                 audit: AuditLog | None = None) -> RunOutcome:
    """Fetch ONE Investify endpoint for ONE symbol, if every rule allows it. At most one HTTP request."""
    audit = audit or AuditLog()
    rng = rng or random.SystemRandom()

    def skip(reason: str) -> RunOutcome:
        audit.record({"event": "endpoint_skip", "ts_utc": _iso(now), "endpoint": endpoint, "symbol": symbol,
                      "reason": reason})
        return RunOutcome("skipped", reason)

    if cfg.kill_switch:
        return skip("kill switch is on")
    problem = pol.registry_problem(entry, source_id=SOURCE_ID, consent_record=CONSENT_RECORD)
    if problem:
        return RunOutcome("refused", problem)
    if endpoint not in endpoints:
        return RunOutcome("refused", f"unknown endpoint {endpoint!r}")
    spec = endpoints[endpoint]
    if spec.path_template is None:
        return RunOutcome("refused", f"{endpoint} path is not yet confirmed by the owner; no request made")
    if not SYMBOL.match(symbol) or symbol not in watchlist:
        return RunOutcome("refused", f"{symbol!r} is not a watchlist symbol")

    state = pol.load_state(state_path)
    trigger: dict[str, Any] | None = None
    if spec.cadence == "announcement":  # rule (a)
        if manual:
            return RunOutcome("refused",
                              "fundamentals are refreshed only by a new announcement, not manually")
        trigger = pending_trigger(state, symbol)
        if trigger is None:
            return skip(f"no pending financial-result announcement for {symbol}")
    else:  # rule (b): backfill once; manual refresh only afterwards
        existing = _stored_record(db, symbol, endpoint)
        if existing is not None and not manual:
            return skip(f"{endpoint} for {symbol} already backfilled; refresh is manual only")

    if pol.robots_needs_refresh(now, state):
        return skip("robots.txt copy is missing or older than 24 hours; the announcements job refreshes it")

    url = SITE + spec.path_template.format(symbol=symbol)
    if not pol.robots_allows(state.robots_txt or "", url):
        return skip(f"robots.txt disallows {url}")

    latest_send = now + timedelta(seconds=cfg.jitter_max)
    decision = pol.may_poll(now, state, cfg, rate_at=latest_send)
    if not decision.allowed:
        return skip(decision.reason)
    jitter = pol.jitter_seconds(rng, cfg)
    sleep(jitter)
    send = now + timedelta(seconds=jitter)
    decision = pol.may_poll(send, state, cfg)
    if not decision.allowed:
        return skip(f"after {jitter}s jitter: {decision.reason}")

    state = pol.mark_in_flight(state, send)
    pol.save_state(state_path, state)

    cache = state.endpoint_cache.get(url, {})
    headers = {"User-Agent": pol.USER_AGENT, "Accept": "text/html"}
    if cache.get("etag"):
        headers["If-None-Match"] = cache["etag"]
    if cache.get("last_modified"):
        headers["If-Modified-Since"] = cache["last_modified"]

    status, resp_headers, body, error = None, {}, b"", None
    try:
        status, resp_headers, body = transport(url, headers)
    except (OSError, TimeoutError) as exc:  # URLError is an OSError
        error = type(exc).__name__
    audit.record({"event": "endpoint_request", "ts_utc": _iso(send), "endpoint": endpoint, "symbol": symbol,
                  "url": url, "status": status, "outcome": _outcome_label(status, error),
                  "bytes": len(body), "jitter_s": jitter, "source": SOURCE_NAME,
                  "triggering_announcement_id": trigger["announcement_id"] if trigger else None,
                  "manual": manual, "user_agent": pol.USER_AGENT, "error": error})

    if error is not None:
        pol.save_state(state_path, pol.finish_request(state, send))
        return RunOutcome("failed", f"network error ({error}); no retry", http_requests=1)

    if status == 304:
        # a recorded no-op: nothing is stored, the cache stays valid, the trigger is consumed
        new_state = pol.finish_request(state, send, consecutive_blocks=0, backoff_until_utc=None)
        new_state = _consume(new_state, trigger)
        pol.save_state(state_path, new_state)
        return RunOutcome("not_modified", "HTTP 304: nothing changed; no record written", http_requests=1)

    if status in BLOCK_STATUSES:
        until = pol.backoff_until(send, resp_headers.get("retry-after"))
        blocks = state.consecutive_blocks + 1
        new_state = pol.finish_request(state, send, consecutive_blocks=blocks, backoff_until_utc=_iso(until))
        if blocks >= cfg.breaker_threshold:
            new_state = pol.trip_breaker(new_state, send)
        pol.save_state(state_path, new_state)  # the trigger stays pending for a later, allowed cycle
        return RunOutcome("backoff", f"HTTP {status}: no retry; backing off until {_iso(until)}",
                          http_requests=1)

    if status != 200:
        pol.save_state(state_path, pol.finish_request(state, send))
        return RunOutcome("failed", f"HTTP {status}", http_requests=1)

    collected = _iso(send)
    outcome_label = _store(db, url=url, symbol=symbol, endpoint=endpoint, body=body,
                           collected_at_utc=collected, http_status=status, trigger=trigger)
    new_cache = dict(state.endpoint_cache)
    new_cache[url] = {"etag": resp_headers.get("etag", cache.get("etag")),
                      "last_modified": resp_headers.get("last-modified", cache.get("last_modified")),
                      "fetched_utc": collected}
    new_state = pol.finish_request(state, send, endpoint_cache=new_cache, consecutive_blocks=0,
                                   backoff_until_utc=None)
    new_state = _consume(new_state, trigger)
    pol.save_state(state_path, new_state)
    return RunOutcome("fetched", f"stored {endpoint} for {symbol}: {outcome_label}", http_requests=1,
                      new=1 if outcome_label == "inserted" else 0,
                      duplicates=0 if outcome_label == "inserted" else 1)


def _consume(state: pol.PollState, trigger: dict[str, Any] | None) -> pol.PollState:
    if trigger is None:
        return state
    return replace(
        state,
        pending_triggers=[t for t in state.pending_triggers
                          if t["announcement_id"] != trigger["announcement_id"]],
        consumed_triggers=sorted(set(state.consumed_triggers) | {trigger["announcement_id"]}),
    )


def stored_profile_age(db: Any, symbol: str, endpoint: str, now: datetime) -> timedelta | None:
    row = _stored_record(db, symbol, endpoint)
    if row is None:
        return None
    return now - _utc(row["collected_at_utc"])


def store_structured(db: Any, *, endpoint: str, symbol: str, fields: dict[str, Any], url: str,
                     fetched_at_utc: str, http_status: int,
                     triggering_announcement_id: str | None = None) -> str:
    """Persist STRUCTURED FIELDS ONLY (never the raw body). Every record is tagged source = investify.pk."""
    content = json.dumps(fields, ensure_ascii=False, sort_keys=True)
    metadata = {
        "source": SOURCE_NAME,
        "attribution": pol.ATTRIBUTION,
        "symbol": symbol,
        "endpoint": endpoint,
        "fetched_at_utc": fetched_at_utc,
        "triggering_announcement_id": triggering_announcement_id,
        "storage": "structured_fields_only",
    }
    out = record_source_item(
        db, source_id=SOURCE_ID, collected_at_utc=fetched_at_utc, url=url,
        external_id=f"{symbol}:{endpoint}", content=content, title=f"{symbol} {endpoint} (Investify)",
        published_at_utc=None, published_at_raw=None, excerpt=None,
        provenance={"original_url": url, "retrieval_method": "html", "http_status": http_status,
                    "document_type": endpoint, "publication_time_status": "unknown",
                    "source_metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True)},
    )
    return out.outcome
