"""Create the company index on psx-library research_fact (0010), and nothing else.

Guarded like the other library migrations: the connection goes through engines.library_db (target guard),
and only the one `CREATE INDEX IF NOT EXISTS idx_research_fact_company` statement is allowed to run.
Reads the table once to build the index, so run it on its own, not during a collector or council run.

    python -m scripts.apply_research_fact_index
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

from engines import library_db

MIGRATION = Path(__file__).resolve().parents[1] / "database" / "library" / "0010_research_fact_index.sql"
_ALLOWED = re.compile(
    r"^CREATE INDEX IF NOT EXISTS idx_research_fact_company ON research_fact \(company, topic\)$",
    re.IGNORECASE,
)


def statements(sql: str) -> list[str]:
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    out = [s.strip() for s in body.split(";") if s.strip()]
    for stmt in out:
        if not _ALLOWED.match(" ".join(stmt.split())):
            raise ValueError(f"refused: only the company index may be created, found {stmt[:60]!r}")
    return out


def apply(environ: Mapping[str, str] | None = None, sql: str | None = None, db=None) -> int:
    todo = statements(sql if sql is not None else MIGRATION.read_text(encoding="utf-8"))
    if db is None:
        try:
            conn = library_db.get_library_connection(environ)  # target guard runs here
        except library_db.LibraryConfigError as exc:
            print(f"index REFUSED: {exc}")
            return 2
        db = conn.db
    for stmt in todo:
        db.execute(stmt)
    print(f"index applied: {len(todo)} statement(s)")
    return 0


if __name__ == "__main__":
    sys.exit(apply())
