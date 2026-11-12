"""Dry run of the autonomous tick through its real entrypoint, with a mocked Investify transport.

No network: the socket layer is replaced with one that raises, and the Investify transport is a recorder.
Asserts the guard order end to end and that exactly the allowed requests (and no others) are made.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collectors import investify_job as job
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import autonomous_tick as at
from engines import library_db

ROOT = Path(__file__).resolve().parents[1]
CONTACT = {"PSXNI_CONTACT_EMAIL": "ops@example.test"}
IN_WINDOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # Monday 10:00 PKT


class Recorder:
    def __init__(self, robots: bytes = b"User-agent: *\nDisallow: /admin\n"):
        self.calls: list[str] = []
        self.robots = robots

    def __call__(self, url, headers):
        self.calls.append(url)
        return (200, {}, self.robots) if url.endswith("/robots.txt") else (304, {}, b"")


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a real network connection was attempted in the dry run")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _library_db():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    sql = (ROOT / "database" / "library" / "0001_fetch_state.sql").read_text(encoding="utf-8")
    for stmt in sql.split(";"):
        body = "\n".join(line.split("--", 1)[0] for line in stmt.splitlines()).strip()
        if body:
            db.execute(body)
    return db


class _Conn:
    host = "psx-library-dryrun.example.test"

    def __init__(self, db):
        self.db = db


def test_in_window_tick_makes_exactly_the_robots_request_and_nothing_else(monkeypatch, no_network):
    db = _library_db()
    monkeypatch.setattr(library_db, "get_library_connection", lambda env: _Conn(db))
    monkeypatch.setattr(library_db, "auth_check", lambda conn: [{"ok": 1}])
    rec = Recorder()
    monkeypatch.setattr(job, "default_transport", rec)
    monkeypatch.setattr(at, "datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: IN_WINDOW), "fromisoformat": datetime.fromisoformat}))
    assert at.main(CONTACT) == 0
    # robots first: the only request in the dry run
    assert rec.calls == ["https://www.investify.pk/robots.txt"]


def test_outside_the_window_the_tick_makes_no_request(monkeypatch, no_network):
    db = _library_db()
    monkeypatch.setattr(library_db, "get_library_connection", lambda env: _Conn(db))
    monkeypatch.setattr(library_db, "auth_check", lambda conn: [{"ok": 1}])
    rec = Recorder()
    monkeypatch.setattr(job, "default_transport", rec)
    late = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)  # Monday 17:00 PKT, after the close
    monkeypatch.setattr(at, "datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: late), "fromisoformat": datetime.fromisoformat}))
    assert at.main(CONTACT) == 0
    assert rec.calls == []


def test_an_unreachable_library_stops_before_any_investify_request(monkeypatch, no_network):
    monkeypatch.setattr(library_db, "get_library_connection", lambda env: _Conn(None))

    def unreachable(conn):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(library_db, "auth_check", unreachable)
    rec = Recorder()
    monkeypatch.setattr(job, "default_transport", rec)
    assert at.main(CONTACT) == 1
    assert rec.calls == []


def test_no_contact_address_means_no_request(monkeypatch, no_network):
    db = _library_db()
    monkeypatch.setattr(library_db, "get_library_connection", lambda env: _Conn(db))
    monkeypatch.setattr(library_db, "auth_check", lambda conn: [{"ok": 1}])
    rec = Recorder()
    monkeypatch.setattr(job, "default_transport", rec)
    assert at.main({}) == 0
    assert rec.calls == []


def test_the_kill_switch_default_is_off_and_stops_everything_when_set():
    assert at.Control().kill_switch is False
    assert at.decide(IN_WINDOW, at.Control(kill_switch=True), calendar=None, resources=[], done=set(),
                     first_live_day=None, env={}).reason == "kill switch is on"
