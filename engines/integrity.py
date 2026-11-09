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


def expected_objects(versions: set[int] | None = None) -> dict[str, set[str]]:
    """Objects (tables, indexes, triggers, views) the repository's migrations define, by type.

    `versions` limits the set to the given migrations (default: all). Names come from a real migration run on
    an in-memory database, so they are exact, not text matches."""
    ref = SQLiteDatabase()
    try:
        if versions is None:
            migrate(ref)
        else:
            migrate(ref, directory=_subset_dir(versions))
        q = "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'"
        return {t: {r["name"] for r in ref.execute(q, (t,))} for t in ("table", "index", "trigger", "view")}
    finally:
        ref.close()


def _subset_dir(versions: set[int]):
    import shutil
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    for m in discover():
        if m.version in versions:
            shutil.copy(m.path, tmp / m.path.name)
    return tmp


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
    applied_versions = set(done) & set(repo)
    have_all = expected_objects(applied_versions) if applied_versions else {}
    for t, names in have_all.items():
        have = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = ?", (t,))}
        missing = sorted(names - have)
        if missing:
            problems.append(f"missing {t}s from applied migrations: {missing}")
        extra = sorted(have - names)
        if extra:
            notes.append(f"{t}s not defined by the applied migrations (review): {extra}")
    if pending:
        notes.append("objects of pending migrations are not checked until they are applied")
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
