"""Apply the approved fetch-state migration to psx-library, and nothing else.

Guarded: the connection goes through engines.library_db (the target guard refuses any host that is not
psx-library, and any production, data-capture or archival host). Only statements of the form
CREATE TABLE IF NOT EXISTS are executed; anything else in the file aborts before the first write.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

from engines import library_db

MIGRATION = Path(__file__).resolve().parents[1] / "database" / "library" / "0001_fetch_state.sql"
EXPECTED = ("fetch_control", "fetch_progress", "fetch_log")
_CREATE = re.compile(r"^CREATE TABLE IF NOT EXISTS [a-z_]+ \(", re.IGNORECASE)


def statements(sql: str) -> list[str]:
    """Strip comments, split on ';', and refuse anything that is not a state-table creation."""
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    out = [s.strip() for s in body.split(";") if s.strip()]
    for stmt in out:
        if not _CREATE.match(stmt):
            raise ValueError(f"refused: migration may only create state tables, found: {stmt[:60]!r}")
    return out


def apply(environ: Mapping[str, str] | None = None, sql: str | None = None) -> int:
    try:
        conn = library_db.get_library_connection(environ)  # target guard runs here
    except library_db.LibraryConfigError as exc:
        print(f"migration REFUSED: {exc}")
        return 2
    todo = statements(sql if sql is not None else MIGRATION.read_text(encoding="utf-8"))
    for stmt in todo:
        conn.db.execute(stmt)
    names = {r["name"] for r in conn.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in EXPECTED if t not in names]
    print(f"migration applied to host={conn.host}: {len(todo)} statement(s)")
    print(f"state tables present: {[t for t in EXPECTED if t in names]}")
    if missing:
        print(f"MISSING after migration: {missing}")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(apply())  # run as: python -m scripts.apply_library_migration
