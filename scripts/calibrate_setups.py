"""Walk-forward check of the technical setups score on the stored daily bars. Read only.

python -m scripts.calibrate_setups
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines import library_db, setups_calibration
from scripts import explain_moves


def main() -> int:
    db = library_db.get_library_readonly_connection().db
    db.max_rows_read = max(db.max_rows_read, 400_000)
    db.max_rows_written = 1
    bars = explain_moves.load_bars(db, datetime.now(UTC).date(), 200)
    sessions = sorted({r["trade_date"] for b in bars.values() for r in b})
    print(f"{len(bars)} symbols, {len(sessions)} sessions ({sessions[0]} to {sessions[-1]})")
    text = setups_calibration.report(setups_calibration.run(bars))
    text += "\n" + setups_calibration.robustness_report(bars)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        Path(path).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
