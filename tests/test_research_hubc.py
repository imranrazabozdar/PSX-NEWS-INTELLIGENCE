"""HUBC research: the folder, the research_fact schema (proposed), and the row rules. No network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engines import research_facts as rf
from scripts import apply_library_migration as mig

ROOT = Path(__file__).resolve().parents[1]
HUBC = ROOT / "docs" / "research" / "hubc"
SCHEMA = ROOT / "database" / "library" / "0002_research_fact.sql"
FILES = ["hubc_financials_3yr.json", "HUBC_research_brief.md", "HUBC_research_brief_part2_macro.md",
         "HUBC_research_brief_part3_analyst_management.md", "HUBC_research_brief_part4_consensus_credit.md"]


def test_the_hubc_folder_holds_the_five_files_and_the_disclaimer():
    for name in FILES:
        assert (HUBC / name).is_file(), name
    readme = (HUBC / "README.md").read_text(encoding="utf-8")
    assert "not investment advice" in readme and "not an input to any buy or sell decision" in readme


def test_only_the_recorded_research_folders_exist():
    """A closed list: a new research folder is a deliberate act and must be added here with its rows."""
    research = sorted(p.name for p in (ROOT / "docs" / "research").iterdir() if p.is_dir())
    assert research == ["cement", "hubc", "nrl", "pso"]


def test_the_schema_creates_only_research_fact_and_only_with_if_not_exists():
    todo = mig.statements(SCHEMA.read_text(encoding="utf-8"))
    assert len(todo) == 1 and todo[0].startswith("CREATE TABLE IF NOT EXISTS research_fact (")


def test_the_migration_refuses_anything_other_than_creating_a_state_table():
    for bad in ("DROP TABLE research_fact", "CREATE TABLE evil (a TEXT)", "DELETE FROM research_fact"):
        with pytest.raises(ValueError, match="may only create state tables"):
            mig.statements(bad + ";")


def test_a_row_without_source_name_or_source_date_is_refused():
    base = {"company": "HUBC", "topic": "dividend", "fact_text": "FY26 dividend Rs 20 per share",
            "source_name": "HUBC annual accounts", "source_date": "2026-08-27", "confidence": "fact",
            "created_at": "2026-11-12"}
    assert rf.validate_fact(base)["source_name"] == "HUBC annual accounts"
    for key in ("source_name", "source_date"):
        with pytest.raises(rf.ResearchFactError, match=key):
            rf.validate_fact({**base, key: ""})


def test_long_text_unknown_columns_and_bad_confidence_are_refused():
    base = {"company": "HUBC", "topic": "x", "fact_text": "short", "source_name": "s",
            "source_date": "2026-01-01", "confidence": "fact", "created_at": "2026-11-12"}
    with pytest.raises(rf.ResearchFactError, match="over 300"):
        rf.validate_fact({**base, "fact_text": "x" * 301})
    with pytest.raises(rf.ResearchFactError, match="unknown"):
        rf.validate_fact({**base, "paragraph": "copied text"})
    with pytest.raises(rf.ResearchFactError, match="confidence"):
        rf.validate_fact({**base, "confidence": "maybe"})


def test_the_shipped_facts_file_is_valid_sourced_and_dated_for_hubc():
    import json

    from scripts import load_research_facts as lrf

    rows = lrf.load_rows(HUBC / "facts.json", "HUBC")
    assert len(rows) >= 20
    for row in rows:
        assert row["source_name"] and row["source_date"] and row["company"] == "HUBC"
        assert len(row["fact_text"]) <= 300
    assert {r["confidence"] for r in rows} == {"fact", "analyst_view"}
    assert all(r["confidence"] == "analyst_view" for r in rows if r["topic"] in
               {"analyst_thesis", "ev_plan", "land_optionality", "receivables"})
    assert "" not in {r["source_name"] for r in rows}
    json.loads((HUBC / "facts.json").read_text(encoding="utf-8"))


def test_the_loader_refuses_a_second_load_and_a_wrong_ticker(tmp_path):
    from database.connection import SQLiteDatabase
    from scripts import load_research_facts as lrf

    db = SQLiteDatabase()
    assert lrf.load("HUBC", HUBC / "facts.json", db=db) == 0
    assert lrf.load("HUBC", HUBC / "facts.json", db=db) == 6  # refused: already loaded
    bad = tmp_path / "bad.json"
    bad.write_text('[{"company": "OGDC", "topic": "x", "fact_text": "y", "source_name": "s", '
                   '"source_date": "2026-01-01", "confidence": "fact", "created_at": "2026-11-12"}]')
    import pytest as _pt

    with _pt.raises(rf.ResearchFactError, match="refused"):
        lrf.load_rows(bad, "HUBC")


def test_the_loader_only_inserts_and_reads_research_fact():
    text = (ROOT / "scripts" / "load_research_facts.py").read_text(encoding="utf-8")
    assert re.findall(r"INSERT INTO (\w+)", text) == ["research_fact"]
    rest = text.replace("CREATE TABLE IF NOT EXISTS", "")
    assert not re.search(r"\b(DROP|DELETE|UPDATE|ALTER|CREATE)\b", rest)
    assert "FROM research_fact" in text
