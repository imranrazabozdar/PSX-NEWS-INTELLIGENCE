"""Print where chosen symbols stand in the setups rankings, with every score and its evidence. Read only.

    python -m scripts.setups_check --symbols MARI,HUBC
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from engines import library_db, market_dashboard, setups


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", required=True)
    args = ap.parse_args(argv)
    db = library_db.get_library_readonly_connection().db
    db.max_rows_read = max(db.max_rows_read, 400_000)
    db.max_rows_written = 1
    data = market_dashboard.load(db, datetime.now(UTC))
    s = data["setups"]
    print(f"{s['eligible']} stocks assessed; prices to {data['price_day']}")
    for kind in ("technical", "fundamental", "combined"):
        print(f"top 10 {kind}: " + ", ".join(f"{r['symbol']} {r[kind]:.0f}" for r in s[kind]))
    for sym in (x.strip() for x in args.symbols.split(",") if x.strip()):
        found = setups.lookup(s, sym)
        print(f"--- {found['symbol']}")
        print(json.dumps(found, indent=1, default=str))
        drivers = next((r["drivers"] for r in data["radar_all"] if r["symbol"] == found["symbol"]), [])
        print("radar drivers:", json.dumps(drivers, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
