"""Sector capsule loader: validation, placeholder refusal, dry run by default, idempotent apply.

Offline: an in-memory SQLite database stands in for psx-library. No network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.connection import SQLiteDatabase
from scripts import absorb_sector_capsule as cap

ROW = {
    "company": "SECTOR:TEST", "topic": "test.rule", "fact_text": "A synthetic rule for the loader test.",
    "value": None, "unit": None, "period": None, "source_name": "Synthetic analyst note",
    "source_url": None, "source_date": "2026-11-01", "as_of": "2026-11-01",
    "confidence": "analyst_view", "created_at": "2026-11-14T00:00:00Z",
}


def _write(tmp_path: Path, rows: list) -> Path:
    path = tmp_path / "capsule.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _db() -> SQLiteDatabase:
    db = SQLiteDatabase()
    for stmt in cap._schema_statements():
        db.execute(stmt)
    return db


def test_a_placeholder_source_is_refused(tmp_path):
    bad = dict(ROW, source_name="Sarmaaya, youtube.com/watch?v=...")
    with pytest.raises(cap.rf.ResearchFactError, match="placeholder"):
        cap.load_capsule(_write(tmp_path, [bad]))


def test_an_unsourced_row_is_refused(tmp_path):
    with pytest.raises(cap.rf.ResearchFactError):
        cap.load_capsule(_write(tmp_path, [dict(ROW, source_name="")]))


def test_dry_run_writes_nothing(tmp_path):
    db = _db()
    assert cap.absorb(_write(tmp_path, [ROW]), apply=False, db=db) == 0
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 0


def test_apply_writes_once_and_a_rerun_is_skipped(tmp_path):
    db = _db()
    path = _write(tmp_path, [ROW, dict(ROW, topic="test.other", fact_text="A second synthetic rule.")])
    cap.absorb(path, apply=True, db=db)
    cap.absorb(path, apply=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 2


def test_the_shipped_cement_capsule_is_valid_and_has_no_placeholder_sources():
    path = Path(__file__).resolve().parents[1] / "docs" / "research" / "cement" / "sector_facts.json"
    rows = cap.load_capsule(path)
    assert len(rows) == 74
    assert not any("..." in r["source_name"] for r in rows)
