"""Dry run of the technical-engine link (ADR-0008, Schedule A approved 2026-11-17).
Per allowlisted table: row count, symbols, date range and two sample rows. Read only; stores nothing."""

from __future__ import annotations

import sys

from engines import technical_link as tl

DATE_COL = {
    "daily_ohlc": "trade_date", "wyckoff_accumulation": "scan_date", "wyckoff_scans": "scan_date",
    "chart_patterns": "signal_date", "fire_events": "event_date", "snapshots": "ts",
    "backtest_runs": "run_at",
}
HAS_SYMBOL = {"stocks", "daily_ohlc", "wyckoff_accumulation", "chart_patterns", "fire_events", "snapshots"}
ROW_CAP = 3_000_000


def main() -> int:
    try:
        link = tl.connect(row_cap=ROW_CAP)
    except tl.LinkError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"target host: {link.host} (read only; nothing stored)")
    for obj in sorted(tl.ALLOWED_OBJECTS):
        d = DATE_COL.get(obj)
        parts = ["COUNT(*) AS n"]
        if obj in HAS_SYMBOL:
            parts.append("COUNT(DISTINCT symbol) AS symbols")
        if d:
            parts += [f"MIN({d}) AS first", f"MAX({d}) AS last"]
        try:
            stat = link.select_from(obj, f"SELECT {', '.join(parts)} FROM {obj}")[0]  # noqa: S608 - names come from the fixed allowlist
            order = f" ORDER BY {d} DESC" if d else ""
            sample = link.select_from(obj, f"SELECT * FROM {obj}{order} LIMIT 2")  # noqa: S608 - fixed allowlist
        except Exception as exc:  # noqa: BLE001 - one table failing must not hide the others
            print(f"TECH_DRYRUN {obj}: ERROR {exc}")
            continue
        print(f"TECH_DRYRUN {obj}: {dict(stat)}")
        for row in sample:
            print(f"TECH_SAMPLE {obj}: {str(dict(row))[:400]}")
    print(f"usage: {link.db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
