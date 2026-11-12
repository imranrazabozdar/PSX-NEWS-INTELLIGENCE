"""Scale validation for the Investify extractors: the proven HUBC flow on a small, diverse batch.

Companies: MEBL (bank), LUCK (cement), OGDC (oil and gas exploration), FFC (fertilizer), APL (oil and
gas marketing). HUBC is the pilot and is not repeated.

Order is round-robin by step: every company's announcements first, then each company's fundamentals
(first fill when a financial result exists), then profile, then competitors. Every request goes through
collectors.investify_fundamentals.run_endpoint, so the 15-minute cap (shared across all Investify requests),
robots.txt, conditional requests, backoff, attribution and structured-only storage all apply.
The driver sleeps
through the cap; it never bypasses it.

Each page is kept ONLY as a transient copy in the scratch directory, for mapping. The report step deletes it.

  python -m scripts.investify_validation_run --db <operational.sqlite> --state <state.json> \
      --audit <audit.jsonl> --scratch <dir> --progress <progress.jsonl> --max-seconds 7000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from collectors import investify_fundamentals as fund
from collectors.engine import load_source
from collectors.investify_job import AuditLog
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate

COMPANIES = ("MEBL", "LUCK", "OGDC", "FFC", "APL")
ENDPOINTS = ("announcements", "fundamentals", "profile", "competitors")
SLEEP_WHEN_CAPPED_S = 20


def plan() -> list[tuple[str, str]]:
    """Round-robin by step: announcements for all, then fundamentals, then profile, then competitors."""
    return [(sym, ep) for ep in ENDPOINTS for sym in COMPANIES]


def _done(progress: Path) -> set[tuple[str, str]]:
    if not progress.exists():
        return set()
    return {(r["symbol"], r["endpoint"]) for r in
            (json.loads(x) for x in progress.read_text(encoding="utf-8").splitlines() if x)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Investify scale validation (small diverse batch)")
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--audit", required=True, type=Path)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--progress", required=True, type=Path)
    ap.add_argument("--max-seconds", type=int, default=7000)
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args(argv)
    if "://" in str(args.db):
        print("refused: local file only", file=sys.stderr)
        return 2
    if args.plan_only:
        for sym, ep in plan():
            print(sym, ep)
        return 0

    args.scratch.mkdir(parents=True, exist_ok=True)
    db = SQLiteDatabase(str(args.db))
    migrate(db)
    seed_loader.load(db)
    entry = {**load_source(db, fund.SOURCE_ID), "enabled": 1}
    audit = AuditLog(args.audit)
    done = _done(args.progress)
    deadline = time.time() + args.max_seconds
    for sym, ep in plan():
        if (sym, ep) in done:
            continue
        if time.time() > deadline:
            break
        dev_copy = args.scratch / f"{sym}_{ep}.html"
        while True:
            out = fund.run_endpoint(
                now=datetime.now(UTC), state_path=args.state, entry=entry, db=db, endpoint=ep, symbol=sym,
                watchlist=frozenset(COMPANIES), dev_copy=dev_copy, audit=audit, sleep=time.sleep)
            capped = out.status == "skipped" and "rate limit" in out.reason
            if capped and time.time() < deadline:
                time.sleep(SLEEP_WHEN_CAPPED_S)  # the cap is shared: wait for it, never bypass it
                continue
            if out.status == "skipped" and out.reason.startswith("outside trading hours"):
                # Not a step outcome: stop without recording, so the step is retried in the next window.
                print("outside trading hours; stopping, nothing recorded", flush=True)
                return 3
            break
        row = {"symbol": sym, "endpoint": ep, "status": out.status, "reason": out.reason,
               "ts_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        with args.progress.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
