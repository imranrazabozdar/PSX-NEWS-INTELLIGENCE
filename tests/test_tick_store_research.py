"""The tick stores distilled rows in research_fact (never source_items, never the Investify description).
No network: the transport is a recorder and the socket layer refuses connections."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from database.connection import SQLiteDatabase
from engines import autonomous_tick as at
from engines import investify_extract as x
from engines import research_facts as rf
from scripts import apply_library_migration as mig

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "investify" / "fundamentals_synthetic.html"
DESCRIPTION = "Earnings per share is the company profit allocated to one share."
ROBOTS = "User-agent: *\nDisallow: /admin\n"
NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # Monday 10:00 PKT, inside the window


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a real network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _db(with_research_table: bool = True) -> SQLiteDatabase:
    db = SQLiteDatabase()
    if with_research_table:
        for stmt in mig.statements((ROOT / "database" / "library" / "0002_research_fact.sql").read_text()):
            db.execute(stmt)
    return db


def _fixture_fields():
    return x.parse_fundamentals(FIXTURE.read_bytes(), "ZZTEST")


def test_rows_are_sourced_dated_and_keep_no_description_text():
    rows = rf.rows_from_fields(company="ZZTEST", endpoint="fundamentals", fields=_fixture_fields(),
                               url="https://www.investify.pk/company/ZZTEST/fundamentals",
                               fetched_at_utc="2026-11-16T05:00:00Z")
    assert len(rows) == 4
    for r in rows:
        assert r["source_name"] == rf.SOURCE_NAME and r["source_date"] == "2026-11-16"
        assert r["confidence"] == "fact" and r["company"] == "ZZTEST"
        assert r["topic"] == "fundamentals.metrics"
    assert not any(DESCRIPTION in r["fact_text"] for r in rows)
    eps = next(r for r in rows if r["fact_text"].startswith("Annual EPS"))
    assert eps["value"] == 10.5 and eps["unit"] == "PKR" and eps["period"] == "2026 FY"


def test_insert_writes_research_fact_rows_and_nothing_else():
    db = _db()
    rows = rf.rows_from_fields(company="ZZTEST", endpoint="fundamentals", fields=_fixture_fields(),
                               url="https://www.investify.pk/company/ZZTEST/fundamentals",
                               fetched_at_utc="2026-11-16T05:00:00Z")
    assert rf.insert_rows(db, rows) == 4
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 4
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "source_items" not in names


def test_a_successful_fetch_is_stored_as_rows_and_marked_done(no_network):
    db = _db()
    done: list[str] = []
    body = FIXTURE.read_bytes()
    deps = at.Dependencies(
        load_control=lambda: at.Control(robots_txt=ROBOTS, robots_fetched_utc="2026-11-16T04:00:00Z",
                                        kill_switch=False),
        save_control=lambda c: None, load_done=lambda: set(), save_done=done.append,
        fetch=lambda sym, ep: (200, {}, body),
        store=at.store_fields(db), log=lambda e, d: None)
    d = at.tick(NOW, deps, calendar=_cal(),
                resources=[("ZZTEST", "fundamentals")], first_live_day=None, env={})
    assert d.reason == "stored ZZTEST:fundamentals" and done == ["ZZTEST:fundamentals"]
    assert db.execute("SELECT COUNT(*) AS n FROM research_fact")[0]["n"] == 4


def test_a_failed_store_leaves_the_resource_pending_and_logs_it(no_network):
    db = _db(with_research_table=False)  # the table is missing: the store must fail, not silently succeed
    done: list[str] = []
    logs: list[tuple[str, str]] = []
    body = FIXTURE.read_bytes()
    deps = at.Dependencies(
        load_control=lambda: at.Control(robots_txt=ROBOTS, robots_fetched_utc="2026-11-16T04:00:00Z",
                                        kill_switch=False),
        save_control=lambda c: None, load_done=lambda: set(), save_done=done.append,
        fetch=lambda sym, ep: (200, {}, body),
        store=at.store_fields(db), log=lambda e, d: logs.append((e, d)))
    d = at.tick(NOW, deps, calendar=_cal(), resources=[("ZZTEST", "fundamentals")],
                first_live_day=None, env={})
    assert done == []  # not marked done: the next run retries it
    assert "stays pending" in d.reason
    assert any(e == "store_failed" for e, _ in logs)


def _cal():
    from engines import market_calendar as mc

    return mc.load_calendar(ROOT / "config" / "psx_calendar.json")
