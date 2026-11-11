"""Role-guard completeness (audit F6). The role table sets are derived from the migration directories, so
these tests fail when a migration creates a table that is unclassified, in the wrong directory, or shared."""

from pathlib import Path

import pytest

from database import connection as conn
from database.connection import (
    ARCHIVE_TABLES,
    OPERATIONAL_TABLES,
    PORTFOLIO_TABLES,
    DatabaseConfigError,
    SQLiteDatabase,
    assert_role,
    tables_created_by,
)

DATABASE_DIR = Path(conn.__file__).resolve().parent
KNOWN_MIGRATION_DIRS = {"migrations", "archive_migrations", "portfolio_migrations"}


def _check_role(role: str, table: str) -> None:
    """Run the role check on a database holding one table, and always close the connection."""
    db = SQLiteDatabase(":memory:")
    try:
        db.execute(f"CREATE TABLE {table} (x INTEGER)")
        assert_role(db, role)
    finally:
        db.close()


def test_the_three_role_sets_are_disjoint():
    assert not (OPERATIONAL_TABLES & ARCHIVE_TABLES)
    assert not (OPERATIONAL_TABLES & PORTFOLIO_TABLES)
    assert not (ARCHIVE_TABLES & PORTFOLIO_TABLES)


def test_every_migration_directory_is_classified():
    """A new migrations directory would be unclassified; this test fails until it is given a role."""
    found = {p.name for p in DATABASE_DIR.iterdir() if p.is_dir() and p.name.endswith("migrations")}
    assert found == KNOWN_MIGRATION_DIRS, (
        f"unclassified migration directory: {sorted(found - KNOWN_MIGRATION_DIRS)}"
    )


def test_no_archive_named_table_is_created_in_the_news_or_portfolio_migrations():
    wrong = sorted(t for t in OPERATIONAL_TABLES | PORTFOLIO_TABLES if t.startswith("archive_"))
    assert wrong == [], f"archive-named table in a non-archive migration directory: {wrong}"


def test_every_archive_table_is_archive_named():
    assert all(t.startswith("archive_") for t in ARCHIVE_TABLES), sorted(
        t for t in ARCHIVE_TABLES if not t.startswith("archive_")
    )


def test_commented_create_table_is_not_counted(tmp_path):
    (tmp_path / "0001_x.sql").write_text(
        "-- CREATE TABLE ghost_table (x INTEGER);\nCREATE TABLE real_table (x INTEGER);\n", encoding="utf-8"
    )
    assert tables_created_by(tmp_path) == frozenset({"real_table"})


def test_the_derived_sets_are_not_empty_and_match_the_directories():
    assert len(OPERATIONAL_TABLES) > 50  # the news schema
    assert len(ARCHIVE_TABLES) == 13  # the archive schema, all 13 tables
    assert PORTFOLIO_TABLES
    assert tables_created_by(DATABASE_DIR / "archive_migrations") == ARCHIVE_TABLES


def test_a_clean_database_passes_both_roles():
    for role in ("main", "archive"):
        db = SQLiteDatabase(":memory:")
        try:
            assert_role(db, role)
        finally:
            db.close()


@pytest.mark.parametrize("table", sorted(ARCHIVE_TABLES))
def test_each_archive_table_in_the_news_database_is_refused(table):
    with pytest.raises(DatabaseConfigError, match="archive"):
        _check_role("main", table)


@pytest.mark.parametrize("table", sorted(OPERATIONAL_TABLES))
def test_each_operational_table_in_the_archive_database_is_refused(table):
    with pytest.raises(DatabaseConfigError, match="operational"):
        _check_role("archive", table)


@pytest.mark.parametrize("table", sorted(PORTFOLIO_TABLES))
def test_each_portfolio_table_is_refused_in_both_roles(table):
    with pytest.raises(DatabaseConfigError):
        _check_role("main", table)
    with pytest.raises(DatabaseConfigError):
        _check_role("archive", table)


def test_the_real_news_schema_is_accepted_as_main():
    from database.migrate import migrate

    db = SQLiteDatabase(":memory:")
    refused_as_archive = False
    try:
        migrate(db)
        assert_role(db, "main")  # every news table is operational, none is archive
        try:
            assert_role(db, "archive")  # and the same database is refused as the archive
        except DatabaseConfigError:
            refused_as_archive = True
    finally:
        db.close()
    assert refused_as_archive
