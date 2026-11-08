"""Migration 0010: append-only PSX OHLCV bars with corrections (SQLite, synthetic rows only)."""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate

NOW = "2026-11-08T00:00:00Z"
BAR = ("synmarket", "OGDC", "1d", "2026-11-06T00:00:00Z", "2026-11-06",
       312.11, 316.24, 311.0, 312.89, 4692324.0)
INSERT = ("INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
          "open, high, low, close, volume, retrieved_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
CORRECT = ("INSERT INTO market_bar_corrections(source_id, symbol, timeframe, bar_start_utc, "
           "open, high, low, close, volume, retrieved_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)")


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    d.execute("INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, "
              "updated_at_utc) VALUES ('synmarket','SYNTHETIC market provider','data_provider',1,?,?)",
              (NOW, NOW))
    yield d
    d.close()


def test_valid_bar_and_coverage(db):
    db.execute(INSERT, (*BAR, NOW))
    cov = db.execute("SELECT * FROM market_coverage")[0]
    assert (cov["bars"], cov["first_bar_utc"], cov["sessions"]) == (1, "2026-11-06T00:00:00Z", 1)


@pytest.mark.parametrize("change", [
    {5: 320.0},                      # open above high
    {7: 0.0},                        # non-positive low
    {9: -1.0},                       # negative volume
    {3: "2026-11-06T05:00:00Z"},     # daily bar not at 00:00 UTC
    {2: "2h"},                       # unsupported timeframe
    {1: "og-dc"},                    # malformed symbol
])
def test_invalid_bars_refused(db, change):
    row = list(BAR)
    for i, v in change.items():
        row[i] = v
    with pytest.raises(DatabaseError):
        db.execute(INSERT, (*row, NOW))


def test_intraday_alignment(db):
    db.execute(INSERT, ("synmarket", "OGDC", "1m", "2026-11-06T04:31:00Z", "2026-11-06",
                        1, 1, 1, 1, 0, NOW))
    with pytest.raises(DatabaseError):
        db.execute(INSERT, ("synmarket", "OGDC", "1h", "2026-11-06T04:30:00Z", "2026-11-06",
                            1, 1, 1, 1, 0, NOW))


def test_bars_are_append_only_and_cannot_be_replaced(db):
    db.execute(INSERT, (*BAR, NOW))
    for sql in ("UPDATE market_bars SET close = 1", "DELETE FROM market_bars"):
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(sql)
    for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE"):
        with pytest.raises(DatabaseError, match="cannot be replaced"):
            db.execute(INSERT.replace("INSERT", verb, 1), (*BAR[:8], 999.0, 1.0, NOW))
    assert db.execute("SELECT close FROM market_bars")[0]["close"] == 312.89


def test_correction_is_recorded_and_current_view_uses_it(db):
    db.execute(INSERT, (*BAR, NOW))
    db.execute(CORRECT, (*BAR[:4], 312.11, 316.24, 311.0, 313.0, 4700000.0, "2026-11-08T01:00:00Z"))
    cur = db.execute("SELECT * FROM market_bars_current")[0]
    assert (cur["close"], cur["correction_count"], cur["first_retrieved_at_utc"]) == (313.0, 1, NOW)
    assert db.execute("SELECT close FROM market_bars")[0]["close"] == 312.89   # original kept
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute("UPDATE market_bar_corrections SET close = 1")


def test_correction_requires_existing_bar(db):
    with pytest.raises(DatabaseError):
        db.execute(CORRECT, (*BAR[:4], 1, 1, 1, 1, 0, NOW))
