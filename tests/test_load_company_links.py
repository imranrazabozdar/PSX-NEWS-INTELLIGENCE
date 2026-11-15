import json

from database.connection import SQLiteDatabase
from scripts import load_company_links as lcl

FACTS = [{"id": 1, "company": "LUCK", "topic": "cost.coal", "fact_text": "Coal prices up hurt margins"}]
GOOD = {"driver": "coal", "affected": "luck", "direction": "down", "fact_id": 1, "quote": "Coal prices up"}


def _files(tmp_path, links):
    (tmp_path / "l.json").write_text(json.dumps(links))
    (tmp_path / "f.json").write_text(json.dumps(FACTS))
    return [(tmp_path / "l.json", tmp_path / "f.json")]


def test_only_valid_links_are_kept_and_duplicates_dropped(tmp_path):
    bad = dict(GOOD, quote="made up")
    links, report = lcl.collect(_files(tmp_path, [GOOD, GOOD, bad]))
    assert len(links) == 1 and report["l.json"]["valid"] == 2


def test_apply_is_idempotent(tmp_path):
    db = SQLiteDatabase()
    links, _ = lcl.collect(_files(tmp_path, [GOOD]))
    lcl.apply(links, db)
    lcl.apply(links, db)
    rows = list(db.execute("SELECT affected, COUNT(*) AS n FROM company_link GROUP BY affected"))
    assert [(r["affected"], r["n"]) for r in rows] == [("LUCK", 1)]
