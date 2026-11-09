"""M10 read-only integrity check."""

from __future__ import annotations

from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import integrity


def test_healthy_database_is_ok_and_check_does_not_write():
    db = SQLiteDatabase()
    migrate(db)
    before = db.execute("SELECT COUNT(*) n FROM sqlite_master")[0]["n"]
    r = integrity.check(db)
    assert r["state"] == "ok" and not r["pending"]
    assert db.execute("SELECT COUNT(*) n FROM sqlite_master")[0]["n"] == before


def test_missing_trigger_and_changed_checksum_are_reported():
    db = SQLiteDatabase()
    migrate(db)
    db.execute("DROP TRIGGER trg_fin_lines_no_delete")
    db.execute("UPDATE schema_migrations SET checksum = ? WHERE version = 12", ("e" * 64,))
    r = integrity.check(db)
    assert r["state"] == "problems"
    assert any("trg_fin_lines_no_delete" in p for p in r["problems"])
    assert any("migration 12" in p for p in r["problems"])


def test_pending_migrations_are_notes_not_problems():
    import shutil
    import tempfile
    from pathlib import Path

    from database.migrate import MIGRATIONS_DIR
    tmp = Path(tempfile.mkdtemp())
    for p in sorted(MIGRATIONS_DIR.glob("*.sql"))[:10]:
        shutil.copy(p, tmp / p.name)
    db = SQLiteDatabase()
    migrate(db, directory=tmp)  # like production today: 0001-0010 only
    r = integrity.check(db)
    assert r["state"] == "ok" and r["pending"] == [11, 12, 13, 14]


def test_empty_database_is_not_written():
    db = SQLiteDatabase()
    r = integrity.check(db)
    assert r["state"] == "problems" and not db.execute("SELECT 1 FROM sqlite_master")


def test_missing_table_is_a_problem_and_extra_object_is_a_note():
    db = SQLiteDatabase()
    migrate(db)
    db.execute("DROP TABLE valuations")  # a table a migration defines
    db.execute("CREATE INDEX ix_rogue ON companies(legal_name)")  # defined by no migration
    r = integrity.check(db)
    assert r["state"] == "problems" and any("valuation" in p for p in r["problems"])
    assert any("ix_rogue" in n for n in r["notes"])


def test_pending_migration_does_not_excuse_a_missing_applied_object():
    """0001-0010 applied, 0011 pending: dropping an APPLIED trigger is reported, even though a pending file
    (0011) mentions a trigger of the same kind."""
    import shutil
    import tempfile
    from pathlib import Path

    from database.migrate import MIGRATIONS_DIR
    tmp = Path(tempfile.mkdtemp())
    for p in sorted(MIGRATIONS_DIR.glob("*.sql"))[:10]:
        shutil.copy(p, tmp / p.name)
    db = SQLiteDatabase()
    migrate(db, directory=tmp)
    applied_trigger = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' LIMIT 1")[0]["name"]
    db.execute(f"DROP TRIGGER {applied_trigger}")
    r = integrity.check(db)
    assert r["state"] == "problems" and any(applied_trigger in p for p in r["problems"])
