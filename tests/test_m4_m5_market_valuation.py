"""M4 market intelligence and M5 valuation. SYNTHETIC hand-built fixtures with hand-calculated "
  "expectations."""

from __future__ import annotations

import pytest

from database.connection import DatabaseError
from engines import financials as fin
from engines import market_intel as mi
from engines import valuation as va
from tests.test_m1_universe_and_x_watchlist import _bars, _days
from tests.test_m2_m3_financials import _corp, _imp
from tests.test_m2_m3_financials import db as db  # noqa: F401 - fixture

AS_OF = "2026-10-30"


def _ca(db, **rec):
    return mi.import_corporate_action(db, {"ticker": "OGDC", **rec}, importer="owner", source_note="notice")


# ---------------------------------------------------------------- corporate actions / adjustment
def test_bonus_and_split_adjustment(db):
    days = sorted(_days(10))
    _bars(db, "OGDC", days, 200_000, close=100)
    _ca(db, action_type="bonus", ex_date=days[5], ratio=0.25)
    s = mi.adjusted_series(db, "OGDC", as_of=AS_OF)
    assert s["state"] == "adjusted"
    adj = {b["d"]: b["adj_close"] for b in s["bars"]}
    assert adj[days[4]] == pytest.approx(80.0) and adj[days[5]] == pytest.approx(100.0)
    raw = {b["d"]: b["close"] for b in s["bars"]}
    assert raw[days[4]] == 100  # the stored price is never changed


def test_rights_terp_and_cash_dividend_listed(db):
    days = sorted(_days(6))
    _bars(db, "OGDC", days, 200_000, close=100)
    _ca(db, action_type="rights", ex_date=days[3], ratio=0.5, subscription_price=40)
    _ca(db, action_type="cash_dividend", ex_date=days[4], amount_per_share=5)
    s = mi.adjusted_series(db, "OGDC", as_of=AS_OF)
    assert {b["d"]: b["factor"] for b in s["bars"]}[days[0]] == pytest.approx(0.8)  # TERP 80 / 100
    assert s["cash_dividends_not_in_price_series"] == [{"ex_date": days[4], "amount_per_share": 5}]


def test_rights_without_cum_price_leaves_series_unadjusted(db):
    days = sorted(_days(5))
    _bars(db, "OGDC", days, 200_000)
    _ca(db, action_type="rights", ex_date=days[0], ratio=0.5, subscription_price=40)
    s = mi.adjusted_series(db, "OGDC", as_of=AS_OF)
    assert s["state"] == "unadjusted" and s["problems"]


def test_corporate_actions_append_only_and_validated(db):
    _ca(db, action_type="cash_dividend", ex_date="2026-10-01", amount_per_share=2)
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM corporate_actions")
    with pytest.raises(DatabaseError):
        _ca(db, action_type="bonus", ex_date="2026-10-02")  # ratio required


# ---------------------------------------------------------------- measures
def test_measures_need_enough_sessions_and_no_benchmark(db):
    days = sorted(_days(25))
    _bars(db, "OGDC", days, 200_000, close=100)
    m = mi.measures(db, "OGDC", as_of=AS_OF)
    assert m["return_20s"]["state"] == "ok" and m["return_20s"]["value"] == pytest.approx(0.0)
    assert m["return_60s"]["state"] == "insufficient_data"
    assert m["volatility_60s_annualised"]["state"] == "insufficient_data"
    assert m["relative_to_benchmark"]["state"] == "not_evaluable"
    assert m["liquidity"]["state"] == "qualified"


def test_gap_breaks_the_consecutive_run(db):
    days = sorted(_days(25))
    _bars(db, "OGDC", days, 200_000)
    _bars(db, "HBL", [d for d in days if d != days[-3]], 200_000)  # HBL missed a market session
    m = mi.measures(db, "HBL", as_of=AS_OF)
    assert m["consecutive_sessions"] == 2 and m["return_20s"]["state"] == "insufficient_data"


