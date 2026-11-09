"""Read-only database integrity check (master plan M10; docs/OPERATIONS_RUNBOOK.md).

Compares a database with the repository's migrations without writing anything:
* every applied migration's checksum matches the repository file, and none is missing or unknown;
* every trigger and index the migrations define exists (append-only and immutability guards included);
* `PRAGMA foreign_key_check` reports no violations.
Run it before and after a backup restore, a rehearsal or an approved production migration:
    python -m engines.integrity
"""

from __future__ import annotations

import json
import sys

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import discover, migrate


def expected_objects() -> dict[str, set[str]]:
    ref = SQLiteDatabase()
    migrate(ref)
    q = "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'"
    out = {t: {r["name"] for r in ref.execute(q, (t,))} for t in ("trigger", "index")}
    ref.close()
    return out


def check(db) -> dict:
    problems, notes = [], []
    repo = {m.version: m for m in discover()}
    try:  # read only: never create schema_migrations here (the runner's applied() would)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"):
            return {"state": "problems", "problems": ["schema_migrations table is absent"], "applied": [],
                    "pending": sorted(repo), "notes": []}
        done = {r["version"]: r for r in db.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version")}
    except DatabaseError as exc:
        return {"state": "error", "problems": [f"schema_migrations unreadable: {str(exc)[:160]}"]}
    for v, row in done.items():
        if v not in repo:
            problems.append(f"migration {v} is applied but not in the repository")
        elif row["checksum"] != repo[v].checksum:
            problems.append(f"migration {v} ({row['name']}) checksum differs from the repository file")
    pending = sorted(set(repo) - set(done))
    if pending:
        notes.append(f"pending migrations (not applied): {pending}")
    exp = expected_objects()
    for t, names in exp.items():
        have = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = ?", (t,))}
        # objects of pending migrations are not expected yet
        pending_defs = " ".join(repo[v].sql for v in pending)
        missing = sorted(n for n in names - have if n not in pending_defs)
        if missing:
            problems.append(f"missing {t}s: {missing}")
    try:
        fk = db.execute("PRAGMA foreign_key_check")
        if fk:
            problems.append(f"{len(fk)} foreign-key violation(s), first: {dict(fk[0])}")
    except DatabaseError as exc:
        notes.append(f"foreign_key_check not available: {str(exc)[:120]}")
    return {"state": "ok" if not problems else "problems", "applied": sorted(done), "pending": pending,
            "problems": problems, "notes": notes}


def main(argv: list[str] | None = None) -> int:
    from database.connection import connect

    db = connect()
    try:
        out = check(db)
    finally:
        db.close()
    print(json.dumps(out, indent=1))
    return 0 if out["state"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
