"""The company index: guarded migration, and that loaders/packs read only the entities they need."""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from engines import research_facts as rf
from scripts import apply_research_fact_index as idx


def table() -> SQLiteDatabase:
    db = SQLiteDatabase()
    db.execute(
        "CREATE TABLE research_fact (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, topic TEXT, "
        "fact_text TEXT, source_name TEXT, source_url TEXT, source_date TEXT, confidence TEXT)"
    )
    for company in ["HUBC", "LUCK", "SECTOR:CEMENT", "SECTOR:BANKS", "MACRO:PAKISTAN", "SECTORX"]:
        for i in range(3):
            db.execute(
                "INSERT INTO research_fact (company, topic, fact_text) VALUES (?, ?, ?)",
                (company, "news.company", f"{company} fact {i}"),
            )
    return db


def test_facts_for_returns_only_the_requested_entities():
    db = table()
    got = rf.facts_for(db, ["HUBC", "MACRO:PAKISTAN", "NOPE"], "company, fact_text")
    assert {r["company"] for r in got} == {"HUBC", "MACRO:PAKISTAN"} and len(got) == 6


def test_sector_names_are_a_range_not_a_scan_and_exclude_lookalikes():
    assert rf.sector_names(table()) == {"SECTOR:CEMENT", "SECTOR:BANKS"}


def test_the_migration_creates_the_index_and_is_repeatable():
    db = table()
    assert idx.apply(db=db) == 0 and idx.apply(db=db) == 0
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "idx_research_fact_company" in names
    plan = db.execute("EXPLAIN QUERY PLAN SELECT id FROM research_fact WHERE company IN ('HUBC')")
    assert "idx_research_fact_company" in " ".join(str(dict(r)) for r in plan)


def test_the_apply_script_refuses_anything_but_the_one_index():
    with pytest.raises(ValueError):
        idx.statements("DROP TABLE research_fact;")
    with pytest.raises(ValueError):
        idx.statements("CREATE INDEX IF NOT EXISTS other ON research_fact (company);")
