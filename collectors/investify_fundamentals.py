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
from collections.abc import Mapping
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
from engines import investify_extract as x

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
    "profile": Endpoint("profile", "/company/{symbol}/profile", "backfill_once"),  # verified 200, 2026-11-12
    "announcements": Endpoint("announcements", "/company/{symbol}/announcements", "feed"),
}


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- rule (a): event triggers

def result_key(rec: ic.AnnouncementRecord) -> str:
    """Dedupe key: symbol, Pakistan-time date and headline. One result never triggers twice."""
    return f"{rec.symbol}|{rec.announced_on_pkt}|{rec.title}"


def enqueue_from_announcements(state: pol.PollState, records: list[ic.AnnouncementRecord], *,
                               now: datetime,
                               has_fundamentals: Mapping[str, bool] | None = None,
                               ) -> tuple[pol.PollState, list[dict[str, Any]]]:
    """Queue fundamentals refreshes from financial-result announcements. Pure: returns the new state.

    FIRST FILL: a watchlist company with NO fundamentals on record gets ONE fetch, seeded from its most recent
    qualifying announcement, however old. It happens once per company.
    REFRESH: after that, a qualifying announcement queues a refresh only if it is NEWER than the last result
    seen for that company AND within TRIGGER_MAX_AGE (3 days). An already-seen result (same symbol, date and
    headline) never queues again.
    """
    has = dict(has_fundamentals or {})
    pending = list(state.pending_triggers)
    done = set(state.consumed_triggers)
    seen_ids = set(state.seen_announcements)
    keys = set(state.seen_result_keys)
    first_filled = set(state.first_filled_symbols)
    last_at = dict(state.last_result_at)
    queued: list[dict[str, Any]] = []

    for rec in records:
        seen_ids.add(rec.content_sha256)
    by_symbol: dict[str, list[ic.AnnouncementRecord]] = {}
    for rec in records:
        if rec.category in x.QUALIFYING_CATEGORIES:
            by_symbol.setdefault(rec.symbol, []).append(rec)

    for symbol, recs in by_symbol.items():
        recs.sort(key=lambda r: r.announced_at_utc, reverse=True)
        newest = recs[0].announced_at_utc
        if symbol not in first_filled and not has.get(symbol, False):
            financial = [r for r in recs if r.category == "financial_results"]
            if financial and not any(t["symbol"] == symbol for t in pending):
                latest = financial[0]  # the most recent FINANCIAL RESULT (not a transmission)
                item = _trigger_item(latest, kind="first_fill", now=now)
                pending.append(item)
                queued.append(item)
                first_filled.add(symbol)
                keys.update(result_key(r) for r in recs)
            last_at[symbol] = max(last_at.get(symbol, newest), newest)
            continue
        last = last_at.get(symbol)
        for rec in recs:  # newest first
            k = result_key(rec)
            if k in keys:
                continue  # already seen: never re-triggers
            keys.add(k)
            if last and rec.announced_at_utc <= last:
                continue  # not newer than the last result seen
            if now - _utc(rec.announced_at_utc) > TRIGGER_MAX_AGE:
                continue  # outside the window for ongoing refreshes
            if rec.content_sha256 in done or any(t["announcement_id"] == rec.content_sha256 for t in pending):
                continue
            item = _trigger_item(rec, kind="refresh", now=now)
            pending.append(item)
            queued.append(item)
            break
        last_at[symbol] = max(last_at.get(symbol, newest), newest)

    new_state = replace(state, seen_announcements=sorted(seen_ids), seen_result_keys=sorted(keys),
                        pending_triggers=pending, first_filled_symbols=sorted(first_filled),
                        last_result_at=last_at)
    return new_state, queued


def _trigger_item(rec: ic.AnnouncementRecord, *, kind: str, now: datetime) -> dict[str, Any]:
    return {"symbol": rec.symbol, "announcement_id": rec.content_sha256, "kind": kind,
            "result_key": result_key(rec), "announced_at_utc": rec.announced_at_utc, "title": rec.title,
            "queued_utc": _iso(now)}


def pending_trigger(state: pol.PollState, symbol: str) -> dict[str, Any] | None:
    """The oldest pending financial-result trigger for this symbol, if any."""
    for item in state.pending_triggers:
        if item["symbol"] == symbol:
            return item
    return None


