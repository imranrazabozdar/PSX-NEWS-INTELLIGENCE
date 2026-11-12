"""Investify announcement collection under written consent (docs/consent/investify-2026-11-12.md).

This is the fetch layer of a transparent, minimal-load client. It is honestly identifiable: one stable
User-Agent with a contact, never a spoofed browser, never rotated identities. The aim is low server load
and transparency.

Pipeline per cycle:

1. kill switch and registry check (enabled, APPROVED, consent recorded);
2. policy gate: consent date, trading hours, daily cap, circuit breaker, single-flight, Cache-Control
   freshness,
   backoff, and the 15-minute floor (or robots.txt Crawl-delay if longer);
3. a random jitter of 1-180 seconds, slept before the request and never on the exact tick;
4. the policy is checked again at the send time, so the jitter cannot carry a request outside the window;
5. a persisted in-flight marker is set before the request, which makes it single-flight;
6. exactly ONE request: robots.txt when its cached copy is stale (the cycle ends there), otherwise the
   announcements page with If-None-Match / If-Modified-Since. Nothing else is fetched: no crawl, no link
   following, no PDFs (gated dps PDFs are browser-only);
7. 304 is a no-op; 200 is parsed and stored as metadata only; 403 / 429 / 503 start a backoff, honour
   Retry-After, and count towards the circuit breaker; a network error is not retried in the same cycle;
8. every request, and every skip, is written to the audit trail (UTC time, URL, status, 200 or 304, bytes,
   jitter, backoff, requests so far today). The audit trail contains no headers and no secrets.

Live collection writes announcement metadata to the news database. It runs from the scheduled GitHub Actions
job (.github/workflows/investify-collect.yml) with the news-database credentials, and not from a development
session. PDFs stay browser-fetch (gated_dps): this module never downloads them.

Usage (scheduled job):  python -m collectors.investify_job --state <state.json> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol
from database.repositories import record_source_item
from engines import investify_collector as ic

log = logging.getLogger("investify")
MAX_BYTES = 5_000_000
TIMEOUT_SECONDS = 25.0
BLOCK_STATUSES = frozenset({403, 429, 503})

# A transport returns (status, headers, body) for any HTTP status and raises only for network failures.
Transport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


def default_transport(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """One request, no retries. Error statuses are returned, not raised."""
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - fixed https URL only
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:  # noqa: S310 - fixed https URL
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        headers_out = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return exc.code, headers_out, exc.read(MAX_BYTES) if exc.fp else b""


class AuditLog:
    """Append-only JSON-lines trail of every request and skip. Shown to Investify on request."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None

    def record(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, sort_keys=True, ensure_ascii=False)
        log.info("investify %s", line)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


@dataclass
class RunOutcome:
    # refused | skipped | robots_refreshed | robots_disallowed | not_modified | backoff | fetched | failed
    status: str
    reason: str
    http_requests: int = 0
    new: int = 0
    duplicates: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)  # dry runs only: what would be stored


def _external_id(source_url: str) -> str | None:
    m = re.search(r"dps-(?:pdf|image)-(\d+)", source_url)
    return m.group(1) if m else None


