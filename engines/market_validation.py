"""Read-only validation of stored SCS market data (master plan M4; docs/MASTER_VALIDATION_STRATEGY.md).

This module never writes. It accepts any database connection, so it can run against:
* an in-memory SYNTHETIC database (tests), whose results must be read as synthetic;
* a production connection the owner has explicitly scoped for read-only inspection, whose results describe
  what SCS data is actually stored.

It separates two kinds of output:
* checks on STORED OBSERVATIONS (completeness, OHLC consistency, date boundaries, duplicate sessions,
  timeframe coverage) are facts about the stored rows;
* DERIVED calculations (returns, volatility, drawdown, liquidity, traded value) are computed from stored bars
  and labelled as such.

Nothing here adjusts, fills or repairs data. Missing sessions are reported, never treated as zero volume.
"""

from __future__ import annotations

from datetime import date

from engines import market_intel, universe
from engines.market_calendar import load_calendar

SOURCE_ID = "scs_chart"
TIMEFRAMES = ("1d", "1h", "4h", "1m")
BASIS_STORED = "stored_observation"
BASIS_DERIVED = "derived_calculation"


def _sessions(db) -> list[str]:
    return [r["d"] for r in db.execute(
        "SELECT DISTINCT session_date_pkt AS d FROM market_bars_current WHERE source_id = ? AND timeframe = "
        "'1d' "
        "ORDER BY d", (SOURCE_ID,))]


def ohlc_violations(db, symbol: str | None = None) -> list[dict]:
    """Bars whose prices are internally inconsistent. Stored rows should never violate this (the table has
    CHECK constraints), so a non-empty result is a serious finding."""
    q = ("SELECT symbol, timeframe, bar_start_utc, open, high, low, close, volume FROM market_bars_current "
         "WHERE source_id = ? AND (? IS NULL OR symbol = ?) AND "
         "(low > high OR open > high OR close > high OR open < low OR close < low OR low <= 0 OR volume < 0)")
    return [dict(r) for r in db.execute(q, (SOURCE_ID, symbol, symbol))]


def duplicate_sessions(db, symbol: str) -> list[str]:
    """Daily sessions stored more than once for one symbol (the primary key stops identical bar starts; this
    catches the same session date recorded at two different bar starts)."""
    return [r["session_date_pkt"] for r in db.execute(
        "SELECT session_date_pkt FROM market_bars_current WHERE source_id = ? AND symbol = ? AND timeframe = "
        "'1d' "
        "GROUP BY session_date_pkt HAVING COUNT(*) > 1", (SOURCE_ID, symbol))]


def date_boundaries(db, symbol: str, *, as_of: str) -> dict:
    """First and last stored sessions, and bars dated after the explicit as-of date. The as-of date is a
    parameter, not the database server's clock, so the check is reproducible."""
    if not is_iso_date(as_of):
        raise ValueError("as_of must be YYYY-MM-DD")
    r = db.execute("SELECT MIN(session_date_pkt) AS first, MAX(session_date_pkt) AS last, COUNT(*) AS n "
                   "FROM market_bars_current WHERE source_id = ? AND symbol = ? AND timeframe = '1d'",
                   (SOURCE_ID, symbol))[0]
    future = db.execute("SELECT COUNT(*) AS n FROM market_bars_current "
                        "WHERE source_id = ? AND symbol = ? AND "
                        "timeframe = '1d' AND session_date_pkt > ?", (SOURCE_ID, symbol, as_of))[0]["n"]
    return {"basis": BASIS_STORED, "first_session": r["first"], "last_session": r["last"],
            "daily_bars": r["n"],
            "bars_after_today_pkt": future}


def timeframe_coverage(db, symbol: str) -> dict:
    """Which timeframes have stored bars for the symbol, and how many. A timeframe with no bars is reported as
    absent, not as an error or as zero."""
    rows = {r["timeframe"]: r for r in db.execute(
        "SELECT timeframe, COUNT(*) AS n, MIN(session_date_pkt) AS first, MAX(session_date_pkt) AS last "
        "FROM market_bars_current WHERE source_id = ? AND symbol = ? GROUP BY "
        "timeframe", (SOURCE_ID, symbol))}
    return {tf: ({"basis": BASIS_STORED, "bars": rows[tf]["n"], "first": rows[tf]["first"],
                  "last": rows[tf]["last"]} if tf in rows else {"basis": BASIS_STORED, "bars": 0})
            for tf in TIMEFRAMES}


def session_completeness(db, symbol: str, *, as_of: str) -> dict:
    """Trading sessions the market traded (official calendar and bars for at least one symbol) that this
    symbol has
    no daily bar for. The missing list is shown in full, never filled."""
    cal = load_calendar()
    market = [d for d in _sessions(db) if d <= as_of and cal.is_trading_day(d)]
    have = {r["d"] for r in db.execute(
        "SELECT session_date_pkt AS d FROM market_bars_current WHERE source_id = ? AND symbol = ? AND "
        "timeframe = '1d' AND session_date_pkt <= ?", (SOURCE_ID, symbol, as_of))}
    missing = [d for d in market if d not in have]
    return {"basis": BASIS_STORED, "market_sessions": len(market), "symbol_sessions": len(have & set(market)),
            "missing_sessions": missing}


def symbol_report(db, symbol: str, *, as_of: str) -> dict:
    """One symbol's validation: stored-observation checks and derived calculations, kept separate."""
    liq = universe.liquidity(db, symbol, as_of=as_of, source_id=SOURCE_ID)
    m = market_intel.measures(db, symbol, as_of=as_of)
    return {
        "symbol": symbol,
        "as_of": as_of,
        "stored": {
            "date_boundaries": date_boundaries(db, symbol, as_of=as_of),
            "timeframes": timeframe_coverage(db, symbol),
            "session_completeness": session_completeness(db, symbol, as_of=as_of),
            "duplicate_sessions": duplicate_sessions(db, symbol),
            "ohlc_violations": ohlc_violations(db, symbol),
        },
        "derived": {
            "basis": BASIS_DERIVED,
            "liquidity_20_sessions": {"state": liq.state, "adv_shares": liq.adv_shares,
                                      "avg_traded_value_pkr_approx": liq.avg_traded_value_pkr_approx,
                                      "reasons": liq.reasons,
                                      "traded_value_note":
                                          "approximation: daily close x volume, not reported turnover"},
            "returns_and_risk": {k: m[k] for k in ("return_1d", "return_20s", "return_60s",
                                                   "volatility_60s_annualised", "max_drawdown",
                                                   "relative_to_benchmark", "series_state")},
        },
    }


def is_iso_date(d: str | None) -> bool:
    try:
        date.fromisoformat(d or "")
        return True
    except ValueError:
        return False
