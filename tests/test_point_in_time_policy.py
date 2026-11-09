"""Point-in-time reporting policy (PR #41 batch): strict by default, lenient labelled and segregated.

SYNTHETIC fixtures only. Amounts are in PKR after the unit scale (thousands).
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import backtest as bt
from engines import financials as fin
from engines import fundamentals as fu
from engines import portfolio as pf
from engines import reports
from engines import valuation as va
from tests.test_m1_universe_and_x_watchlist import _bars, _days
from tests.test_m2_m3_financials import _corp, _imp

AS_OF = "2026-06-30"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


def _fy24(filed, sha="b" * 64, revenue=None):
    # cost of sales is 500 in the fixture, so gross profit = revenue - 500 keeps the restatement reconcilable
    ov = {} if revenue is None else {("Net sales", "2024-06-30"): revenue,
                                     ("Gross profit", "2024-06-30"): revenue - 500.0}
    return _corp(period="2024-06-30", prev="2023-06-30", sha=sha, filed_at_utc=filed, overrides=ov)


def test_1_later_filed_annual_report_is_excluded_until_filed(db):
    fin.promote(db, _imp(db, _fy24("2025-09-30T00:00:00Z"))["report_id"])
    fin.promote(db, _imp(db, _corp(filed_at_utc="2026-09-30T00:00:00Z"))["report_id"])  # FY2025, filed later
    before = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)
    assert before["state"] == "insufficient_data"  # FY2025 not known on 2026-06-30
    assert "prior_period_end" not in before  # nothing is returned for a period not yet filed
    after = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-10-01")
    assert after["state"] == "ok" and after["ratios"]["gross_margin"]["state"] == "ok"


def test_2_restatement_filed_after_as_of_is_invisible(db):
    fin.promote(db, _imp(db, _fy24("2025-09-30T00:00:00Z"))["report_id"])  # revenue 800
    fin.promote(db, _imp(db, _fy24("2026-12-01T00:00:00Z", sha="c" * 64, revenue=790.0))["report_id"])
    on_date = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of=AS_OF)
    assert on_date["ratios"]["gross_margin"]["inputs"]["revenue"]["value"] == 800_000.0
    later = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of="2027-01-31")
    assert later["ratios"]["gross_margin"]["inputs"]["revenue"]["value"] == 790_000.0
    assert db.execute("SELECT COUNT(*) n FROM financial_metrics WHERE metric = 'revenue' AND period_end = "
                      "'2024-06-30'")[0]["n"] == 2  # both kept: history is not overwritten


def test_3_unknown_filing_date_strict_excludes_lenient_labels(db):
    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # unknown filing date
    strict = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)
    assert strict["state"] == "insufficient_data"
    lenient = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF, strict=False)
    assert lenient["state"] == "ok_with_unknown_filing_dates"
    assert lenient["filing_dates_unknown"]  # segregated and visible


def test_4_strict_versus_lenient_in_integrated_report(db):
    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # one unknown-date report only
    s = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)
    assert s["point_in_time"]["mode"] == "strict"
    assert s["point_in_time"]["excluded_unknown_filing_date_reports"] == 1
    assert s["point_in_time"]["unknown_filing_date_used"] is False
    assert s["fundamental_performance"] == {"state": "data_unavailable"}  # not silently mixed in
    lx = reports.company_report(db, "cmp-ogdc", as_of=AS_OF, mode="lenient")
    assert lx["point_in_time"]["mode"] == "lenient" and "EXPLORATORY" in lx["point_in_time"]["statement"]
    assert lx["point_in_time"]["unknown_filing_date_used"] is True
    assert lx["fundamental_performance"]["state"] == "ok"
    with pytest.raises(ValueError):
        reports.company_report(db, "cmp-ogdc", as_of=AS_OF, mode="best_effort")


def test_5_prior_period_growth_and_average_roe_respect_filing(db):
    fin.promote(db, _imp(db, _fy24("2025-09-30T00:00:00Z"))["report_id"])
    fin.promote(db, _imp(db, _corp(filed_at_utc="2026-09-30T00:00:00Z"))["report_id"])
    mid = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-10-01")
    assert mid["prior_period_end"] == "2024-06-30"
    assert mid["growth"]["revenue"]["prior"] == 800_000.0
    assert mid["ratios"]["roe_average_equity"]["state"] == "ok"
    # Prior year filed only after this as-of date: no prior, so growth and average ROE are unavailable.
    early = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2025-10-01")
    assert early["state"] == "insufficient_data"  # FY2025 not filed yet


def test_6_valuation_and_snapshot_use_strict_history(db):
    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # unknown filing date
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)
    out = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)  # default strict
    assert {x["method"]: x for x in out["results"]}["pe"]["state"] == "insufficient_data"
    assert out["inputs"]["fy_period_end"] is None
    snap = reports.snapshot(db, "cmp-ogdc", as_of=AS_OF)
    assert reports.verify_snapshot(db, "cmp-ogdc", as_of=AS_OF)["state"] == "reproduced"
    lx = reports.snapshot(db, "cmp-ogdc", as_of=AS_OF, mode="lenient")
    assert lx["sha256"] != snap["sha256"]  # lenient snapshot is distinct and verifies in its own mode
    assert reports.verify_snapshot(db, "cmp-ogdc", as_of=AS_OF, mode="lenient")["state"] == "reproduced"


def test_7_portfolio_thesis_and_event_study_are_consistent(db):
    pdb = SQLiteDatabase()
    pf.migrate_portfolio(pdb)
    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # unknown filing date: not used
    pf.add_thesis(pdb, "owner-a", ticker="OGDC", title="t", statement="s",
                  conditions=[{"kind": "ratio", "subject": "current_ratio", "operator": ">=",
                               "threshold": "1.5", "description": "current ratio"}])
    t = pf.check_theses(pdb, db, "owner-a", as_of=AS_OF)[0]
    assert t["conditions"][0]["state"] == "not_evaluable"
    days = sorted(_days(10))
    _bars(db, "OGDC", days, 200_000, close=100)
    for d, c in zip(days, (100,) * 5 + (110,) * 5, strict=True):
        _bars(db, "BENCH", [d], 1, close=c)
    es = bt.event_study(db, "OGDC", days[5], benchmark="BENCH", pre=1, post=3)
    assert es["state"] == "ok"
    assert es["start"] < days[5] <= es["end"]  # window straddles the event; only the stored sessions are used
    assert bt.event_study(db, "OGDC", days[5], benchmark=None)["state"] == "not_evaluable"