def test_drawdown_hand_calculated(db):
    days = sorted(_days(4))
    for d, c in zip(days, (100, 120, 90, 110), strict=True):
        _bars(db, "OGDC", [d], 200_000, close=c)
    assert mi.measures(db, "OGDC", as_of=AS_OF)["max_drawdown"]["value"] == pytest.approx(-0.25)


def test_assess_writes_i_and_j(db):
    _bars(db, "OGDC", sorted(_days(21)), 200_000)
    mi.assess(db, "OGDC", as_of=AS_OF)
    rows = {r["dimension"]: r for r in db.execute("SELECT dimension, data_state, band FROM "
                                                  "dimension_assessments")}
    assert set(rows) == {"I", "J"} and rows["J"]["data_state"] == "ok" and rows["I"]["band"] is None


# ---------------------------------------------------------------- valuation
def _fundamentals(db):
    rec = _corp()
    rec["lines"].append({"statement": "CF", "raw_label": "Depreciation", "column_period_end": "2025-06-30",
                         "value": -30.0})
    rec["lines"].append({"statement": "BS", "raw_label": "Cash and bank balances",
                         "column_period_end": "2025-06-30", "value": 40.0})
    fin.load_mappings(db)
    fin.promote(db, _imp(db, rec)["report_id"])


def test_multiples_hand_calculated(db):
    _fundamentals(db)
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)
    _ca(db, action_type="cash_dividend", ex_date="2026-09-01", amount_per_share=3.5)
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF)["results"]}
    # shares derived = 140,000 / 14 = 10,000; BVPS = 200,000 / 10,000 = 20
    assert r["pe"]["base"] == pytest.approx(5.0) and r["pb"]["base"] == pytest.approx(3.5)
    # EV = 70 x 10,000 + (80,000 + 20,000) - 40,000 = 760,000; EBITDA = 250,000 + 30,000
    assert r["ev_ebitda"]["base"] == pytest.approx(760_000 / 280_000)
    assert r["dividend_yield"]["base"] == pytest.approx(0.05)
    assert r["forward_pe"]["state"] == "insufficient_data" and "U6" in r["forward_pe"]["missing"][0]
    assert r["dcf"]["state"] == "needs_assumptions" and r["justified_pb"]["state"] == "not_applicable"
    stored = db.execute("SELECT method, state, base FROM valuations")
    assert len(stored) == 8 and all(s["base"] is None for s in stored if s["state"] != "ok")


def test_models_need_owner_assumptions_and_give_ranges(db):
    _fundamentals(db)
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)
    _ca(db, action_type="cash_dividend", ex_date="2026-09-01", amount_per_share=3.5)
    a = {"ddm": {"cost_of_equity": (0.14, 0.16, 0.18), "dividend_growth": (0.02, 0.04, 0.06)}}
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF, assumptions=a, store=False)["results"]}
    d = r["ddm"]
    assert d["state"] == "ok" and d["base"] == pytest.approx(3.5 * 1.04 / 0.12)
    assert d["conservative"] < d["base"] < d["optimistic"] and d["sensitivity"]
    bad = {"ddm": {"cost_of_equity": (0.03, 0.03, 0.03), "dividend_growth": (0.04, 0.04, 0.04)}}
    out = va.value(db, "cmp-ogdc", as_of=AS_OF, assumptions=bad, store=False)
    r = {x["method"]: x for x in out["results"]}
    assert r["ddm"]["state"] == "not_applicable" and r["ddm"]["base"] is None


def test_no_look_ahead_on_financials(db):
    _fundamentals(db)
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of="2025-06-29", store=False)["results"]}
    assert r["pe"]["state"] == "insufficient_data"  # FY2025 period had not ended yet


def test_loss_making_pe_not_applicable(db):
    rec = _corp(overrides={("Earnings per share - basic and diluted", "2025-06-30"): -2.0})
    fin.promote(db, _imp(db, rec)["report_id"])
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)["results"]}
    assert r["pe"]["state"] == "not_applicable" and r["pe"]["base"] is None