def _store(db: Any, rec: ic.AnnouncementRecord, *, collected_at_utc: str, http_status: int) -> str:
    """Metadata only. The basis hashed for dedup is title, source URL and time: never the summary."""
    basis = "\n".join([rec.title, rec.source_url, rec.announced_at_utc])
    metadata = {
        "symbol": rec.symbol,
        "company_name": rec.company_name,
        "announced_on_pkt": rec.announced_on_pkt,
        "category": rec.category,
        "pdf_url": rec.pdf_url,
        "pdf_access": rec.pdf_access,
        "attribution": pol.ATTRIBUTION,
        "source": "investify.pk",
    }
    out = record_source_item(
        db, source_id=pol.SOURCE_ID, collected_at_utc=collected_at_utc, url=rec.source_url,
        external_id=_external_id(rec.source_url), content=basis, title=rec.title,
        published_at_utc=rec.announced_at_utc, published_at_raw=rec.announced_at_utc, excerpt=None,
        provenance={"original_url": rec.source_url, "retrieval_method": "html",
                    "http_status": http_status, "document_type": rec.category,
                    "publication_time_status": "known",
                    "source_metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True)},
    )
    return out.outcome


def _request(transport: Transport, url: str, headers: dict[str, str], *, cycle: str, send: datetime,
             state: pol.PollState, cfg: pol.PolicyConfig, jitter: int, audit: AuditLog):
    """The single request of a cycle. Returns (status, headers, body, error). Audited either way."""
    status, resp_headers, body, error = None, {}, b"", None
    try:
        status, resp_headers, body = transport(url, headers)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = type(exc).__name__  # the class only: no message, no headers, no secrets
    audit.record({
        "event": "request", "ts_utc": pol._iso(send), "cycle": cycle, "method": "GET", "url": url,
        "status": status, "outcome": _outcome_label(status, error), "bytes": len(body),
        "jitter_s": jitter, "requests_today": pol.requests_today(send, state) + 1,
        "user_agent": pol.USER_AGENT, "error": error,
    })
    return status, resp_headers, body, error


def _outcome_label(status: int | None, error: str | None) -> str:
    if error:
        return "network_error"
    return {200: "ok", 304: "not_modified", 403: "blocked", 429: "rate_limited", 503: "unavailable"}.get(
        status, "other")


def run_once(*, now: datetime, state_path: Path, entry: dict[str, Any], db: Any | None,
             transport: Transport = default_transport, watchlist: frozenset[str] | None = None,
             dry_run: bool = False, cfg: pol.PolicyConfig = pol.DEFAULT_CONFIG,
             sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
             audit: AuditLog | None = None, good: gc.Policy | None = None) -> RunOutcome:
    """One consented cycle. Fail-closed on a missing policy. One request in flight process-wide.

    Every decision comes from the good-citizen gate."""
    policy = good if good is not None else gc.safe_active_policy()
    if policy is None:
        return RunOutcome("refused", "policy missing or invalid: fail closed")
    with gc.single_flight() as got:
        if not got:
            return RunOutcome("skipped", "queued: single-flight, another request holds the slot")
        return _run_once_inner(now=now, state_path=state_path, entry=entry, db=db, transport=transport,
                               watchlist=watchlist, dry_run=dry_run, cfg=cfg, sleep=sleep, rng=rng,
                               audit=audit, policy=policy)


def _run_once_inner(*, now: datetime, state_path: Path, entry: dict[str, Any], db: Any | None,
                    transport: Transport, watchlist: frozenset[str] | None, dry_run: bool,
                    cfg: pol.PolicyConfig, sleep, rng: random.Random | None, audit: AuditLog | None,
                    policy: gc.Policy) -> RunOutcome:
    audit = audit or AuditLog()
    rng = rng or random.SystemRandom()

    def skip(reason: str) -> RunOutcome:
        audit.record({"event": "skip", "ts_utc": pol._iso(now), "reason": reason})
        return RunOutcome("skipped", reason)

    if cfg.kill_switch:
        return skip("kill switch is on")
    problem = pol.registry_problem(entry)
    if problem:
        return RunOutcome("refused", problem)
    state = pol.load_state(state_path)
    endpoint = "robots" if pol.robots_needs_refresh(now, state) else "announcements"
    # the announcements page is an event feed; the gate decides the rest
    verdict = gc.gate(now=now, state=state, policy=policy, endpoint=endpoint)
    if verdict.warning:
        audit.record({"event": "warn", "ts_utc": pol._iso(now), "endpoint": endpoint,
                      "warning": verdict.warning})
    if not verdict.allowed:
        return skip(verdict.reason)
    # the latest possible send time: if even that is too early, no send in this cycle can be valid
    latest_send = now + timedelta(seconds=cfg.jitter_max)
    decision = pol.may_poll(now, state, cfg, rate_at=latest_send)
    if not decision.allowed:
        return skip(decision.reason)

    # 3. jitter: never on the exact tick, always inside the window the policy re-checks below
    jitter = pol.jitter_seconds(rng, cfg)
    sleep(jitter)
    send = now + timedelta(seconds=jitter)
    # 4. the jitter may have carried the send past the window, the interval or the cap: check again
    decision = pol.may_poll(send, state, cfg)
    if not decision.allowed:
        return skip(f"after {jitter}s jitter: {decision.reason}")

    # 5. single-flight marker, persisted before the request is sent
    state = pol.mark_in_flight(state, send)
    pol.save_state(state_path, state)

    if pol.robots_needs_refresh(send, state):
        return _robots_cycle(send=send, state=state, state_path=state_path, transport=transport,
                             cfg=cfg, jitter=jitter, audit=audit, policy=policy)
    return _page_cycle(send=send, state=state, state_path=state_path, transport=transport, cfg=cfg,
                       jitter=jitter, audit=audit, db=db, dry_run=dry_run, watchlist=watchlist,
                       policy=policy)


def _robots_cycle(*, send, state, state_path, transport, cfg, jitter, audit,
                  policy: gc.Policy) -> RunOutcome:
    status, _, body, error = _request(
        transport, pol.ROBOTS_URL, {"User-Agent": pol.USER_AGENT, "Accept": "text/plain"},
        cycle="robots", send=send, state=state, cfg=cfg, jitter=jitter, audit=audit)
    if status == 200:
        text = body.decode("utf-8", "replace")
    elif status in (404, 410):
        text = ""  # no robots file: nothing is disallowed
    else:
        text = "User-agent: *\nDisallow: /\n"  # cannot read robots.txt (or a network error): be conservative

    tripped = False
    if state.robots_txt is not None and pol.robots_allows(state.robots_txt, pol.ANNOUNCEMENTS_URL) \
            and not pol.robots_allows(text, pol.ANNOUNCEMENTS_URL):
        # the site has started to disallow the path: stop for the day and raise an alert
        tripped = True
    extra: dict[str, Any] = {}
    if status in BLOCK_STATUSES:  # a block on robots.txt is a multi-hour cooldown too
        until = gc.cooldown_until(send, state.consecutive_blocks + 1, policy)
        extra = {"cooldown_until_utc": pol._iso(until), "consecutive_blocks": state.consecutive_blocks + 1}
    new_state = pol.finish_request(state, send, robots_txt=text, robots_fetched_utc=pol._iso(send),
                                   crawl_delay_s=pol.robots_crawl_delay(text), **extra)
    if tripped:
        new_state = pol.trip_breaker(new_state, send)
        _alert_breaker(audit, send, "robots.txt now disallows the announcements path")
    pol.save_state(state_path, new_state)
    reason = f"robots.txt cached (HTTP {status or error}); no page request this cycle"
    if tripped:
        reason += "; circuit breaker opened"
    return RunOutcome("robots_refreshed", reason, http_requests=1)


def _page_cycle(*, send, state, state_path, transport, cfg, jitter, audit, db, dry_run,
                watchlist, policy: gc.Policy) -> RunOutcome:
    if not pol.robots_allows(state.robots_txt or "", pol.ANNOUNCEMENTS_URL):
        pol.save_state(state_path, replace(state, in_flight_since_utc=None))
        audit.record({"event": "skip", "ts_utc": pol._iso(send), "reason": "robots.txt disallows the path"})
        return RunOutcome("robots_disallowed", "robots.txt disallows the announcements path; not fetched")

    headers = {"User-Agent": pol.USER_AGENT, "Accept": "text/html"}
    if state.etag:
        headers["If-None-Match"] = state.etag
    if state.last_modified:
        headers["If-Modified-Since"] = state.last_modified
    status, resp_headers, body, error = _request(
        transport, pol.ANNOUNCEMENTS_URL, headers, cycle="page", send=send, state=state, cfg=cfg,
        jitter=jitter, audit=audit)
    fresh = _fresh_until(send, resp_headers)

    if error is not None:
        pol.save_state(state_path, pol.finish_request(state, send, fresh_until_utc=None))
        return RunOutcome("failed", f"network error ({error}); no retry in this cycle", http_requests=1)

    if status == 304:
        # 3. nothing changed: no further processing, the stored cache stays valid
        pol.save_state(state_path, pol.finish_request(
            state, send, fresh_until_utc=fresh, consecutive_blocks=0, backoff_until_utc=None))
        return RunOutcome("not_modified", "HTTP 304: nothing changed since the last poll", http_requests=1)

    if status in BLOCK_STATUSES:
        blocks = state.consecutive_blocks + 1
        until = gc.cooldown_until(send, blocks, policy, resp_headers.get("retry-after"))
        changes: dict[str, Any] = {"consecutive_blocks": blocks, "backoff_until_utc": pol._iso(until),
                                   "cooldown_until_utc": pol._iso(until)}
        tripped = blocks >= policy.breaker_threshold
        new_state = pol.finish_request(state, send, **changes)
        if tripped:
            new_state = pol.trip_breaker(new_state, send)
            _alert_breaker(audit, send, f"{blocks} consecutive HTTP {status}")
        pol.save_state(state_path, new_state)
        reason = (f"HTTP {status}: multi-hour cooldown until {pol._iso(until)}"
                  + ("; circuit breaker opened for the day" if tripped else ""))
        return RunOutcome("backoff", reason, http_requests=1)

    if status != 200:
        pol.save_state(state_path, pol.finish_request(state, send))
        return RunOutcome("failed", f"HTTP {status}", http_requests=1)

    # 200: parse, filter, store metadata only
    watch = watchlist if watchlist is not None else ic.load_watchlist_symbols()
    collected_at = pol._iso(send)
    result = ic.collect(body.decode("utf-8", "replace"), watchlist=watch, retrieved_at_utc=collected_at)
    outcome = RunOutcome("fetched", f"parsed {len(result.records)} watchlist announcements",
                         http_requests=1, duplicates=result.skipped_duplicates)
    if dry_run:
        outcome.records = [{"symbol": r.symbol, "title": r.title, "category": r.category,
                            "announced_at_utc": r.announced_at_utc, "pdf_access": r.pdf_access}
                           for r in result.records]
    else:
        for rec in result.records:
            if _store(db, rec, collected_at_utc=collected_at, http_status=status) == "inserted":
                outcome.new += 1
            else:
                outcome.duplicates += 1
    if not dry_run:
        # rule (a): queue one fundamentals refresh per NEW financial-result announcement. Imported here,
        # because the fundamentals module imports this one.
        from collectors import investify_fundamentals as fund
        symbols = {r.symbol for r in result.records}
        has = {sym: fund.has_fundamentals(db, sym) for sym in symbols}
        state, _ = fund.enqueue_from_announcements(state, result.records, now=send, has_fundamentals=has)
    pol.save_state(state_path, pol.finish_request(
        state, send, etag=resp_headers.get("etag", state.etag),
        last_modified=resp_headers.get("last-modified", state.last_modified),
        fresh_until_utc=fresh, consecutive_blocks=0, backoff_until_utc=None))
    return outcome


def _fresh_until(send: datetime, headers: dict[str, str]) -> str | None:
    max_age = pol.parse_max_age(headers.get("cache-control"))
    if max_age is None:
        return None
    return pol._iso(send + min(timedelta(seconds=max_age), pol.FRESH_CAP))


def _alert_breaker(audit: AuditLog, send: datetime, why: str) -> None:
    log.warning("investify circuit breaker opened: %s", why)
    audit.record({"event": "breaker_opened", "ts_utc": pol._iso(send), "why": why})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Investify announcements, consent-bound (one request per cycle)")
    ap.add_argument("--state", required=True, help="polling state file (kept between runs)")
    ap.add_argument("--audit", help="audit trail file (JSON lines); default: next to the state file")
    ap.add_argument("--dry-run", action="store_true", help="fetch and parse only; store nothing")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from collectors.engine import load_source
    from database.connection import connect

    cfg = pol.PolicyConfig.from_env()
    audit_path = Path(args.audit) if args.audit else Path(args.state).with_name("investify_audit.jsonl")
    db = connect()
    entry = load_source(db, pol.SOURCE_ID)
    outcome = run_once(now=datetime.now(UTC), state_path=Path(args.state), entry=entry, db=db,
                       dry_run=args.dry_run, cfg=cfg, audit=AuditLog(audit_path))
    print(json.dumps({"status": outcome.status, "reason": outcome.reason,
                      "http_requests": outcome.http_requests, "new": outcome.new,
                      "duplicates": outcome.duplicates, "attribution": pol.ATTRIBUTION,
                      "records": outcome.records}, ensure_ascii=False, indent=2))
    return 1 if outcome.status in ("refused", "failed") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
