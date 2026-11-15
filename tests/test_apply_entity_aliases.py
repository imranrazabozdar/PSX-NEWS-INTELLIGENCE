from database.connection import SQLiteDatabase
from scripts import apply_entity_aliases as ali


def _db():
    db = SQLiteDatabase()
    db.execute("CREATE TABLE research_fact (id INTEGER PRIMARY KEY, company TEXT)")
    db.execute("CREATE TABLE company_link (id INTEGER PRIMARY KEY, affected TEXT)")
    for name in ("Interloop", "Kohat Cement", "LUCK"):
        db.execute("INSERT INTO research_fact (company) VALUES (?)", (name,))
    for name in ("INTERLOOP", "MACRO:PAKISTAN"):
        db.execute("INSERT INTO company_link (affected) VALUES (?)", (name,))
    return db


def test_names_fold_to_tickers_and_others_are_untouched_and_it_is_idempotent():
    db = _db()
    aliases = {"Interloop": "ILP", "Kohat Cement": "KOHC"}
    for _ in range(2):
        db.batch(ali.statements(aliases))
    assert sorted(r["company"] for r in db.execute("SELECT company FROM research_fact")) == \
        ["ILP", "KOHC", "LUCK"]
    assert sorted(r["affected"] for r in db.execute("SELECT affected FROM company_link")) == \
        ["ILP", "MACRO:PAKISTAN"]


def test_the_shipped_alias_file_holds_tickers_sectors_or_name_folds():
    aliases = ali.load()
    assert len(aliases) >= 30
    for name, target in aliases.items():
        folded = target != target.upper()  # a name-to-name fold, e.g. two spellings of one unlisted company
        assert folded or target.removeprefix("SECTOR:").removeprefix("MACRO:").isalnum(), (name, target)
    assert sum(t != t.upper() for t in aliases.values()) <= 5


def test_no_name_is_both_aliased_and_marked_not_listed():
    import json

    data = json.loads(ali.ALIASES.read_text(encoding="utf-8"))
    assert not set(data["aliases"]) & set(data["not_listed"])
