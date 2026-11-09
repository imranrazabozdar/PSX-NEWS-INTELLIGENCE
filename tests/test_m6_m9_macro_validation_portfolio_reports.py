"""M6 macro vintages, M7 validation infrastructure, M8 portfolio isolation, M9 reproducible reports.

SYNTHETIC fixtures only: these test logic, not real-world accuracy.
"""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from engines import backtest as bt
from engines import financials as fin
from engines import macro, reports
from engines import portfolio as pf
from engines import valuation as va
from tests.test_m1_universe_and_x_watchlist import _bars, _days
from tests.test_m2_m3_financials import _corp, _imp
from tests.test_m2_m3_financials import db as db  # noqa: F401 - fixture

AS_OF = "2026-10-30"


def _imp_macro(db, rows, title="SBP MPS"):
    return macro.import_observations(db, "sbp_policy_rate", rows, importer="owner", release_url=None,
                                     release_title=title, rights_attestation="read from the official release")


# ---------------------------------------------------------------- M6
def test_registry_has_no_values(db):
    assert macro.load_registry(db) == 8
    assert macro.load_registry(db) == 0
    assert not db.execute("SELECT 1 FROM macro_observations")


def test_vintages_and_point_in_time(db):
    macro.load_registry(db)
    _imp_macro(db, [{"reference_period": "2026-06-10", "value": 11.0, "release_date": "2026-06-10"}])
    r = _imp_macro(db, [{"reference_period": "2026-06-10", "value": 11.0, "release_date": "2026-06-10"},
                        {"reference_period": "2026-09-15", "value": 10.0, "release_date": "2026-09-15"},
                        {"reference_period": "bad", "value": 1, "release_date": "2026-09-15"}], title="MPS 2")
    assert r["unchanged"] == ["2026-06-10"] and len(r["rejected"]) == 1
    assert macro.as_known_at(db, "sbp_policy_rate", "2026-08-01")["value"] == 11.0
    assert macro.as_known_at(db, "sbp_policy_rate", "2026-10-01")["value"] == 10.0
    _imp_macro(db, [{"reference_period": "2026-09-15", "value": 10.5, "release_date": "2026-10-05"}],
               title="rev")
    assert macro.as_known_at(db, "sbp_policy_rate", "2026-10-01")["value"] == 10.0  # revision not yet known
    assert macro.as_known_at(db, "sbp_policy_rate", "2026-10-06")["vintage"] == 2
    with pytest.raises(DatabaseError):
        db.execute("UPDATE macro_observations SET value = 0")


def test_driver_changes(db):
    macro.load_registry(db)
    _imp_macro(db, [{"reference_period": "2026-06-10", "value": 11.0, "release_date": "2026-06-10"},
                    {"reference_period": "2026-09-15", "value": 10.0, "release_date": "2026-09-15"}])
    ch = {c["series_code"]: c for c in macro.driver_changes(db, "T3", start="2026-07-01", end="2026-10-01")}
    assert ch["sbp_policy_rate"]["change"] == -1.0 and ch["sbp_policy_rate"]["state"] == "ok"
    assert ch["kibor_6m"]["state"] == "data_unavailable" and ch["kibor_6m"]["change"] is None


# ---------------------------------------------------------------- M7
def test_validation_run_rules(db):
    rid = bt.record_validation_run(db, kind="labelled_accuracy", data_kind="human_labelled",
                                   result={"n": 5, "metrics": [{"metric": "x", "value": 1.0}]},
                                   engine_versions={"event_intel": "1"})
    row = db.execute("SELECT status, metrics_json FROM validation_runs WHERE run_id = ?", (rid,))[0]
    assert row["status"] == "insufficient_labelled_data" and '"metrics": []' in row["metrics_json"]
    with pytest.raises(ValueError):
        bt.record_validation_run(db, kind="labelled_accuracy", data_kind="synthetic_test",
                                 result={"n": 100}, engine_versions={})


def test_walk_forward_and_lookahead():
    d = [f"2026-01-{i:02d}" for i in range(1, 11)]
    w = bt.walk_forward(d, train=4, test=2)
    assert len(w) == 3 and all(max(x["train"]) < min(x["test"]) for x in w)
    rows = [{"t": "2026-01-01"}, {"t": "2026-01-05"}]
    assert bt.point_in_time(rows, "2026-01-03", key="t") == [{"t": "2026-01-01"}]
    with pytest.raises(AssertionError):
        bt.assert_no_lookahead(rows, "2026-01-03", key="t")


def test_event_study_needs_benchmark(db):
    days = sorted(_days(10))
    _bars(db, "OGDC", days, 200_000, close=100)
    assert bt.event_study(db, "OGDC", days[5], benchmark=None)["state"] == "not_evaluable"
    for d, c in zip(days, (100, 100, 100, 100, 100, 110, 110, 110, 110, 110), strict=True):
        _bars(db, "BENCH", [d], 1, close=c)
    es = bt.event_study(db, "OGDC", days[5], benchmark="BENCH", pre=1, post=3)
    assert es["state"] == "ok" and es["abnormal_return"] == pytest.approx(-0.1)
    assert bt.evaluate_predictions(db, benchmark=None)["state"] == "not_evaluable"


def test_label_template_is_empty(db):
    t = bt.export_label_template(db, limit=3)
    assert all(i["expected"] == {} and i["labeller"] == "" for i in t["items"])


# ---------------------------------------------------------------- M8
@pytest.fixture
def pdb():
    d = SQLiteDatabase()
    pf.migrate_portfolio(d)
    yield d
    d.close()


