"""Read and write economy: windowed duplicate checks, loose sector scan, URL lookups, index allowlist."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from database.connection import SQLiteDatabase
from engines import news_collector as nc
from engines import research_facts as rf
from scripts import absorb_sector_capsule as ab
from scripts import apply_library_indexes as idx
from scripts import build_news_capsule as bnc


def facts_db() -> SQLiteDatabase:
    db = SQLiteDatabase()
    db.execute(
        "CREATE TABLE research_fact (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, topic TEXT, "
        "fact_text TEXT, value REAL, unit TEXT, period TEXT, source_name TEXT, source_url TEXT, "
        "source_date TEXT, as_of TEXT, confidence TEXT, created_at TEXT)"
    )
    for i in range(30):
        day = f"2026-10-{i + 1:02d}"
        db.execute(
            "INSERT INTO research_fact (company, topic, fact_text, source_date) VALUES (?, ?, ?, ?)",
            ("MACRO:PAKISTAN", "market.news", f"old story {i}", day),
        )
    return db


def test_facts_for_since_reads_only_the_recent_window():
    db = facts_db()
    recent = rf.facts_for(db, ["MACRO:PAKISTAN"], "fact_text", since="2026-10-25")
    assert len(recent) == 6 and len(rf.facts_for(db, ["MACRO:PAKISTAN"], "fact_text")) == 30


def test_absorb_since_days_still_skips_a_repeat_inside_the_window_and_writes_the_new_row(tmp_path):
    db = facts_db()
    row = {
        "company": "MACRO:PAKISTAN",
        "topic": "market.news",
        "fact_text": "old story 29",
        "value": None,
        "unit": None,
        "period": None,
        "source_name": "Mettis news, 2026-10-30",
        "source_url": "https://x/1",
        "source_date": "2026-10-30",
        "as_of": "2026-10-30",
        "confidence": "fact",
        "created_at": "2026-10-30T00:00:00Z",
    }
    fresh = {**row, "fact_text": "a brand new story about rates", "source_url": "https://x/2"}
    path = tmp_path / "c.json"
    path.write_text(json.dumps([row, fresh]))
    assert ab.absorb(path, apply=True, db=db, since_days=7) == 0
    texts = [
        r["fact_text"]
        for r in db.execute("SELECT fact_text FROM research_fact WHERE company = 'MACRO:PAKISTAN'")
    ]
    assert texts.count("old story 29") == 1 and "a brand new story about rates" in texts


def test_news_known_among_checks_only_the_candidates():
    db = SQLiteDatabase()
    store = nc.Store(db)
    store.ensure_tables()
    now = datetime(2026, 11, 17, tzinfo=UTC)
    store.add_item(nc.Item("mettis", "https://m/a", "A", "2026-11-17T00:00:00Z", None, None), now)
    store.set_progress("mettis", "skip:https://m/b", "unparsed", now)
    got = store.known_among("mettis", ["https://m/a", "https://m/b", "https://m/c"])
    assert got == {"https://m/a", "https://m/b"} and store.known_among("mettis", []) == set()


def test_news_item_has_a_published_index_after_ensure_tables():
    db = SQLiteDatabase()
    nc.Store(db).ensure_tables()
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "idx_news_item_published" in names


def test_index_script_allows_only_the_approved_statements():
    assert len(idx.statements((idx.DIR / idx.FILES["0011"]).read_text())) == 2
    for bad in (
        "DROP TABLE research_fact;",
        "DROP INDEX IF EXISTS idx_other;",
        "CREATE INDEX x ON research_fact (a);",
    ):
        with pytest.raises(ValueError):
            idx.statements(bad)


def test_owner_confirmed_notes_give_the_bare_company_name():
    assert (
        bnc.confirmed_name("SELECT", "Select Technologies, owner-confirmed 2026-11-16")
        == "Select Technologies"
    )
    assert (
        bnc.confirmed_name("ZUMA", "Zuma Resources Ltd, from the owner's Investify export 2026-11-17")
        == "Zuma Resources Ltd"
    )
    assert bnc.confirmed_name("BFBIO", "owner-confirmed 2026-11-16") == "BFBIO"
