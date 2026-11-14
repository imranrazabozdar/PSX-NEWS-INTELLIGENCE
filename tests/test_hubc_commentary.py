"""HUBC YouTube commentary: every row sourced, dated and marked analyst_view; scoped loading. No network."""

from __future__ import annotations

import json
from pathlib import Path

from database.connection import SQLiteDatabase
from scripts import apply_library_migration as mig
from scripts import load_research_facts as lrf

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "docs" / "research" / "hubc" / "commentary_youtube.json"
SCHEMA = ROOT / "database" / "library" / "0002_research_fact.sql"


def _db() -> SQLiteDatabase:
    db = SQLiteDatabase()
    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    return db


def test_every_commentary_row_is_sourced_dated_and_an_analyst_view():
    rows = lrf.load_rows(FACTS, "HUBC")
    assert len(rows) >= 80
    for r in rows:
        assert r["confidence"] == "analyst_view"  # commentary is never stored as fact
        assert r["source_name"] and r["source_date"] == "2026-11-14"
        assert r["topic"].startswith("commentary.")
        assert len(r["fact_text"]) <= 300


def test_the_three_identified_videos_carry_their_url_and_the_rest_are_flagged_unidentified():
    rows = lrf.load_rows(FACTS, "HUBC")
    with_url = {r["source_name"] for r in rows if r["source_url"]}
    assert len(with_url) == 3 and all("youtube.com/watch" in r["source_url"] for r in rows if r["source_url"])
    unidentified = [r for r in rows if not r["source_url"]]
    assert unidentified and all("video not identified" in r["source_name"] for r in unidentified)


def test_the_secmc_stake_conflict_is_recorded_on_both_sides():
    texts = [r["fact_text"] for r in lrf.load_rows(FACTS, "HUBC") if r["topic"] == "commentary.mining"]
    assert any("CONTRADICTED by the CFO" in t for t in texts)
    assert any("HUBC holds 8% of SECMC" in t for t in texts)


def test_a_scoped_load_leaves_other_knowledge_alone_and_still_refuses_a_repeat():
    db = _db()
    db.execute("INSERT INTO research_fact (company, topic, fact_text, source_name, source_date, confidence, "
               "created_at) VALUES ('HUBC', 'dividend', 'existing row', 's', '2026-11-12', 'fact', "
               "'2026-11-12')")
    assert lrf.load("HUBC", FACTS, db=db, scope="commentary") == 0
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact WHERE topic = 'dividend'")[0]["n"] == 1
    assert lrf.load("HUBC", FACTS, db=db, scope="commentary") == 6  # refused the second time
    assert lrf.load("HUBC", FACTS, db=db) == 6  # unscoped still refuses because rows exist


def test_a_scoped_load_refuses_a_file_with_rows_outside_the_scope(tmp_path):
    rows = json.loads(FACTS.read_text(encoding="utf-8"))
    rows[0]["topic"] = "dividend"
    bad = tmp_path / "mixed.json"
    bad.write_text(json.dumps(rows), encoding="utf-8")
    assert lrf.load("HUBC", bad, db=_db(), scope="commentary") == 7
