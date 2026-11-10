"""Read-only probe and dry run of the archive database. Writes nothing; issues no DDL.

Uses PSXNI_ARCHIVE_TURSO_URL and PSXNI_ARCHIVE_TURSO_AUTH_TOKEN only. Prints the probe report and the dry-run
migration plan as JSON. The operational database is never opened.

Usage: python -m scripts.archive_probe
"""

from __future__ import annotations

import json
import sys

from database.archive_migrations import archive_gate as gate
from database.connection import connect_archive


def run() -> dict:
    adb = connect_archive()  # refuses the operational URL and any database holding operational tables
    try:
        report = {"probe": gate.probe(adb)}
        report["dry_run"] = gate.apply(adb, dry_run=True)
        return report
    finally:
        adb.close()


if __name__ == "__main__":
    try:
        print(json.dumps(run(), indent=2, sort_keys=True, default=str))
    except Exception as exc:  # report the refusal; never retry or change anything
        print(json.dumps({"status": "refused_or_failed", "error": type(exc).__name__,
                          "detail": str(exc)[:500]}))
        sys.exit(1)