# ---------------------------------------------------------------- storage

def _stored_record(db: Any, symbol: str, endpoint: str) -> dict[str, Any] | None:
    """The newest stored record for this company and endpoint.

    Refreshed snapshots carry a timestamp suffix on their identifier."""
    rows = db.execute(
        "SELECT source_item_id, collected_at_utc FROM source_items WHERE source_id = ? "
        "AND (external_id = ? OR external_id LIKE ?) ORDER BY collected_at_utc DESC LIMIT 1",
        (SOURCE_ID, f"{symbol}:{endpoint}", f"{symbol}:{endpoint}:%"))
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
                 audit: AuditLog | None = None, dev_copy: Path | None = None) -> RunOutcome:
    """Fetch ONE Investify endpoint for ONE symbol, if every rule allows it. At most one HTTP request.

    dev_copy: development only. When given, the body is written to that path so the page can be mapped; the
    caller must delete it. Nothing is persisted from the body except the structured fields.
    """
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
    if spec.cadence == "feed":
        if manual:
            return RunOutcome("refused", "the announcements feed is polled by its own schedule, not manually")
    elif spec.cadence == "announcement":  # rule (a)
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
    if _stored_record(db, symbol, endpoint) is None:
        cache = {}  # nothing stored yet: a 304 would have nothing to point to, so send no conditional headers
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
    if dev_copy is not None:
        dev_copy.write_bytes(body)  # transient, for mapping only; the caller deletes it
    outcome_label = "no_extractor"
    extractor = EXTRACTORS.get(endpoint)
    if extractor is not None:
        fields = extractor(body, symbol)
        outcome_label = store_structured(
            db, endpoint=endpoint, symbol=symbol, fields=fields, url=url, fetched_at_utc=collected,
            http_status=status, triggering_announcement_id=trigger["announcement_id"] if trigger else None)
    if endpoint == "announcements":
        records = x.to_announcement_records(fields, collected)
        has = {symbol: has_fundamentals(db, symbol)}
        state, queued = enqueue_from_announcements(state, records, now=send, has_fundamentals=has)
        audit.record({"event": "triggers_queued", "ts_utc": collected, "symbol": symbol,
                      "queued": [q["kind"] + ":" + q["result_key"] for q in queued]})
    new_cache = dict(state.endpoint_cache)
    if extractor is not None:  # cache validators only for bodies that were actually stored
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
                     triggering_announcement_id: str | None = None, manual_gate_test: bool = False) -> str:
    """Persist STRUCTURED FIELDS ONLY (never the raw body). Every record is tagged source = investify.pk."""
    content = json.dumps(fields, ensure_ascii=False, sort_keys=True)
    metadata = {
        "source": SOURCE_NAME,
        "attribution": pol.ATTRIBUTION,
        "symbol": symbol,
        "endpoint": endpoint,
        "fetched_at_utc": fetched_at_utc,
        "triggering_announcement_id": triggering_announcement_id,
        "manual_gate_test": manual_gate_test,
        "storage": "structured_fields_only",
        "fields": fields,  # the structured record itself; no raw body
    }
    # The table is append-only and keeps the metadata of the first row for an identifier. A later snapshot
    # of the same endpoint gets its own identifier, so its structured fields are kept.
    base = f"{symbol}:{endpoint}"
    external_id = base if _stored_record(db, symbol, endpoint) is None else f"{base}:{fetched_at_utc}"
    out = record_source_item(
        db, source_id=SOURCE_ID, collected_at_utc=fetched_at_utc, url=url,
        external_id=external_id, content=content, title=f"{symbol} {endpoint} (Investify)",
        published_at_utc=None, published_at_raw=None, excerpt=None,
        provenance={"original_url": url, "retrieval_method": "html", "http_status": http_status,
                    "document_type": endpoint, "publication_time_status": "unknown",
                    "source_metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True)},
    )
    return out.outcome


def has_fundamentals(db: Any, symbol: str) -> bool:
    """True when a fundamentals record exists for this company in the operational database."""
    return _stored_record(db, symbol, "fundamentals") is not None


EXTRACTORS: dict[str, Any] = {
    "profile": x.parse_profile,
    "announcements": x.parse_announcements,
    "fundamentals": x.parse_fundamentals,
    "competitors": x.parse_competitors,
}
