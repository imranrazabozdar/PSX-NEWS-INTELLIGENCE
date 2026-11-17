"""Delete Investify announcement TITLE facts older than the capture window (owner decision 2026-11-17).

Narrow by construction: only research_fact rows from an Investify source, topic announcements.*, whose
announcement date (period) is before capture_cutoff(now). Dry run by default (counts only); --apply deletes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from collectors import investify_policy as pol
from collectors.investify_library_job import SOURCE_NAME
from engines import library_db
from engines import research_facts as rf

WHERE = "source_name IN (?, ?) AND topic LIKE 'announcements.%' AND period < ?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    cutoff = pol.capture_cutoff(datetime.now(UTC))
    try:
        conn = library_db.get_library_connection()
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2
    params = (SOURCE_NAME, rf.SOURCE_NAME, cutoff)
    n = conn.db.execute(f"SELECT COUNT(*) AS n FROM research_fact WHERE {WHERE}", params)[0]["n"]  # noqa: S608
    print(f"Investify title facts older than {cutoff}: {n}")
    if args.apply and n:
        conn.db.execute(f"DELETE FROM research_fact WHERE {WHERE}", params)  # noqa: S608
        left = conn.db.execute(f"SELECT COUNT(*) AS n FROM research_fact WHERE {WHERE}", params)[0]["n"]  # noqa: S608
        print(f"deleted; remaining older than cutoff: {left}")
    elif not args.apply:
        print("dry run: nothing deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
