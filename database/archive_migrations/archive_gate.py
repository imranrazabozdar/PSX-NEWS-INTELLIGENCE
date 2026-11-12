"""Archive DDL gate: the only sanctioned way to change the archive database schema.

Design (see docs/ARCHIVE_MIGRATION_SAFETY.md):

* The expected schema is DERIVED from the committed migration files. reference_fingerprint(k) applies the
  first k migrations to an in-memory database and records every table, column, index and trigger. No
  hand-maintained list can drift from the SQL.
* inventory is read from the target with SELECT and PRAGMA only.
* Before any DDL, the target must match the reference for its recorded ledger state exactly. Anything else is
  refused: unknown objects, a partly applied migration, or a modified schema.
* After DDL, the target must match the reference for the full set. A mismatch is reported with the difference
  and the run stops. Nothing is rolled back or re-run automatically.
* Real DDL requires PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL to equal the approval string exactly, the target to
  declare the archive purpose, and the connection to carry the archive role.
* A dry run executes no statement that changes anything. Tests prove this from recorded SQL.

The gate never reads or writes the operational database and never uses the operational token.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from database.connection import OPERATIONAL_TABLES, DatabaseConfigError, SQLiteDatabase
from database.migrate import MigrationError, discover, migrate

ARCHIVE_DIR = Path(__file__).resolve().parent
DDL_OPT_IN_VAR = "PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL"
DDL_OPT_IN_VALUE = "yes-execute-archive-migration-ddl"
PURPOSE = "archive"
LEDGER = "schema_migrations"


class ArchiveDDLRefused(RuntimeError):
    """The gate refused to run DDL. Nothing was changed."""


class SchemaDrift(RuntimeError):
    """The target schema does not match the reference for its ledger state. Stop and diagnose."""


def ddl_permitted(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get(DDL_OPT_IN_VAR, "") == DDL_OPT_IN_VALUE


# ------------------------------------------------------------------ structure

def _structure(db) -> dict[str, Any]:
    """Tables (with columns), indexes and triggers from sqlite_master. Read-only."""
    objs = db.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                      "OR name LIKE 'sqlite_autoindex_%' ORDER BY type, name")
    tables, indexes, triggers, views = {}, {}, {}, {}
    for o in objs:
        if o["name"] == LEDGER:
            continue  # the ledger is bookkeeping, compared separately, not part of the schema fingerprint
        if o["type"] == "table":
            cols = [(c["cid"], c["name"], (c["type"] or "").upper(), c["notnull"], c["pk"])
                    for c in db.execute(f"PRAGMA table_info({o['name']})")]  # noqa: S608 - names from sqlite_master
            tables[o["name"]] = cols
        elif o["type"] == "index":
            indexes[o["name"]] = o["tbl_name"]
        elif o["type"] == "trigger":
            triggers[o["name"]] = o["tbl_name"]
        elif o["type"] == "view":
            views[o["name"]] = o["tbl_name"]
    return {"tables": tables, "indexes": indexes, "triggers": triggers, "views": views}


def _migrations(upto: int | None = None):
    found = discover(ARCHIVE_DIR)
    return found if upto is None else found[:upto]


_REF_CACHE: dict[int, dict[str, Any]] = {}


def reference_fingerprint(upto: int) -> dict[str, Any]:
    """Structure produced by applying the first `upto` migrations to a fresh in-memory database."""
    if upto not in _REF_CACHE:
        ref = SQLiteDatabase(":memory:")
        try:
            for m in _migrations(upto):
                for stmt in m.statements():
                    ref.execute(stmt)
            _REF_CACHE[upto] = _structure(ref)
        finally:
            ref.close()
    return _REF_CACHE[upto]


def _diff(actual: dict, expected: dict) -> dict[str, Any]:
    out = {}
    for kind in ("tables", "indexes", "triggers", "views"):
        a, e = actual[kind], expected[kind]
        extra = sorted(set(a) - set(e))
        missing = sorted(set(e) - set(a))
        changed = sorted(k for k in set(a) & set(e) if a[k] != e[k])
        if extra or missing or changed:
            out[kind] = {"unexpected": extra, "missing": missing, "changed": changed}
    return out


def _ledger(db) -> list[dict]:
    if not db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (LEDGER,)):
        return []
    return [dict(r) for r in db.execute(
        "SELECT version, name, checksum, result FROM schema_migrations ORDER BY version")]


# ------------------------------------------------------------------ preflight and probe

def preflight(adb) -> dict:
    """Refuse a database that is not an archive. Read-only."""
    st = _structure(adb)
    operational = sorted(set(st["tables"]) & set(OPERATIONAL_TABLES))
    if operational:
        raise DatabaseConfigError(f"refusing: operational tables present {operational}")
    everything = reference_fingerprint(len(_migrations()))
    unknown = _diff(st, everything)
    unknown = {k: v["unexpected"] for k, v in unknown.items() if v["unexpected"]}
    if unknown:
        raise DatabaseConfigError(f"refusing: unknown schema objects {unknown}; not an archive database")
    return {"tables": sorted(st["tables"])}


def probe(adb) -> dict:
    """Read-only report: structure, ledger, state against the reference, and row counts. Writes nothing."""
    st = _structure(adb)
    ledger = _ledger(adb)
    k = len(ledger)
    state = {"ledger_versions": [r["version"] for r in ledger]}
    total = len(_migrations())
    checksums_ok = all(r["checksum"] == m.checksum for r, m in zip(ledger, _migrations(), strict=False))
    if k <= total:
        drift_vs_state = _diff(st, reference_fingerprint(k))
    else:
        drift_vs_state = {"ledger": f"{k} rows but only {total} migrations exist"}
    counts = {t: adb.execute(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]  # noqa: S608 - names from sqlite_master
              for t in st["tables"] if t != LEDGER}
    blob_columns = sorted(f"{t}.{c[1]}" for t, cols in st["tables"].items() for c in cols if "BLOB" in c[2])
    return {
        "state": state,
        "ledger": ledger,
        "ledger_checksums_match_repository": checksums_ok,
        "structure_drift_for_ledger_state": drift_vs_state,
        "fully_migrated": k == total and not drift_vs_state and checksums_ok,
        "tables": sorted(st["tables"]),
        "indexes": sorted(st["indexes"]),
        "triggers": sorted(st["triggers"]),
        "views": sorted(st["views"]),
        "row_counts": counts,
        "blob_columns": blob_columns,
        "operational_tables_present": sorted(set(st["tables"]) & set(OPERATIONAL_TABLES)),
    }


# ------------------------------------------------------------------ dry run and apply

def plan(adb) -> dict:
    """Read-only plan: what would run, with checksums. Creates nothing, writes nothing."""
    preflight(adb)
    st = _structure(adb)
    ledger = _ledger(adb)
    k = len(ledger)
    drift = _diff(st, reference_fingerprint(k)) if k <= len(_migrations()) else {"ledger": "too many rows"}
    pending = [m for m in _migrations() if m.version > k]
    return {
        "mode": "dry_run",
        "ledger_versions": [r["version"] for r in ledger],
        "structure_drift_for_ledger_state": drift,
        "pending": [{"version": m.version, "name": m.name, "checksum": m.checksum,
                     "statements": len(m.statements())} for m in pending],
        "ddl_statements_pending": sum(len(m.statements()) for m in pending),
    }


def apply(adb, *, dry_run: bool = True, purpose: str = "", env: Mapping[str, str] | None = None) -> dict:
    """Dry run: plan only. Real run: needs the purpose, the archive role, the exact approval string, a clean
    pre-state and a clean post-state. Stops on any drift; never rolls back automatically."""
    if dry_run:
        return plan(adb)
    if purpose != PURPOSE:
        raise ArchiveDDLRefused(f"DDL refused: the target must declare purpose {PURPOSE!r}")
    if getattr(adb, "role", None) != "archive":
        raise ArchiveDDLRefused("DDL refused: the connection does not carry the archive role")
    if not ddl_permitted(env):
        raise ArchiveDDLRefused(f"DDL refused: {DDL_OPT_IN_VAR} must equal the approval string")
    before = plan(adb)  # also runs preflight
    if before["structure_drift_for_ledger_state"]:
        raise SchemaDrift("pre-state drift, nothing executed: "
                          f"{before['structure_drift_for_ledger_state']}")
    if before["pending"]:
        try:
            log = migrate(adb, directory=ARCHIVE_DIR)
        except MigrationError as exc:
            raise ArchiveDDLRefused(f"migration refused: {exc}") from exc
    else:
        log = []
    after = _diff(_structure(adb), reference_fingerprint(len(_migrations())))
    if after:
        raise SchemaDrift(f"post-state drift: {after}; STOP. Do not re-run. Diagnose before any action.")
    return {"mode": "applied", "log": log, "pre_pending": [p["name"] for p in before["pending"]]}
