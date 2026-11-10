"""Migration runner (spec section 11.1).

* Migrations are `database/migrations/NNNN_name.sql`, applied in order.
* `schema_migrations` records version, name, SHA-256 checksum, applied time and result.
* Each migration and its bookkeeping row commit atomically, so a failure leaves nothing applied.
* Re-running is safe: applied migrations are skipped. If an applied migration's file has
  changed, the runner refuses to continue (edit history by adding a new migration).
* Destructive statements (DROP, DELETE, TRUNCATE-style rewrites) are refused. Spec 11.1 forbids
  destructive migrations without a backup and the owner's approval.

Usage: python -m database.migrate [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from database.connection import Database, DatabaseError, connect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_DESTRUCTIVE = re.compile(
    r"\b(DROP\s+(TABLE|INDEX|VIEW|TRIGGER|COLUMN)|DELETE\s+FROM|ALTER\s+TABLE\s+\S+\s+DROP|"
    r"ALTER\s+TABLE\s+\S+\s+RENAME)\b", re.IGNORECASE)

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version        INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    checksum       TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at_utc TEXT NOT NULL,
    result         TEXT NOT NULL CHECK (result IN ('applied'))
)"""


class MigrationError(DatabaseError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def statements(self) -> list[str]:
        return split_statements(self.sql)


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into complete statements (handles CREATE TRIGGER ... END;)."""
    statements, buf = [], []
    for line in sql.splitlines():
        if not buf and (not line.strip() or line.strip().startswith("--")):
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip().rstrip(";").strip())
            buf = []
    if "".join(buf).strip():
        raise MigrationError("migration ends with an incomplete statement")
    return statements


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for p in sorted(directory.glob("*.sql")):
        m = _NAME.match(p.name)
        if not m:
            raise MigrationError(f"bad migration file name: {p.name}")
        found.append(Migration(int(m.group(1)), m.group(2), p, p.read_text(encoding="utf-8")))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migration versions must be contiguous from 1, got {versions}")
    for mig in found:
        for stmt in mig.statements():
            code = re.sub(r"--[^\n]*", "", stmt)
            if _DESTRUCTIVE.search(code):
                raise MigrationError(f"{mig.path.name}: destructive statement refused: {code[:80]}")
    return found


def applied(db: Database, *, create: bool = True) -> dict[int, dict]:
    """Applied migrations by version. With create=False (dry run) nothing is written: a missing ledger is
    treated as empty instead of being created."""
    if create:
        db.execute(SCHEMA_MIGRATIONS_DDL)
    elif not db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"):
        return {}
    return {r["version"]: r for r in db.execute(
        "SELECT version, name, checksum, applied_at_utc FROM schema_migrations ORDER BY version")}


def migrate(db: Database, *, dry_run: bool = False,
            directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns a log of what happened."""
    log = []
    migrations = discover(directory)
    done = applied(db, create=not dry_run)  # a dry run issues no DDL
    for v, row in done.items():
        known = {m.version: m for m in migrations}
        if v not in known:
            raise MigrationError(f"database has migration {v} that is not in the repository")
        if row["checksum"] != known[v].checksum:
            raise MigrationError(
                f"migration {v} ({row['name']}) was changed after it was applied; "
                "add a new migration instead of editing an applied one")
    for mig in migrations:
        if mig.version in done:
            log.append(f"skip   {mig.version:04d}_{mig.name} (already applied)")
            continue
        if dry_run:
            log.append(f"would apply {mig.version:04d}_{mig.name} ({len(mig.statements())} statements)")
            continue
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stmts = [(s, ()) for s in mig.statements()]
        stmts.append(("INSERT INTO schema_migrations(version, name, checksum, applied_at_utc, result) "
                      "VALUES (?, ?, ?, ?, 'applied')", (mig.version, mig.name, mig.checksum, now)))
        db.batch(stmts, transactional=True)
        log.append(f"apply  {mig.version:04d}_{mig.name} ({len(stmts) - 1} statements) OK")
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    db = connect()
    print(db.validate())
    for line in migrate(db, dry_run=args.dry_run):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
