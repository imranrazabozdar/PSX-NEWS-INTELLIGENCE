"""Read-only impact report for the Mettis timestamp offset. Changes NOTHING.

    python -m scripts.mettis_timestamp_impact --out mettis_timestamp_impact.json

For every stored Mettis item it shows how far the stored publication time is from the time it was collected
and what the corrected time would be (stored minus 5 hours, the Pakistan offset). A historical rewrite is NOT
made by this script and needs the owner's separate approval; this is only the evidence for that decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from engines import library_db

OFFSET = timedelta(hours=5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("mettis_timestamp_impact.json"))
    args = ap.parse_args(argv)
    db = library_db.get_library_readonly_connection().db
    rows = db.execute("SELECT url, title, published_at, fetched_at FROM news_item WHERE source = 'mettis'")
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    future, ok, bad = [], 0, 0
    bucket: Counter = Counter()
    for r in rows:
        try:
            pub, got = parse(r["published_at"]), parse(r["fetched_at"])
        except (TypeError, ValueError, AttributeError):
            bad += 1
            continue
        lag_h = (got - pub).total_seconds() / 3600
        bucket["published_after_collected" if lag_h < -0.1 else "ok"] += 1
        if lag_h < -0.1:
            future.append(
                {
                    "url": r["url"],
                    "title": r["title"][:100],
                    "stored": r["published_at"],
                    "collected": r["fetched_at"],
                    "corrected": (pub - OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "stored_day_changes": (pub - OFFSET).date() != pub.date(),
                }
            )
        else:
            ok += 1
    out = {
        "mettis_rows": len(rows),
        "unparseable": bad,
        "stored_after_collection": len(future),
        "consistent": ok,
        "would_change_calendar_day": sum(1 for f in future if f["stored_day_changes"]),
        "note": "No row was changed. Rows collected long after publication (back-fill) look consistent even "
        "if offset, so 'consistent' is not proof they are right.",
        "sample": future[:25],
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: v for k, v in out.items() if k != "sample"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
