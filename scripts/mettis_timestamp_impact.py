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
QUERY = "SELECT url, title, published_at, fetched_at FROM news_item WHERE source = 'mettis'"
VERSION = "mettis-tz-correction-v1"
METHOD = "stored time minus 5 hours (stored value is Pakistan wall-clock time labelled as UTC)"


def corrected_view(rows: list[dict]) -> list[dict]:
    """A versioned, read-only correction layer: every stored Mettis row with its original time, the proposed
    corrected time, the collection time, the source zone, the method and a validation status. The stored rows
    are never modified. 'valid' means the corrected time is not after the collection time; 'check' means it
    still is (the offset cannot explain it); 'unverifiable' means the row was collected long after publication
    so collection time cannot confirm or refute the offset."""
    out = []
    for r in rows:
        pub = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
        got = datetime.fromisoformat(r["fetched_at"].replace("Z", "+00:00"))
        fixed = pub - OFFSET
        lag_h = (got - pub).total_seconds() / 3600
        if lag_h < -0.1:
            status = "valid" if fixed <= got + timedelta(minutes=5) else "check"
        else:
            status = "unverifiable"
        out.append(
            {
                "url": r["url"],
                "title": r["title"][:100],
                "original_utc": r["published_at"],
                "corrected_utc": fixed.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "collected_utc": r["fetched_at"],
                "source_timezone": "Asia/Karachi (UTC+5)",
                "method": METHOD,
                "version": VERSION,
                "validation_status": status,
                "calendar_day_changes": fixed.date() != pub.date(),
            }
        )
    return out




def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("mettis_timestamp_correction_v1.json"))
    args = ap.parse_args(argv)
    db = library_db.get_library_readonly_connection().db
    rows = [dict(r) for r in db.execute(QUERY)]
    view = corrected_view(rows)
    counts = Counter(v["validation_status"] for v in view)
    out = {
        "version": VERSION,
        "method": METHOD,
        "mettis_rows": len(rows),
        "status_counts": dict(counts),
        "would_change_calendar_day": sum(1 for v in view if v["calendar_day_changes"]),
        "note": "Read-only correction layer. No stored row was changed. 'unverifiable' rows were collected "
        "long after publication, so the collection time cannot confirm the offset for them.",
        "records": view,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: v for k, v in out.items() if k != "records"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
