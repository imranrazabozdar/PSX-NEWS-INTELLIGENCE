"""Investify announcement collection under written consent (docs/consent/investify-2026-11-12.md).

Pipeline per run, in order:

1. kill switch and registry check (lifecycle PERMITTED_WITH_CONDITIONS, enabled, consent recorded);
2. policy gate (consent effective date, trading hours, 15-minute rate limit, backoff): if refused, no request;
3. robots.txt: if the cached copy is stale, the run's single request fetches it and the run ends there;
4. one conditional GET of the announcements page (If-None-Match / If-Modified-Since):
   304 is a no-op; 429 or 503 starts a backoff and the run ends without a retry;
5. the page is parsed by the pure parser (engines/investify_collector.py), filtered to the watchlist, and each
   record is stored as METADATA ONLY through the shared item writer. Investify's summary text is never stored.

Each run makes at most ONE HTTP request. Every branch is covered by tests that inject the transport.

Live collection writes announcement metadata to the news database. It runs from the scheduled GitHub Actions
job (.github/workflows/investify-collect.yml) with the news-database credentials, and not from a development
session. PDFs stay browser-fetch (gated_dps): this module never downloads them.

Usage (scheduled job):  python -m collectors.investify_job --state <state.json> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collectors import investify_policy as pol
from database.repositories import record_source_item
from engines import investify_collector as ic

MAX_BYTES = 5_000_000
TIMEOUT_SECONDS = 25.0

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


def run_once(*, now: datetime, state_path: Path, entry: dict[str, Any], db: Any | None,
             transport: Transport = default_transport, watchlist: frozenset[str] | None = None,
             dry_run: bool = False, kill_switch: bool = False) -> RunOutcome:
    if kill_switch:
        return RunOutcome("skipped", "kill switch is on")
    problem = pol.registry_problem(entry)
    if problem:
        return RunOutcome("refused", problem)
    state = pol.load_state(state_path)
    decision = pol.may_poll(now, state)
    if not decision.allowed:
        return RunOutcome("skipped", decision.reason)

    # 3. robots.txt. Its fetch is this run's single request, so the page is not fetched in the same run.
    if pol.robots_needs_refresh(now, state):
        status, _, body = transport(pol.ROBOTS_URL, {"User-Agent": pol.USER_AGENT})
        if status == 200:
            robots = body.decode("utf-8", "replace")
        elif status in (404, 410):
            robots = ""  # no robots file: nothing is disallowed
        else:
            robots = "User-agent: *\nDisallow: /\n"  # cannot read robots.txt: be conservative
        save = pol.after_request(state, now, robots_txt=robots, robots_fetched_utc=pol._iso(now))
        pol.save_state(state_path, save)
        return RunOutcome("robots_refreshed", f"robots.txt cached (HTTP {status}); no page request this run",
                          http_requests=1)

    if not pol.robots_allows(state.robots_txt or "", pol.ANNOUNCEMENTS_URL):
        return RunOutcome("robots_disallowed", "robots.txt disallows the announcements path; not fetched")

    # 4. one conditional GET
    headers = {"User-Agent": pol.USER_AGENT, "Accept": "text/html"}
    if state.etag:
        headers["If-None-Match"] = state.etag
    if state.last_modified:
        headers["If-Modified-Since"] = state.last_modified
    status, resp_headers, body = transport(pol.ANNOUNCEMENTS_URL, headers)

    if status == 304:
        pol.save_state(state_path, pol.after_request(state, now))
        return RunOutcome("not_modified", "HTTP 304: nothing changed since the last poll", http_requests=1)
    if status in (429, 503):
        until = pol.backoff_until(now, resp_headers.get("retry-after"))
        pol.save_state(state_path, pol.after_request(state, now, backoff_until_utc=pol._iso(until)))
        return RunOutcome("backoff", f"HTTP {status}: no retry; no requests until {pol._iso(until)}",
                          http_requests=1)
    if status != 200:
        pol.save_state(state_path, pol.after_request(state, now))
        return RunOutcome("failed", f"HTTP {status}", http_requests=1)

    # 5. parse, filter, store metadata
    watch = watchlist if watchlist is not None else ic.load_watchlist_symbols()
    collected_at = pol._iso(now)
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
    pol.save_state(state_path, pol.after_request(
        state, now, etag=resp_headers.get("etag", state.etag),
        last_modified=resp_headers.get("last-modified", state.last_modified), backoff_until_utc=None))
    return outcome


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Investify announcements, consent-bound (one request per run)")
    ap.add_argument("--state", required=True, help="path of the polling state file (kept between runs)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and parse only; store nothing")
    args = ap.parse_args(argv)

    from collectors.engine import load_source
    from database.connection import connect

    kill = os.environ.get("PSXNI_KILL_SWITCH", "").lower() == "true"
    db = connect()
    entry = load_source(db, pol.SOURCE_ID)
    outcome = run_once(now=datetime.now(UTC), state_path=Path(args.state), entry=entry, db=db,
                       dry_run=args.dry_run, kill_switch=kill)
    print(json.dumps({"status": outcome.status, "reason": outcome.reason,
                      "http_requests": outcome.http_requests, "new": outcome.new,
                      "duplicates": outcome.duplicates, "attribution": pol.ATTRIBUTION,
                      "records": outcome.records}, ensure_ascii=False, indent=2))
    return 1 if outcome.status in ("refused", "failed") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
