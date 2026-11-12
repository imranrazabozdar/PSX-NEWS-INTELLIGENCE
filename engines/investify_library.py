"""The company-data LIBRARY database: target guard, and a synthetic end-to-end dry run.

Guard: a library URL must name the library, must not look like production or the data-capture database,
and must be present. The guard refuses otherwise. It never prints the URL's credentials.

Dry run: a FIXTURE payload goes through the real pipeline (parse, distill to structured fields, store,
read back, verify) under a clearly synthetic symbol. It uses a disposable in-memory database, because
source_items is append-only: a test row cannot be deleted from it, so the only clean-up is to discard
the database.
No network. No Investify traffic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collectors import investify_fundamentals as fund
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import investify_extract as x

LIBRARY_MARKER = "psx-library"  # the host must name the dedicated library database
# Any of these in the URL refuses the run. They cover the production, data-capture and archival databases.
FORBIDDEN_MARKERS = ("data-capture", "data-archival", "archival", "archive", "production", "prod", "capture")
# The approved probe table for the link test. Approved by the owner; created only in the library database.
PROBE_TABLE_DDL = ("CREATE TABLE IF NOT EXISTS library_probe (marker TEXT PRIMARY KEY, source TEXT NOT NULL, "
                   "payload TEXT NOT NULL CHECK (length(payload) < 1024))")
SYNTHETIC_SYMBOL = "ZZTEST"  # clearly synthetic: no listed company uses it
FIXTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "investify"
           / "fundamentals_synthetic.html")


class LibraryTargetError(RuntimeError):
    """The configured library target is missing, or resolves to a database the library must never touch."""


def check_library_target(url: str | None) -> str:
    """Return the database name for logging, or raise. Refuses before any write. Never returns credentials."""
    if not url:
        raise LibraryTargetError("library database URL is not set (set PSXNI_LIBRARY_TURSO_DATABASE_URL "
                                 "through the secure secret flow; never paste it)")
    host = url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower()
    if any(m in host for m in FORBIDDEN_MARKERS):
        raise LibraryTargetError("refused: the URL resolves to a production, data-capture or archival "
                                 "database")
    if LIBRARY_MARKER not in host:
        raise LibraryTargetError("refused: the URL does not name the psx-library database")
    return host.split(".", 1)[0]


def link_test(db: Any, *, marker: str = "psxni-link-test-0001") -> dict[str, Any]:
    """Write ONE synthetic record to the probe table, read it back, and delete it. The record is marked as
    a test. The delete runs in a finally block, so a mismatch cannot leave the record behind."""
    payload = json.dumps({"synthetic": True, "purpose": "library link test", "source": "test"},
                         sort_keys=True)
    if len(payload.encode("utf-8")) >= 1024:
        raise ValueError("probe payload must be under 1 KB")
    db.execute(PROBE_TABLE_DDL)
    try:
        db.execute("INSERT INTO library_probe (marker, source, payload) VALUES (?, ?, ?)",
                   (marker, "test", payload))
        rows = db.execute("SELECT source, payload FROM library_probe WHERE marker = ?", (marker,))
        matched = bool(rows) and rows[0]["source"] == "test" and rows[0]["payload"] == payload
    finally:
        db.execute("DELETE FROM library_probe WHERE marker = ?", (marker,))
    remaining = db.execute("SELECT COUNT(*) AS n FROM library_probe WHERE marker = ?", (marker,))[0]["n"]
    return {"written": True, "read_back": matched, "deleted": remaining == 0, "marker": marker}


def synthetic_dry_run(db: SQLiteDatabase) -> dict[str, Any]:
    """Parse the fixture, distill it, store it, read it back, verify it. The handle must be disposable."""
    migrate(db)
    seed_loader.load(db)
    body = FIXTURE.read_bytes()
    fields = x.parse_fundamentals(body, SYNTHETIC_SYMBOL)  # parse and distill to structured fields
    outcome = fund.store_structured(db, endpoint="fundamentals", symbol=SYNTHETIC_SYMBOL, fields=fields,
                                    url=f"https://www.investify.pk/company/{SYNTHETIC_SYMBOL}/fundamentals",
                                    fetched_at_utc="2026-11-12T00:00:00Z", http_status=200)
    rows = db.execute("SELECT source_metadata_json FROM source_items WHERE source_id = ? AND external_id = ?",
                      (fund.SOURCE_ID, f"{SYNTHETIC_SYMBOL}:fundamentals"))
    import json

    read_back = json.loads(rows[0]["source_metadata_json"])["fields"] if rows else None
    verified = read_back == fields and read_back["metric_count"] == fields["metric_count"]
    return {"symbol": SYNTHETIC_SYMBOL, "stored": outcome, "read_back": bool(rows),
            "metric_count": fields["metric_count"], "verified": verified, "source": "investify.pk",
            "synthetic": True}
