"""Read-only SCS market validation harness: logic checks on a SYNTHETIC in-memory database.

No result here is a market observation. These tests show that the checks detect what they claim to detect.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import market_validation as mv
from tests.test_m1_universe_and_x_watchlist import _bars, _days

AS_OF = "2026-10-30"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    yield d
    d.close()


def test_completeness_lists_missing_sessions_and_never_fills_them(db):
    days = sorted(_days(10))
    _bars(db, "OGDC", days, 200_000)
    _bars(db, "HBL", [d for d in days if d != days[4]], 200_000)  # HBL misses one session
    c = mv.session_completeness(db, "HBL", as_of=AS_OF)
    assert c["missing_sessions"] == [days[4]] and c["symbol_sessions"] == 9
    assert mv.session_completeness(db, "OGDC", as_of=AS_OF)["missing_sessions"] == []


def test_duplicate_session_is_detected(db):
    """Daily bars must start at 00:00 UTC (schema CHECK), so a duplicate can only be the same session date
    stored under a second bar start date, for example after a session-date error."""
    days = sorted(_days(3))
    _bars(db, "OGDC", days, 200_000)
    # the same session date appears at a second 00:00 bar start, one day later (a session-date error)
    unused_start = "2099-01-05T00:00:00Z"  # unused by other rows, so the primary key does not collide
    db.execute("INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
               "open, high, low, close, volume, retrieved_at_utc) "
               "VALUES ('scs_chart','OGDC','1d',?,?,10,11,9,10,1,?)",
               (unused_start, days[0], "2099-01-05T12:00:00Z"))
    assert mv.duplicate_sessions(db, "OGDC") == [days[0]]


def test_ohlc_violation_is_reported_even_though_schema_should_block_it(db):
    """The table's CHECK constraints should reject this row; if a violation ever appears in stored data, the
    validator must report it. The row is inserted only with constraints disabled, to prove the check works."""
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute("INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
               "open, high, low, close, volume, retrieved_at_utc) VALUES ('scs_chart','BAD','1d',"
               "'2026-10-01T00:00:00Z','2026-10-01',10,9,8,10,1,'2026-10-01T12:00:00Z')")
    db.execute("PRAGMA ignore_check_constraints = OFF")
    assert [v["symbol"] for v in mv.ohlc_violations(db)] == ["BAD"]


def test_boundaries_use_explicit_as_of_not_server_clock(db):
    days = sorted(_days(5))
    _bars(db, "OGDC", days, 200_000)
    b = mv.date_boundaries(db, "OGDC", as_of=days[2])
    assert b["bars_after_today_pkt"] == 2  # reproducible: bars after the explicit as-of date
    assert mv.date_boundaries(db, "OGDC", as_of=AS_OF)["bars_after_today_pkt"] == 0
    with pytest.raises(ValueError):
        mv.date_boundaries(db, "OGDC", as_of="30/10/2026")


def test_timeframe_absent_is_reported_absent_not_zero_or_error(db):
    _bars(db, "OGDC", sorted(_days(2)), 200_000)
    tf = mv.timeframe_coverage(db, "OGDC")
    assert tf["1d"]["bars"] == 2 and tf["1m"] == {"basis": "stored_observation", "bars": 0}


def test_report_keeps_stored_and_derived_separate(db):
    _bars(db, "OGDC", sorted(_days(25)), 200_000, close=70)
    r = mv.symbol_report(db, "OGDC", as_of=AS_OF)
    assert set(r) == {"symbol", "as_of", "stored", "derived"}
    assert r["derived"]["basis"] == "derived_calculation" and r["stored"]["ohlc_violations"] == []
    assert r["derived"]["liquidity_20_sessions"]["state"] == "qualified"
    assert "approximation" in r["derived"]["liquidity_20_sessions"]["traded_value_note"]


def test_validator_is_read_only(db):
    _bars(db, "OGDC", sorted(_days(3)), 200_000)
    before = db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"]
    mv.symbol_report(db, "OGDC", as_of=AS_OF)
    assert db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"] == before
