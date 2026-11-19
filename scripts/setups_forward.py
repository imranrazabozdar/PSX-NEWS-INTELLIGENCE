"""Record today's live setups top 10 and score the older snapshots. Read only on the library.

    python -m scripts.setups_forward --file .setups_forward/snapshots.jsonl

The snapshots file is private (carried between runs by the Actions cache); nothing is written to the library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines import library_db, market_dashboard, setups_forward
from scripts import explain_moves


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", type=Path, default=Path(".setups_forward/snapshots.jsonl"))
    args = ap.parse_args(argv)
    args.file.parent.mkdir(parents=True, exist_ok=True)
    snaps = (
        [json.loads(line) for line in args.file.read_text("utf-8").splitlines()] if args.file.exists() else []
    )
    db = library_db.get_library_readonly_connection().db
    db.max_rows_read = max(db.max_rows_read, 400_000)
    db.max_rows_written = 1
    now = datetime.now(UTC)
    data = market_dashboard.load(db, now)
    day = data["price_day"]
    bars = explain_moves.load_bars(db, now.date(), 200)
    if day and day not in {s["day"] for s in snaps}:
        snap = setups_forward.snapshot(data["setups"], bars, day)
        snaps.append(snap)
        with args.file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap, sort_keys=True) + "\n")
        print(
            f"recorded the {day} snapshot: " + ", ".join(f"{t} {len(v)}" for t, v in snap["tracks"].items())
        )
    else:
        print(f"snapshot for {day} already recorded")
    problems = setups_forward.validate_snapshots(snaps)
    if problems:
        print("SNAPSHOT FILE PROBLEMS:", problems)
        return 2
    scored = setups_forward.evaluate(snaps, bars)
    results = setups_forward.results_payload(snaps, scored, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    (args.file.parent / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    text = setups_forward.report(snaps, scored)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
