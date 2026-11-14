"""Read-only check of research_fact in psx-library: counts per company and topic, and the latest rows.

Only SELECT statements are run. No writes, no requests to any data source. Runs through the guarded connection
(engines/library_db.py), so the target guard applies.
"""

from __future__ import annotations

import sys

from engines import library_db

SELECTS = (
    "SELECT company, COUNT(*) AS n FROM research_fact GROUP BY company ORDER BY company",
    "SELECT topic, COUNT(*) AS n FROM research_fact GROUP BY topic ORDER BY topic",
    "SELECT id, company, topic, fact_text, value, unit, period, source_name, source_date, confidence "
    "FROM research_fact ORDER BY id DESC LIMIT 5",
)


def main() -> int:
    try:
        conn = library_db.get_library_connection()
    except library_db.LibraryConfigError as exc:
        print(f"check REFUSED: {exc}")
        return 2
    print(f"read-only check on host={conn.host}")
    for sql in SELECTS:
        for row in conn.db.execute(sql):
            print(f"  {dict(row)}")
        print("---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
