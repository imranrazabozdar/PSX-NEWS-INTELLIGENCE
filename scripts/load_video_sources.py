"""Load the per-video recency index into psx-library's video_source table.

The index (docs/research/arn/video_index.json) says, for every video in the archive, where it sits in the
newest-first ordering. Dry run by default. Idempotent: re-running replaces a video's row, never duplicates it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from engines import library_db

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0005_video_source.sql"
INDEX = Path(__file__).resolve().parents[1] / "docs" / "research" / "arn" / "video_index.json"
CHANNEL = "Abdul Rehman Najam"
_UPSERT = ("INSERT OR REPLACE INTO video_source (video_id, title, channel, archive_position, sector_bucket, "
           "url, speaker_may_differ, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")


def load_index(path: Path = INDEX) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    positions = [r["archive_position"] for r in rows]
    if len(set(positions)) != len(positions):
        raise ValueError("archive_position must be unique: it is a rank")
    if len({r["video_id"] for r in rows}) != len(rows):
        raise ValueError("video_id must be unique")
    return rows


def apply(rows: list[dict[str, Any]], *, write: bool, db: Any = None) -> int:
    print(f"index valid: {len(rows)} video(s); newest = position 0")
    if not write:
        print("dry run: nothing written. Re-run with --apply to write.")
        return 0
    if db is None:
        conn = library_db.get_library_connection()  # target guard runs here
        db = conn.db
        print(f"target host: {conn.host}")
    from scripts import apply_library_migration as mig

    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    for r in rows:
        db.execute(_UPSERT, (r["video_id"], r["title"], CHANNEL, r["archive_position"], r["sector_bucket"],
                             r["url"], int(bool(r["speaker_may_differ"])), r["status"]))
    n = db.execute("SELECT COUNT(*) AS n FROM video_source")[0]["n"]
    print(f"video_source now holds {n} row(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write to psx-library (default: dry run)")
    args = parser.parse_args(argv)
    try:
        return apply(load_index(), write=args.apply)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
