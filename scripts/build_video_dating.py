"""Estimate a date interval for every video and optionally load it into psx-library's video_dating table.

Reads docs/research/arn/video_index.json (title and newest-first rank per video), writes
docs/research/arn/video_dating.json, and with --apply loads the table. Dry run by default; idempotent.
Real dates, when supplied, override estimates: see load_real_dates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from engines import library_db
from engines import video_dating as vd

ARN = Path(__file__).resolve().parents[1] / "docs" / "research" / "arn"
SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0006_video_dating.sql"
_UPSERT = ("INSERT OR REPLACE INTO video_dating (video_id, date_from, date_to, basis, note) "
           "VALUES (?, ?, ?, ?, ?)")


def read_verified(path: Path) -> dict[str, str]:
    """Real publication dates, from JSON {id: date} or yt-dlp's plain output, one "id date" per line.

    Accepts YYYY-MM-DD and YYYYMMDD, separated by a space, comma or tab. A line with no usable date (yt-dlp
    prints NA) is skipped rather than guessed.
    """
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("{"):
        return {str(k): str(v) for k, v in json.loads(text).items()}
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = [x for x in line.replace(",", " ").replace("\t", " ").split() if x]
        if len(parts) < 2:
            continue
        raw = parts[-1]
        if len(raw) == 8 and raw.isdigit():
            raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        try:
            vd.date.fromisoformat(raw)
        except ValueError:
            continue
        out[parts[0]] = raw
    return out


def build(index: list[dict[str, Any]], verified: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Estimated intervals, with any VERIFIED real date replacing the estimate for its video."""
    verified = verified or {}
    rows = []
    for d in vd.estimate(index):
        if d.video_id in verified:
            real = verified[d.video_id]
            rows.append({"video_id": d.video_id, "date_from": real, "date_to": real, "basis": "verified",
                         "note": "supplied publication date"})
        else:
            start = d.date_from.isoformat() if d.date_from else None
            rows.append({"video_id": d.video_id, "date_from": start, "date_to": d.date_to.isoformat(),
                         "basis": d.basis, "note": d.note})
    return rows


def apply(rows: list[dict[str, Any]], *, write: bool, db: Any = None) -> int:
    widths = [(vd.date.fromisoformat(r["date_to"]) - vd.date.fromisoformat(r["date_from"])).days
              for r in rows if r["date_from"]]
    print(f"{len(rows)} video(s) dated; median interval {sorted(widths)[len(widths) // 2]} days")
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
    db.batch([(_UPSERT, (r["video_id"], r["date_from"], r["date_to"], r["basis"], r["note"])) for r in rows],
             transactional=True)
    held = db.execute("SELECT COUNT(*) AS n FROM video_dating")[0]["n"]
    print(f"video_dating now holds {held} row(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write to psx-library (default: dry run)")
    parser.add_argument("--verified", type=Path, default=None,
                        help="real dates: JSON {id: date}, or yt-dlp output, one 'id YYYYMMDD' per line")
    args = parser.parse_args(argv)
    index = json.loads((ARN / "video_index.json").read_text(encoding="utf-8"))
    verified = read_verified(args.verified) if args.verified else None
    rows = build(index, verified)
    (ARN / "video_dating.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    try:
        return apply(rows, write=args.apply)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
