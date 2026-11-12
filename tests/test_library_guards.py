"""Guards for the psx-library destination: the migration can only create state tables there, the target
guard refuses every other host, and only engines/library_db.py reads the library credentials in code."""

from __future__ import annotations

from pathlib import Path

import pytest

from engines import library_db
from scripts import apply_library_migration as mig

ROOT = Path(__file__).resolve().parents[1]


def test_the_approved_migration_creates_exactly_the_three_state_tables_and_nothing_else():
    todo = mig.statements(mig.MIGRATION.read_text(encoding="utf-8"))
    assert len(todo) == 3 and all(s.startswith("CREATE TABLE IF NOT EXISTS") for s in todo)
    assert [s.split()[5] for s in todo] == ["fetch_control", "fetch_progress", "fetch_log"]


def test_any_statement_other_than_creating_a_state_table_is_refused():
    for bad in ("DROP TABLE fetch_log", "DELETE FROM fetch_control", "ALTER TABLE fetch_log ADD x TEXT",
                "CREATE TABLE evil (a TEXT)"):
        with pytest.raises(ValueError, match="may only create state tables"):
            mig.statements(bad + ";")


def test_the_migration_is_refused_for_any_host_that_is_not_psx_library(monkeypatch):
    monkeypatch.setenv(library_db.URL_VAR, "libsql://prod-archive-turso.example.test")
    monkeypatch.setenv(library_db.TOKEN_VAR, "not-used")
    sql = "CREATE TABLE IF NOT EXISTS fetch_control (key TEXT);"
    assert mig.apply(None, sql) == 2  # refused, nothing run


@pytest.mark.parametrize("host", ["data-capture-turso.example.test", "psx-library-archival.example.test",
                                  "psx-library-prod.example.test"])
def test_the_target_guard_refuses_forbidden_markers_even_with_the_library_name(host):
    with pytest.raises(library_db.LibraryConfigError):
        library_db.resolve_host(f"libsql://{host}")


def test_the_target_guard_accepts_the_psx_library_host():
    assert library_db.resolve_host("libsql://psx-library-turso202601.aws-us-east-1.turso.io") == \
        "psx-library-turso202601.aws-us-east-1.turso.io"


def test_only_engines_library_db_reads_the_library_credentials_in_code():
    code_dirs = ["engines", "collectors", "services", "database", "scripts", "app.py"]
    offenders = []
    for name in code_dirs:
        base = ROOT / name
        files = [base] if base.is_file() else [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
        for path in files:
            if path.name == "library_db.py" and path.parent.name == "engines":
                continue
            if "PSXNI_LIBRARY_TURSO" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
