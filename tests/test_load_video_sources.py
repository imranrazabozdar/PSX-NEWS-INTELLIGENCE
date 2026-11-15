"""Recency index loader: validation, idempotency, and a real newest-first ranking."""

from __future__ import annotations

import json

import pytest

from database.connection import SQLiteDatabase
from scripts import load_video_sources as lvs

ROWS = [{"video_id": "a", "title": "Newest", "archive_position": 0, "sector_bucket": "cement",
         "url": "https://y/a", "speaker_may_differ": False, "status": "extracted"},
        {"video_id": "b", "title": "Older", "archive_position": 1, "sector_bucket": "banks",
         "url": "https://y/b", "speaker_may_differ": True, "status": "pending"}]


def _db():
    return SQLiteDatabase()


def test_dry_run_writes_nothing():
    db = _db()
    assert lvs.apply(ROWS, write=False, db=db) == 0
    assert not db.execute("SELECT name FROM sqlite_master WHERE name = 'video_source'")


def test_apply_loads_every_video_and_a_rerun_replaces_instead_of_duplicating():
    db = _db()
    lvs.apply(ROWS, write=True, db=db)
    lvs.apply(ROWS, write=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM video_source")[0]["n"] == 2
    newest = db.execute("SELECT video_id FROM video_source ORDER BY archive_position LIMIT 1")[0]
    assert newest["video_id"] == "a"


def test_a_duplicate_position_is_refused_because_position_is_a_rank(tmp_path):
    bad = tmp_path / "i.json"
    bad.write_text(json.dumps([ROWS[0], dict(ROWS[1], archive_position=0)]))
    with pytest.raises(ValueError, match="rank"):
        lvs.load_index(bad)


def test_the_shipped_index_is_a_complete_unique_ranking_from_zero():
    rows = lvs.load_index()
    assert len(rows) == 215
    assert sorted(r["archive_position"] for r in rows) == list(range(215))
