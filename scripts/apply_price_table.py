"""Create the price_daily table on psx-library (migration 0012) and nothing else.

Guarded like the other library migrations: the connection goes through engines.library_db (target guard) and
the only statement allowed is the one CREATE TABLE IF NOT EXISTS in database/library/0012_price_daily.sql.
"""

from __future__ import annotations

import sys
from pathlib import Path

from engines import library_db

FILE = Path(__file__).resolve().parents[1] / "database" / "library" / "0012_price_daily.sql"
_HEAD = "CREATE TABLE IF NOT EXISTS price_daily ("


def statements(sql: str) -> list[str]:
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    out = [s.strip() for s in body.split(";") if s.strip()]
    if len(out) != 1 or not out[0].startswith(_HEAD):
        raise ValueError("refused: the migration must be exactly one CREATE TABLE IF NOT EXISTS price_daily")
    return out


def main() -> int:
    todo = statements(FILE.read_text(encoding="utf-8"))
    try:
        conn = library_db.get_library_connection()  # target guard runs here
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2
    for stmt in todo:
        conn.db.execute(stmt)
    print("0012: price_daily is in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
