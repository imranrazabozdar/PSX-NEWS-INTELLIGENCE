"""Build the daily news rollup and signals from stored headlines (dry run unless --apply).

    python -m scripts.build_news_rollup --out signals.json [--days 60] [--apply]

--apply upserts news_rollup rows (one per day and entity) and nothing else. Signals are only written to --out;
they are loaded with `python -m scripts.absorb_sector_capsule signals.json --apply`, which skips repeats.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines import library_db, news_rollup
from scripts import build_news_capsule as bnc

UPSERT = (
    "INSERT INTO news_rollup (day, entity, stories, topics, top_title, top_url, updated_utc) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(day, entity) DO UPDATE SET stories = excluded.stories, "
    "topics = excluded.topics, top_title = excluded.top_title, top_url = excluded.top_url, "
    "updated_utc = excluded.updated_utc"
)
SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0009_news_rollup.sql"


def changed_rows(db, rows: list[dict]) -> list[dict]:
    """Only the rollup rows that are new or differ from what is stored; a no-change re-run writes nothing.

    One indexed range read of the stored window (the primary key starts with day), then a comparison."""
    if not rows:
        return []
    first = min(r["day"] for r in rows)
    stored = {
        (r["day"], r["entity"]): (r["stories"], r["topics"], r["top_url"])
        for r in db.execute(
            "SELECT day, entity, stories, topics, top_url FROM news_rollup WHERE day >= ?", (first,)
        )
    }
    return [
        r for r in rows if stored.get((r["day"], r["entity"])) != (r["stories"], r["topics"], r["top_url"])
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    facts, n_items, _seen = bnc.build(db, args.days)
    rows = news_rollup.rollup(facts)
    now = datetime.now(UTC)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sigs = news_rollup.signals(rows, now.date(), stamp)
    print(
        f"headlines read: {n_items}; fact rows: {len(facts)}; rollup rows: {len(rows)}; signals: {len(sigs)}"
    )
    for s in sigs[:10]:
        print("  signal:", s["fact_text"])
    if args.apply:
        body = "\n".join(ln.split("--", 1)[0] for ln in SCHEMA.read_text("utf-8").splitlines())
        db.execute(body.split(";")[0].strip())
        changed = changed_rows(db, rows)
        for i in range(
            0, len(changed), 200
        ):  # one request per 200 rows, and only rows that differ are written
            db.batch(
                [
                    (
                        UPSERT,
                        (
                            r["day"],
                            r["entity"],
                            r["stories"],
                            r["topics"],
                            r["top_title"],
                            r["top_url"],
                            stamp,
                        ),
                    )
                    for r in changed[i : i + 200]
                ],
                transactional=True,
            )
        print(f"news_rollup: {len(rows)} rows built, {len(changed)} new or changed rows written")
    else:
        print("dry run: nothing was written to the database")
    if sigs:
        args.out.write_text(json.dumps(sigs, ensure_ascii=False), encoding="utf-8")
        print(f"signal capsule written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
