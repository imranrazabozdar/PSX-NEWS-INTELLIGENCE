"""Schema and idempotent upsert for psx_announcements, run on an in-memory SQLite database."""

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.psx_announcements import count_announcements, upsert_announcement


def _db():
    db = SQLiteDatabase(":memory:")
    migrate(db)
    return db


def _row(**overrides):
    base = {
        "symbol": "OGDC",
        "company_name": "Oil & Gas Development Company Limited",
        "date": "2026-11-11",
        "time": "14:22:10",
        "category": "Financial Results",
        "title": "Financial Results for the Quarter Ended September 30, 2026",
        "doc_id": None,
        "track": "flash",
        "source": "unresolved",
        "target_url": None,
    }
    base.update(overrides)
    return base


def test_reinsert_is_idempotent():
    db = _db()
    upsert_announcement(db, _row())
    upsert_announcement(db, _row())
    assert count_announcements(db) == 1


def test_null_time_still_deduplicates():
    db = _db()
    upsert_announcement(db, _row(time=None))
    upsert_announcement(db, _row(time=None))
    assert count_announcements(db) == 1


def test_later_run_fills_unknown_fields_without_overwriting():
    db = _db()
    upsert_announcement(db, _row(doc_id=None, target_url=None))
    upsert_announcement(db, _row(doc_id=555, target_url="https://example.org/a.pdf", source="open_mirror"))
    row = db.execute("SELECT doc_id, target_url, source FROM psx_announcements")[0]
    assert row["doc_id"] == 555
    assert row["target_url"] == "https://example.org/a.pdf"
    assert row["source"] == "unresolved"  # first-seen routing decision is kept


def test_missing_required_field_is_refused():
    db = _db()
    try:
        upsert_announcement(db, _row(title=""))
    except ValueError as exc:
        assert "title" in str(exc)
    else:
        raise AssertionError("empty title must be refused")
    assert count_announcements(db) == 0


def test_bad_date_is_refused_by_schema():
    db = _db()
    with pytest.raises(Exception, match="CHECK"):  # sqlite CHECK constraint failure
        upsert_announcement(db, _row(date="11Nov2026"))
    assert count_announcements(db) == 0
