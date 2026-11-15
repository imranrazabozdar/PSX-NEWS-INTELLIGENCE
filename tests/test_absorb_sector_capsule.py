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


# ---------- updating a company later must not restate what it already knows

def _row(**kw):
    return dict(ROW, **kw)


ENERGY_A = "Energy is roughly seventy percent of a cement maker's production cost."
ENERGY_B = "Roughly seventy percent of cement production cost is energy."
ENERGY_SHORT = "Energy is roughly seventy percent of production cost."
LIMESTONE = "Limestone from owned mining leases keeps raw material near five percent."
DEBT_A = "Heavy expansion debt leaves the balance sheet exposed to interest rate moves."
DEBT_B = "Expansion debt that is heavy leaves the balance sheet exposed to interest rate moves."


def test_a_reworded_repeat_of_a_stored_fact_is_skipped_as_a_near_duplicate(tmp_path, capsys):
    db = _db()
    first = _write(tmp_path, [_row(company="LUCK", topic="cost.energy_share",
                                   fact_text=ENERGY_A)])
    cap.absorb(first, apply=True, db=db)
    later = tmp_path / "later.json"
    later.write_text(json.dumps([_row(company="LUCK", topic="cost.energy_share",
                                      fact_text=ENERGY_B)]))
    cap.absorb(later, apply=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 1
    assert "near-duplicates skipped: 1" in capsys.readouterr().out


def test_a_genuinely_new_fact_about_the_same_company_is_added(tmp_path):
    db = _db()
    cap.absorb(_write(tmp_path, [_row(company="LUCK", topic="cost.energy_share",
                                      fact_text=ENERGY_SHORT)]),
               apply=True, db=db)
    new = tmp_path / "new.json"
    new.write_text(json.dumps([_row(company="LUCK", topic="cost.energy_share",
                                    fact_text=LIMESTONE)]))
    cap.absorb(new, apply=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 2


def test_the_same_sentence_about_a_different_company_is_not_a_duplicate(tmp_path):
    db = _db()
    text = "Captive power gives the company a durable cost advantage over its rivals."
    cap.absorb(_write(tmp_path, [_row(company="LUCK", topic="commentary.thesis", fact_text=text)]),
               apply=True, db=db)
    other = tmp_path / "other.json"
    other.write_text(json.dumps([_row(company="FCCL", topic="commentary.thesis", fact_text=text)]))
    cap.absorb(other, apply=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 2


def test_two_near_identical_rows_inside_one_capsule_leave_one(tmp_path):
    db = _db()
    rows = [_row(company="MLCF", topic="commentary.risk",
                 fact_text=DEBT_A),
            _row(company="MLCF", topic="commentary.risk",
                 fact_text=DEBT_B)]
    cap.absorb(_write(tmp_path, rows), apply=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 1
