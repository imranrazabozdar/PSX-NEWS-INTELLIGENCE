"""The single library connection: fail-closed config, the target guard, the probe round trip, the single path.

No network: the environment is a fake mapping, and the round trip runs on an in-memory copy of the
probe table.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from database import seed_loader
from database.connection import SQLiteDatabase, TursoHTTPDatabase
from database.migrate import migrate
from engines import library_db as ldb

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = "libsql://psx-library-turso202601.aws-us-east-1.turso.io"
DATA_CAPTURE = "libsql://psx-data-capture-turso202601.aws-us-east-1.turso.io"
ARCHIVAL_TEST = "libsql://psx-data-archival-test-turso202601.aws-us-east-1.turso.io"


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no socket may be opened by these tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def env(**over):
    base = {ldb.URL_VAR: LIBRARY, ldb.TOKEN_VAR: "a-token-value"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


# ---------- fail closed: each missing or empty variable raises, naming it; nothing is opened

def test_a_missing_url_raises_and_names_the_variable():
    with pytest.raises(ldb.LibraryConfigError, match=ldb.URL_VAR):
        ldb.get_library_connection(env(**{ldb.URL_VAR: None}))


def test_an_empty_url_raises_and_names_the_variable():
    with pytest.raises(ldb.LibraryConfigError, match=ldb.URL_VAR):
        ldb.get_library_connection(env(**{ldb.URL_VAR: "   "}))


def test_a_missing_token_raises_and_names_the_variable():
    with pytest.raises(ldb.LibraryConfigError, match=ldb.TOKEN_VAR):
        ldb.get_library_connection(env(**{ldb.TOKEN_VAR: None}))


def test_an_empty_token_raises_and_names_the_variable():
    with pytest.raises(ldb.LibraryConfigError, match=ldb.TOKEN_VAR):
        ldb.get_library_connection(env(**{ldb.TOKEN_VAR: ""}))


def test_there_is_no_fallback_to_any_other_database_when_the_library_variables_are_unset():
    other = {"PSXNI_TURSO_DATABASE_URL": "libsql://psx-data-capture.turso.io", "PSXNI_TURSO_AUTH_TOKEN": "x"}
    with pytest.raises(ldb.LibraryConfigError):
        ldb.get_library_connection(other)


# ---------- the target guard: accept psx-library; refuse everything else before connecting

def test_the_guard_accepts_the_psx_library_host_and_returns_a_connection():
    conn = ldb.get_library_connection(env())
    assert conn.host == "psx-library-turso202601.aws-us-east-1.turso.io"
    assert isinstance(conn.db, TursoHTTPDatabase)  # constructed; no request is made here


@pytest.mark.parametrize("url", [DATA_CAPTURE, ARCHIVAL_TEST,
                                 "libsql://psx-archive-turso202601.aws-us-east-1.turso.io",
                                 "libsql://psx-prod-turso202601.aws-us-east-1.turso.io",
                                 "libsql://psx-production-turso202601.aws-us-east-1.turso.io",
                                 "libsql://psx-library-prod.turso.io"])
def test_the_guard_refuses_data_capture_archival_and_production_before_any_connection(url):
    with pytest.raises(ldb.LibraryConfigError, match="refused"):
        ldb.get_library_connection(env(**{ldb.URL_VAR: url}))


def test_the_guard_refuses_a_host_that_does_not_name_the_library():
    with pytest.raises(ldb.LibraryConfigError, match="does not name the psx-library"):
        ldb.get_library_connection(env(**{ldb.URL_VAR: "libsql://psx-operational.turso.io"}))


def test_the_logged_host_never_includes_the_token_or_query_string():
    conn = ldb.get_library_connection(env(**{ldb.URL_VAR: LIBRARY + "?authToken=LEAKED"}))
    assert "LEAKED" not in conn.host and "?" not in conn.host


# ---------- the probe round trip: insert, read back exactly one, delete; on the approved table

def _memory_db():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    return db


def test_the_probe_round_trip_inserts_reads_one_row_and_deletes_it():
    db = _memory_db()
    r = ldb.probe_round_trip(db)
    assert r["inserted"] and r["read_back_rows"] == 1 and r["exactly_one"] and r["matched"] and r["deleted"]
    assert db.execute("SELECT COUNT(*) AS n FROM library_probe")[0]["n"] == 0


def test_the_probe_payload_must_be_under_one_kilobyte():
    with pytest.raises(ValueError, match="1 KB"):
        ldb.probe_round_trip(_memory_db(), payload="x" * 1500)


def test_each_probe_uses_a_unique_marker():
    db = _memory_db()
    assert ldb.probe_round_trip(db)["marker"] != ldb.probe_round_trip(db)["marker"]


# ---------- the decisive check refuses cleanly when the variables are absent

def test_the_decisive_check_refuses_without_opening_anything(monkeypatch, capsys):
    monkeypatch.delenv(ldb.URL_VAR, raising=False)
    monkeypatch.delenv(ldb.TOKEN_VAR, raising=False)
    assert ldb.main() == 2
    assert ldb.URL_VAR in capsys.readouterr().out


# ---------- the single path: no other module builds a client for the library

def test_only_the_single_module_constructs_a_turso_client_outside_the_database_package():
    """The operational database uses connect_main and is separate.

    This rule covers direct client construction."""
    offenders = []
    for folder in ("engines", "collectors", "scripts", "services", "app.py"):
        base = ROOT / folder
        files = [base] if base.is_file() else list(base.rglob("*.py"))
        for path in files:
            if path.name == "library_db.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TursoHTTPDatabase":
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"library connections must go through engines/library_db.py: {offenders}"
