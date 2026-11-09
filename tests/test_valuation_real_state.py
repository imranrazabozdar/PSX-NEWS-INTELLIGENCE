"""M5 valuation with the state a real company would show TODAY: market data present, no reconciled financial
statements. The engine must not produce a number from market data alone.
"""

from __future__ import annotations

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import valuation as va
from tests.test_m1_universe_and_x_watchlist import _bars, _days


def test_market_data_alone_produces_no_valuation_number():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    _bars(d, "OGDC", sorted(_days(25)), 200_000, close=70)  # a real-style price history, no financials
    out = va.value(d, "cmp-ogdc", as_of="2026-10-30", store=False)
    for r in out["results"]:
        assert r["base"] is None and r["conservative"] is None and r["optimistic"] is None, r["method"]
    states = {r["method"]: r["state"] for r in out["results"]}
    assert states["pe"] == "insufficient_data" and states["pb"] == "insufficient_data"
    assert states["ev_ebitda"] in ("insufficient_data", "not_applicable")
    assert states["forward_pe"] == "insufficient_data"  # consensus has no approved source (U6)
    assert states["dcf"] == "needs_assumptions" and states["ddm"] == "needs_assumptions"
    assert states["justified_pb"] in ("needs_assumptions", "not_applicable")
    assert out["inputs"]["price"] == 70  # the price is shown, honestly, as the only market input
    d.close()


def test_missing_price_and_stale_price_never_produce_a_multiple():
    """A price dated after the as-of date must not be used (no look-ahead), and no price means no multiple."""
    from database.connection import SQLiteDatabase
    from database.migrate import migrate
    from database.seed_loader import load
    from engines import valuation as va
    from tests.test_m1_universe_and_x_watchlist import _bars, _days
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    days = sorted(_days(3))
    _bars(d, "OGDC", days, 200_000, close=70)  # prices exist only up to days[-1]
    before = va.value(d, "cmp-ogdc", as_of=days[0], store=False)
    assert before["inputs"]["price"] == 70 and before["inputs"]["price_date"] == days[0]
    assert not any("look" in str(n) for n in before["inputs"].get("notes", []))
    none = va.value(d, "cmp-ogdc", as_of="2020-01-01", store=False)  # before any stored price
    assert none["inputs"]["price"] is None
    for r in none["results"]:
        assert r["base"] is None, r["method"]
    d.close()
