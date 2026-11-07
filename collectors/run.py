"""Command-line entry point used by the scheduled workflow and for manual runs.

  python -m collectors.run --due                 # collect every ACTIVE source that is due
  python -m collectors.run --source dawn --dry-run
  python -m collectors.run --source dawn --since 2026-11-01T00:00:00Z  # bounded backfill (ACTIVE only)

Exit code is non-zero if any source failed, so failures are visible in GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import sys

from collectors.engine import CollectionRefused, collect, due_sources
from database.connection import connect


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run source collectors")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--source", help="source_id to collect")
    g.add_argument("--due", action="store_true", help="collect all ACTIVE sources that are due")
    ap.add_argument("--dry-run", action="store_true", help="fetch and parse only; write nothing")
    ap.add_argument("--max-items", type=int, default=100)
    ap.add_argument("--since", help="only items published at/after this UTC time")
    ap.add_argument("--until", help="only items published at/before this UTC time")
    args = ap.parse_args(argv)
    db = connect()
    sources = due_sources(db) if args.due else [args.source]
    if not sources:
        print("No ACTIVE sources are due. Nothing collected.")
        print(json.dumps({"usage": db.usage()}))
        return 0
    failed = False
    for sid in sources:
        try:
            r = collect(db, sid, dry_run=args.dry_run, max_items=args.max_items,
                        since_utc=args.since, until_utc=args.until, job="scheduled" if args.due else "manual")
        except CollectionRefused as exc:
            print(f"{sid}: refused: {exc}")
            failed = True
            continue
        failed |= r.status == "failed"
        print(json.dumps({"source": sid, "status": r.status, "fetched": r.fetched, "new": r.new,
                          "unchanged": r.unchanged, "duplicates": r.duplicates,
                          "new_versions": r.new_versions, "failed": r.failed,
                          "not_modified": r.not_modified, "http_status": r.http_status,
                          "errors": r.errors[:3]}))
    print(json.dumps({"usage": db.usage()}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