def test_portfolio_is_owner_scoped_and_append_only(pdb, db):
    a = pf.create_portfolio(pdb, "owner-a", "main")
    b = pf.create_portfolio(pdb, "owner-b", "main")
    pf.add_transaction(pdb, "owner-a", a, ticker="OGDC", trade_date="2026-10-01", side="buy", quantity=100,
                       price=50, fees=10)
    with pytest.raises(pf.PortfolioError):
        pf.holdings(pdb, "owner-b", a)
    with pytest.raises(pf.PortfolioError):
        pf.add_transaction(pdb, "owner-b", a, ticker="OGDC", trade_date="2026-10-01", side="buy", quantity=1,
                           price=1)
    assert pf.holdings(pdb, "owner-b", b) == {}
    with pytest.raises(pf.PortfolioError):
        pf.add_transaction(pdb, "owner-a", a, ticker="OGDC", trade_date="2026-10-02", side="sell",
                           quantity=101, price=60)
    with pytest.raises(DatabaseError):
        pdb.execute("UPDATE transactions SET quantity = 0")


def test_holdings_average_cost_and_marking(pdb, db):
    a = pf.create_portfolio(pdb, "owner-a", "main")
    for side, q, p in (("buy", 100, 50), ("buy", 100, 70), ("bonus_in", 50, None), ("sell", 50, 80)):
        pf.add_transaction(pdb, "owner-a", a, ticker="OGDC", trade_date="2026-10-01", side=side, quantity=q,
                           price=p)
    h = pf.holdings(pdb, "owner-a", a)["OGDC"]
    assert h["quantity"] == 200 and h["avg_cost"] == pytest.approx(48.0)  # 12,000 / 250 shares, then sell 50
    assert h["realised"] == pytest.approx(50 * (80 - 48))
    _bars(db, "OGDC", sorted(_days(2)), 200_000, close=60)
    v = pf.valuation(pdb, db, "owner-a", a, as_of=AS_OF)
    assert v["market_value_priced"] == 12_000 and v["unpriced"] == []


def test_thesis_needs_owner_thresholds_and_reports_missing_data(pdb, db):
    with pytest.raises(pf.PortfolioError):
        pf.add_thesis(pdb, "owner-a", ticker="OGDC", title="t", statement="s",
                      conditions=[{"kind": "ratio", "subject": "current_ratio"}])
    pf.add_thesis(pdb, "owner-a", ticker="OGDC", title="liquid balance sheet", statement="s",
                  conditions=[{"kind": "ratio", "subject": "current_ratio", "operator": ">=",
                               "threshold": "1.5", "description": "current ratio at least 1.5"}])
    t = pf.check_theses(pdb, db, "owner-a", as_of=AS_OF)[0]
    assert t["state"] == "needs_review" and t["conditions"][0]["state"] == "not_evaluable"
    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # unknown filing date: not used
    t = pf.check_theses(pdb, db, "owner-a", as_of=AS_OF)[0]
    assert t["conditions"][0]["state"] == "not_evaluable"
    db.execute("UPDATE financial_reports SET filed_at_utc = '2025-09-30T00:00:00Z'")  # now filed and known
    t = pf.check_theses(pdb, db, "owner-a", as_of=AS_OF)[0]
    assert t["state"] == "holds" and t["conditions"][0]["value"] == pytest.approx(2.0)
    assert pf.check_theses(pdb, db, "owner-b", as_of=AS_OF) == []


def test_alerts_dedupe(pdb, db):
    _bars(db, "OGDC", sorted(_days(20)), 200_000)
    pf.add_alert_rule(pdb, "owner-a", kind="liquidity_change", ticker="OGDC")
    assert len(pf.run_alerts(pdb, db, "owner-a", as_of=AS_OF)) == 1
    assert pf.run_alerts(pdb, db, "owner-a", as_of=AS_OF) == []


def test_portfolio_refuses_research_database(monkeypatch):
    from database.connection import DatabaseConfigError
    monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", "sqlite:///tmp/research.db")
    with pytest.raises(DatabaseConfigError):
        pf.connect_portfolio("sqlite:///tmp/research.db")


# ---------------------------------------------------------------- M9
def test_company_report_sections_and_reproducibility(db):
    fin.promote(db, _imp(db, _corp())["report_id"])
    _bars(db, "OGDC", sorted(_days(25)), 200_000, close=70)
    va.value(db, "cmp-ogdc", as_of=AS_OF)
    body = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)
    assert all(s in body for s in reports.SECTIONS)
    assert body["fundamental_performance"]["state"] == "ok"
    assert body["valuation"]["consensus"] == "not available (U6)"
    assert "no buy/sell" in body["disclaimer"]
    s = reports.snapshot(db, "cmp-ogdc", as_of=AS_OF)
    assert reports.verify_snapshot(db, "cmp-ogdc", as_of=AS_OF)["state"] == "reproduced"
    assert reports.snapshot(db, "cmp-ogdc", as_of=AS_OF)["sha256"] == s["sha256"]
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64))["report_id"])
    assert reports.verify_snapshot(db, "cmp-ogdc", as_of=AS_OF)["state"] == "inputs_changed"
    assert "## Valuation" in reports.report_markdown(body)


def test_report_without_data_says_so(db):
    body = reports.company_report(db, "cmp-hbl", as_of=AS_OF)
    assert body["fundamental_performance"] == {"state": "data_unavailable"}
    assert body["valuation"]["state"] == "not_processed"
    assert any("financial statements" in m for m in body["confidence_and_missing_data"]["missing"])


def test_sector_and_market_views(db):
    assert reports.sector_view(db, "COMMERCIAL BANKS", as_of=AS_OF)["companies"]
    mv = reports.market_view(db, as_of=AS_OF)
    assert mv["benchmark"].startswith("not_evaluable") and mv["priority_count"] == 0
