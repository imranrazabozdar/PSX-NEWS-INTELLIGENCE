"""Archive DDL gate: the only sanctioned way to change the archive database schema.

Not a migration (it is not `NNNN_name.sql`, so migration discovery ignores it). It provides:

* `probe(adb)`: read-only inspection of the archive database. Only SELECT and PRAGMA statements.
* `apply(adb, dry_run=..., env=...)`: runs the archive migrations. A dry run always works. Real DDL runs
  only when
  PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL equals exactly the approval string, and only after the preflight passes.
* `preflight(adb)`: refuses any database that holds operational tables, or unknown tables that are not part of
  the archive schema. A new empty database or an already-migrated archive is accepted.

The gate never reads or writes the operational database, and it never takes the operational token.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from database.connection import ARCHIVE_TABLES, OPERATIONAL_TABLES, DatabaseConfigError
from database.migrate import MigrationError, discover, migrate

ARCHIVE_DIR = Path(__file__).resolve().parent
DDL_OPT_IN_VAR = "PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL"
DDL_OPT_IN_VALUE = "yes-execute-archive-migration-ddl"
LEDGER = "schema_migrations"
EXPECTED_TABLES = frozenset(ARCHIVE_TABLES) | {LEDGER}
EXPECTED_TRIGGERS = frozenset(
    {
        "trg_archive_tuples_no_delete",
        "trg_archive_tuples_no_update",
        "trg_archive_reports_no_delete",
        "trg_archive_reports_no_update",
        "trg_archive_disclosures_no_delete",
        "trg_archive_disclosures_no_update",
    }
)


class ArchiveDDLRefused(RuntimeError):
    """The gate refused to run DDL. Nothing was changed."""


def ddl_permitted(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get(DDL_OPT_IN_VAR, "") == DDL_OPT_IN_VALUE


def _tables(adb) -> set[str]:
    return {r["name"] for r in adb.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def preflight(adb) -> dict:
    """Refuse a database that is not an archive. Returns the table list when acceptable."""
    present = _tables(adb)
    operational = present & set(OPERATIONAL_TABLES)
    if operational:
        raise DatabaseConfigError(f"refusing: operational tables present {sorted(operational)}")
    unknown = present - EXPECTED_TABLES - {"sqlite_sequence"}
    if unknown:
        raise DatabaseConfigError(
            f"refusing: unknown tables present {sorted(unknown)}; not an archive database"
        )
    return {"tables": sorted(present)}


def probe(adb) -> dict:
    """Read-only schema and state report. SELECT and PRAGMA only; nothing is written."""
    tables = sorted(_tables(adb))
    triggers = sorted(r["name"] for r in adb.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
    columns: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for t in tables:
        if t.startswith("sqlite_"):
            continue
        columns[t] = [
            {"name": c["name"], "type": c["type"], "notnull": c["notnull"], "pk": c["pk"]}
            for c in adb.execute(f"PRAGMA table_info({t})")
        ]
        # t comes from sqlite_master, never from user input
        counts[t] = adb.execute(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]  # noqa: S608
    ledger = []
    if LEDGER in tables:
        ledger = [
            dict(r)
            for r in adb.execute(
                "SELECT version, name, checksum, result FROM schema_migrations ORDER BY version"
            )
        ]
    blob_columns = sorted(
        f"{t}.{c['name']}" for t, cols in columns.items() for c in cols if "BLOB" in (c["type"] or "").upper()
    )
    return {
        "tables": tables,
        "triggers": triggers,
        "columns": columns,
        "row_counts": counts,
        "ledger": ledger,
        "blob_columns": blob_columns,
        "operational_tables_present": sorted(set(tables) & set(OPERATIONAL_TABLES)),
        "unknown_tables": sorted(
            set(tables)
            - EXPECTED_TABLES
            - {"sqlite_sequence"}
            - {t for t in tables if t.startswith("sqlite_")}
        ),
        "expected_schema_present": EXPECTED_TABLES.issubset(set(tables)),
        "missing_triggers": sorted(EXPECTED_TRIGGERS - set(triggers)),
    }


def apply(adb, *, dry_run: bool = True, env: Mapping[str, str] | None = None) -> dict:
    """Dry run: report pending migrations and checksums, change nothing.

    Real run: needs the approval string."""
    preflight(adb)
    if dry_run:
        return {
            "mode": "dry_run",
            "log": migrate(adb, dry_run=True, directory=ARCHIVE_DIR),
            "pending": [m.name for m in discover(ARCHIVE_DIR)],
            "checksums": {m.name: m.checksum for m in discover(ARCHIVE_DIR)},
        }
    if not ddl_permitted(env):
        raise ArchiveDDLRefused(
            f"DDL refused: {DDL_OPT_IN_VAR} must equal the approval string; nothing changed"
        )
    try:
        log = migrate(adb, directory=ARCHIVE_DIR)
    except MigrationError as exc:
        raise ArchiveDDLRefused(f"migration refused: {exc}") from exc
    return {"mode": "applied", "log": log}
