"""The contact address: one built-in default, an optional override, and strict validation. No network."""

from __future__ import annotations

import re

import pytest

from collectors import investify_job as job
from engines import autonomous_tick as at
from engines import library_db


class _Conn:
    host = "psx-library-contact-test.example.test"

    def __init__(self):
        from database.connection import SQLiteDatabase
        from scripts import apply_library_migration as mig

        self.db = SQLiteDatabase()
        for stmt in mig.statements(mig.MIGRATION.read_text(encoding="utf-8")):
            self.db.execute(stmt)  # the approved state tables, through the same guarded statement check


def test_the_one_default_is_the_repo_url():
    assert at.DEFAULT_CONTACT == "https://github.com/imranrazabozdar/psx-news-intelligence"


@pytest.mark.parametrize("env", [{}, {"PSXNI_CONTACT_EMAIL": ""}])
def test_unset_or_empty_uses_the_repo_default(env):
    assert at.resolve_contact(env) == at.DEFAULT_CONTACT
    assert at.user_agent(at.resolve_contact(env)) == (
        "PSX-NI/1.0 (private, consented; contact: https://github.com/imranrazabozdar/psx-news-intelligence)")


def test_a_valid_email_overrides_the_default():
    assert at.resolve_contact({"PSXNI_CONTACT_EMAIL": "ops@example.test"}) == "ops@example.test"


@pytest.mark.parametrize("bad", ["http://insecure.example.test/x", "   ", "ops@example.test extra",
                                 " ops@example.test", "not-an-address", "https://user:pw@x.example.test",
                                 "https://localhost"])
def test_refused_values_resolve_to_none(bad):
    assert at.resolve_contact({"PSXNI_CONTACT_EMAIL": bad}) is None


def test_the_default_always_passes_validation():
    assert at.validate_contact(at.DEFAULT_CONTACT) == at.DEFAULT_CONTACT


def test_a_refused_value_is_a_clean_no_op_not_a_breaker_trip(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(library_db, "get_library_connection", lambda env: library_db.LibraryConnection(
        host=conn.host, db=conn.db))
    monkeypatch.setattr(library_db, "auth_check", lambda conn: [{"ok": 1}])
    calls = []
    monkeypatch.setattr(job, "default_transport", lambda url, headers: calls.append(url) or (200, {}, b""))
    assert at.main({"PSXNI_CONTACT_EMAIL": "http://insecure.example.test"}) == 0
    out = capsys.readouterr().out
    assert calls == [] and "refused" in out and "tables" not in out


def test_the_personal_address_is_not_in_the_repository():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = []
    for path in root.rglob("*"):
        if path.name == Path(__file__).name:
            continue  # this file names the pattern it searches for
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts \
                and path.suffix in {".py", ".md", ".json", ".yml", ".yaml", ".txt", ".sql", ""}:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if re.search(r"gmail\.com", text) or "imranrazabozdar@" in text:
                hits.append(str(path.relative_to(root)))
    assert hits == []
