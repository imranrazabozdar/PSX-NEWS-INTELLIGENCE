"""One-off: copy the 12 Nov 2026 Investify pilot pages from the local pilot SQLite file into psx-library.

The pages were fetched once, under consent, before psx-library was connected. This makes NO request to
Investify. Each page is mapped with the tick's own code (engines/research_facts.py), written through the
guarded connection (engines/library_db.py), and marked done in fetch_progress so the tick does not fetch it
again. A page whose rows are already present is skipped. Default is a dry run; pass --apply to write.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from engines import library_db
from engines import research_facts as rf
from engines.autonomous_tick import LibraryState


def pilot_pages(path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # read-only: the pilot file is never modified
    con.row_factory = sqlite3.Row
    pages = []
    for r in con.execute("SELECT canonical_url, source_metadata_json FROM source_items "
                         "WHERE source_id LIKE 'investify%' ORDER BY collected_at_utc"):
        meta = json.loads(r["source_metadata_json"])
        rows = rf.rows_from_fields(company=meta["symbol"], endpoint=meta["endpoint"],
                                   fields=meta.get("fields") or {}, url=r["canonical_url"],
                                   fetched_at_utc=meta["fetched_at_utc"])
        pages.append({"key": f"{meta['symbol']}:{meta['endpoint']}", "symbol": meta["symbol"],
                      "endpoint": meta["endpoint"], "fetched": meta["fetched_at_utc"][:10], "rows": rows})
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pilot-db", required=True, type=Path)
    ap.add_argument("--apply", action="store_true", help="write to psx-library (default: dry run)")
    args = ap.parse_args(argv)
    pages = pilot_pages(args.pilot_db)
    for p in pages:
        print(f"{p['key']:<22} fetched {p['fetched']}  {len(p['rows'])} rows")
    if not args.apply:
        print("dry run: nothing written")
        return 0
    try:
        conn = library_db.get_library_connection()  # target guard runs here
    except library_db.LibraryConfigError as exc:
        print(f"import REFUSED: {exc}")
        return 2
    library_db.auth_check(conn)
    state = LibraryState(conn.db)
    done = state.load_done()
    for p in pages:
        present = conn.db.execute(
            "SELECT COUNT(*) AS n FROM research_fact WHERE company = ? AND topic LIKE ? AND source_date = ?",
            (p["symbol"], f"{p['endpoint']}.%", p["fetched"]))[0]["n"]
        if present or p["key"] in done:
            print(f"{p['key']:<22} skipped: already in psx-library ({present} rows) or marked done")
            continue
        if not p["rows"]:
            print(f"{p['key']:<22} skipped: no rows; left pending for the tick")
            continue
        written = rf.insert_rows(conn.db, p["rows"])
        state.save_done(p["key"])
        print(f"{p['key']:<22} wrote {written} rows; marked done")
    print(f"import finished on host={conn.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
