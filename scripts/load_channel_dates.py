"""Load a channel's verified upload dates into psx-library video_dating. Dry run by default.

Input is the yt-dlp style file the owner's phone produces: one "<video id> <YYYYMMDD>" per line. Every row is
stored as a verified, single-day interval (date_from == date_to, basis 'verified'), tagged with the channel in
`note`. Idempotent: video_id is the key, so a re-run changes nothing. Works for any channel.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0006_video_dating.sql"
_UPSERT = ("INSERT OR REPLACE INTO video_dating (video_id, date_from, date_to, basis, note) "
           "VALUES (?, ?, ?, 'verified', ?)")
BATCH = 200


def read(path: Path, channel: str) -> list[tuple[str, str, str, str]]:
    """(video_id, date_from, date_to, note) rows. Lines that are not '<id> <YYYYMMDD>' are refused."""
    rows, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"\d{8}", parts[1]):
            raise ValueError(f"line {n}: not '<video id> <YYYYMMDD>': {line!r}")
        vid, raw = parts
        day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat()  # also rejects 20261340
        if vid in seen:
            raise ValueError(f"line {n}: duplicate video id {vid}")
        seen.add(vid)
        rows.append((vid, day, day, f"verified upload date; channel={channel}"))
    return rows


def apply(rows: list[tuple[str, str, str, str]], db: Any) -> None:
    from scripts import apply_library_migration as mig

    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    for i in range(0, len(rows), BATCH):
        db.batch([(_UPSERT, (v, a, b, note)) for v, a, b, note in rows[i:i + BATCH]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dates", type=Path)
    parser.add_argument("--channel", required=True, help="short channel name, e.g. standard_capital")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    rows = read(args.dates, args.channel)
    lo, hi = min(r[1] for r in rows), max(r[1] for r in rows)
    print(f"{len(rows)} verified date(s) for {args.channel}, {lo} .. {hi}")
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply.")
        return 0
    from engines import library_db

    conn = library_db.get_library_connection()
    apply(rows, conn.db)
    print(f"stored -> {conn.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
