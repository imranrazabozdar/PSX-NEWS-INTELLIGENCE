"""Build the daily digest (engines/daily_digest.py) from psx-library. Read only: no database is written."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engines import daily_digest, library_db, move_explainer
from scripts import build_radar, explain_moves

PROBES = ("HBL", "OGDC", "PSO")  # reference symbols: the newest stored price day, one indexed row each


def latest_price_day(db: Any) -> str | None:
    """The newest stored price day, from one indexed row of a reference symbol. Costs a single row read."""
    for sym in PROBES:
        rows = db.execute(
            "SELECT trade_date FROM price_daily WHERE symbol = ? ORDER BY trade_date DESC LIMIT 1", (sym,)
        )
        if rows:
            return str(rows[0]["trade_date"])
    return None


def build(db: Any, today_dt: datetime, days: int = 3, top: int = 10) -> str:
    today = today_dt.date()
    bars = explain_moves.load_bars(db, today, 10)
    moves = move_explainer.daily_moves(bars)
    day = daily_digest.latest_trading_day(moves)
    br = daily_digest.breadth(moves, day) if day else None
    radar, _ = build_radar.build(db, today, days, top)
    items, universe = explain_moves.build(db, today, days, 40)
    news_day = db.execute("SELECT MAX(day) AS d FROM news_rollup")[0]["d"]
    fresh = {
        "latest price day": day,
        "latest news day": news_day,
        "digest built (UTC)": today_dt.strftime("%Y-%m-%d %H:%M"),
    }
    return daily_digest.render(today.isoformat(), day, br, radar, items, fresh, universe)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=Path(".digest"))
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument(
        "--probe",
        action="store_true",
        help="print the newest stored price day (for the once-a-day gate) and stop",
    )
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    if args.probe:
        day = latest_price_day(db) or "none"
        print(f"latest_price_day={day}")
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"day={day}\n")
        return 0
    md = build(db, datetime.now(UTC), args.days)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "digest.md").write_text(md, encoding="utf-8")
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    print(md)
    print(f"usage: {db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
