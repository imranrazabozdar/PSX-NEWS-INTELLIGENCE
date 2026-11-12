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

from pathlib import Path
from typing import Any

from collectors import investify_fundamentals as fund
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import investify_extract as x

LIBRARY_MARKER = "library"  # the URL must name the library database
FORBIDDEN_MARKERS = ("prod", "production", "capture", "data-capture", "live")
SYNTHETIC_SYMBOL = "ZZTEST"  # clearly synthetic: no listed company uses it
FIXTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "investify"
           / "fundamentals_synthetic.html")


class LibraryTargetError(RuntimeError):
    """The configured library target is missing, or resolves to a database the library must never touch."""


def check_library_target(url: str | None) -> str:
    """Return the database name, or raise. Never returns credentials."""
    if not url:
        raise LibraryTargetError("library database URL is not set (set the library secret; never paste it)")
    lowered = url.lower()
    if any(m in lowered for m in FORBIDDEN_MARKERS):
        raise LibraryTargetError("refused: the URL resolves to a production or data-capture database")
    if LIBRARY_MARKER not in lowered:
        raise LibraryTargetError("refused: the URL does not name the library database")
    host = url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return host.split(".", 1)[0]  # the database name, without the secret


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
