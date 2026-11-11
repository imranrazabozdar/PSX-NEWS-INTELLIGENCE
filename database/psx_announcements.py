"""Repository layer for the PSX announcement feed (migration 0015).

Idempotent: re-inserting the same announcement updates only the fields that were previously unknown
(NULL), so a later run can add a doc_id or target URL without duplicating the row.
"""

from __future__ import annotations

from typing import Any

from database.connection import Database

UPSERT_SQL = """
INSERT INTO psx_announcements
    (symbol, company_name, date, time, category, title, doc_id, track, source, target_url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol, date, COALESCE(time, ''), title) DO UPDATE SET
    company_name = COALESCE(psx_announcements.company_name, excluded.company_name),
    category     = COALESCE(psx_announcements.category, excluded.category),
    doc_id       = COALESCE(psx_announcements.doc_id, excluded.doc_id),
    target_url   = COALESCE(psx_announcements.target_url, excluded.target_url)
"""

_COLUMNS = (
    "symbol",
    "company_name",
    "date",
    "time",
    "category",
    "title",
    "doc_id",
    "track",
    "source",
    "target_url",
)


def upsert_announcement(db: Database, row: dict[str, Any]) -> None:
    """Insert or fill in one announcement. `row` uses the column names above."""
    missing = [c for c in ("symbol", "date", "title", "track", "source") if not row.get(c)]
    if missing:
        raise ValueError(f"announcement row missing required field(s): {', '.join(missing)}")
    db.execute(UPSERT_SQL, [row.get(c) for c in _COLUMNS])


def upsert_announcements(db: Database, rows: list[dict[str, Any]]) -> int:
    for row in rows:
        upsert_announcement(db, row)
    return len(rows)


def count_announcements(db: Database) -> int:
    return int(db.execute("SELECT COUNT(*) AS n FROM psx_announcements")[0]["n"])
