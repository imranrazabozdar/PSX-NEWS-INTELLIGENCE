"""Regression tests for defects found in the PR #40 pre-merge review. SYNTHETIC fixtures only."""

from __future__ import annotations

import pytest

from database.connection import DatabaseConfigError, SQLiteDatabase
from engines import financials as fin
from engines import macro
from engines import market_intel as mi
from engines import portfolio as pf
from engines import valuation as va
from tests.test_m1_universe_and_x_watchlist import _bars, _days
from tests.test_m2_m3_financials import _corp, _imp
from tests.test_m2_m3_financials import db as db  # noqa: F401 - fixture

AS_OF = "2026-10-30"


def _line(stmt, label, col, v):
    return {"statement": stmt, "raw_label": label, "column_period_end": col, "value": v}


# ---------------------------------------------------------------- M2
def test_repeated_labels_in_one_statement_import(db):
    rec = _corp()
    rec["lines"] += [_line("BS", "Others", "2025-06-30", 3.0), _line("BS", "Others", "2025-06-30", 4.0)]
    r = _imp(db, rec)
    assert r["status"] == "reconciled"
    assert len(db.execute("SELECT 1 FROM financial_line_items WHERE raw_label = 'Others'")) == 2


def test_conflicting_values_for_one_code_block_promotion(db):
    rec = _corp()
    rec["lines"].append(_line("IS", "Revenue", "2025-06-30", 999.0))  # second revenue line, different value
    r = _imp(db, rec)
    assert r["status"] == "needs_review"
    assert any(c["check"] == "single_value_per_code" for c in r["checks"])
    assert fin.promote(db, r["report_id"])["promoted"] == 0


def test_both_scopes_from_one_document_are_promoted(db):
    fin.promote(db, _imp(db, _corp())["report_id"])
    fin.promote(db, _imp(db, _corp(scope="consolidated"))["report_id"])  # same document SHA-256
    scopes = {r["scope"] for r in db.execute("SELECT DISTINCT scope FROM financial_metrics")}
    assert scopes == {"consolidated", "unconsolidated"}


def test_promote_recomputes_reconciliation(db):
    r = _imp(db, _corp(overrides={("Total assets", "2025-06-30"): 999.0}))
    db.execute("UPDATE financial_reports SET extraction_status = 'reconciled' WHERE report_id = ?",
               (r["report_id"],))  # a stale or tampered status must not allow promotion
    assert fin.promote(db, r["report_id"])["promoted"] == 0


def test_repromotion_is_explicit_noop(db):
    rid = _imp(db, _corp())["report_id"]
    first = fin.promote(db, rid)
    again = fin.promote(db, rid)
    assert again["promoted"] == 0 and again["already_promoted"] == first["promoted"]
    assert db.execute("SELECT calculation_method FROM financial_metrics LIMIT 1")[0][
        "calculation_method"] == "line_item:manual;reconciled"


def test_share_counts_are_not_scaled(db):
    rec = _corp()
    rec["lines"].append(_line("note", "Number of ordinary shares", "2025-06-30", 10_000.0))
    fin.promote(db, _imp(db, rec)["report_id"])
    v = db.execute("SELECT value FROM financial_metrics WHERE metric = 'shares_outstanding'")[0]["value"]
    assert v == 10_000.0  # unit_scale 1000 applies to amounts only


def test_comparative_flags_compare_like_periods_only(db, monkeypatch):
    from tests import test_m2_m3_financials as m2
    monkeypatch.setitem(m2.YEARS, "2025-12-31", m2.YEARS["2025-06-30"])
    _imp(db, _corp(period="2024-12-31", prev="2023-12-31", sha="d" * 64, doc_type="half_yearly"))
    # a quarterly report whose comparative 2024-12-31 column is a 3-month figure: different period length
    q = _corp(period="2025-12-31", prev="2024-12-31", sha="e" * 64, doc_type="quarterly",
              overrides={("Net sales", "2024-12-31"): 300.0})
    r = _imp(db, q)
    assert not any(c["canonical_code"] == "revenue" for c in r["comparative_changes"])
    assert all(c["canonical_code"] in ("total_assets", "total_liabilities", "total_equity", "current_assets",
                                       "current_liabilities", "long_term_borrowings", "short_term_borrowings")
               for c in r["comparative_changes"])  # balance-sheet points may compare; flows may not


# ---------------------------------------------------------------- M4 / M5
def _ca(db, **rec):
    return mi.import_corporate_action(db, {"ticker": "OGDC", **rec}, importer="owner", source_note="notice")


def test_split_ratio_is_shares_after_per_share_before(db):
    days = sorted(_days(4))
    _bars(db, "OGDC", days, 200_000, close=100)
    _ca(db, action_type="split", ex_date=days[2], ratio=2)
    f = {b["d"]: b["factor"] for b in mi.adjusted_series(db, "OGDC", as_of=AS_OF)["bars"]}
    assert f[days[0]] == pytest.approx(0.5) and f[days[2]] == 1.0


def _val_setup(db, *, short_term=True, filed=None):
    over = {} if short_term else {("Short term borrowings", "2025-06-30"): None}
    rec = _corp(overrides=over, filed_at_utc=filed)
    rec["lines"] += [_line("CF", "Depreciation", "2025-06-30", -30.0),
                     _line("BS", "Cash and bank balances", "2025-06-30", 40.0)]
    fin.promote(db, _imp(db, rec)["report_id"])
    _bars(db, "OGDC", sorted(_days(3)), 200_000, close=70)


def test_missing_short_term_debt_is_not_zero(db):
    _val_setup(db, short_term=False)
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)["results"]}
    assert r["ev_ebitda"]["state"] == "insufficient_data"
    assert "short_term_borrowings" in r["ev_ebitda"]["missing"]


def test_bonus_after_period_end_restates_per_share_inputs(db):
    _val_setup(db)
    _ca(db, action_type="bonus", ex_date="2026-01-15", ratio=0.25)
    out = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)
    r = {x["method"]: x for x in out["results"]}
    # EPS 14 -> 11.2 after a 25% bonus; price 70 is post-bonus
    assert r["pe"]["base"] == pytest.approx(70 / 11.2)
    assert out["inputs"]["share_factor"] == pytest.approx(1.25)


def test_point_in_time_filing_dates(db):
    _val_setup(db)  # no filing date recorded
    lenient = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)
    assert lenient["inputs"]["filing_date_known"] is False and lenient["inputs"]["notes"]
    strict = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF, store=False,
                                               strict_point_in_time=True)["results"]}
    assert strict["pe"]["state"] == "insufficient_data"


def test_report_filed_after_as_of_is_excluded(db):
    _val_setup(db, filed="2026-11-15T00:00:00Z")
    r = {x["method"]: x for x in va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)["results"]}
    assert r["pe"]["state"] == "insufficient_data"


def test_valuation_writes_dimension_d_without_band(db):
    _val_setup(db)
    va.value(db, "cmp-ogdc", as_of=AS_OF)
    d = db.execute("SELECT data_state, band FROM dimension_assessments WHERE dimension = 'D'")
    assert len(d) == 1 and d[0]["band"] is None and d[0]["data_state"] in ("partial", "ok")


# ---------------------------------------------------------------- M6
def test_out_of_order_vintage_rejected(db):
    macro.load_registry(db)
    kw = {"importer": "owner", "release_url": None, "rights_attestation": "official release"}
    first = [{"reference_period": "2026-09-15", "value": 10.0, "release_date": "2026-09-15"}]
    earlier = [{"reference_period": "2026-09-15", "value": 10.5, "release_date": "2026-09-01"}]
    macro.import_observations(db, "sbp_policy_rate", first, release_title="a", **kw)
    r = macro.import_observations(db, "sbp_policy_rate", earlier, release_title="b", **kw)
    assert r["rejected"] and not r["added"]


# ---------------------------------------------------------------- M8
def test_same_turso_database_in_another_scheme_is_refused(monkeypatch):
    monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", "libsql://research-db.turso.io")
    with pytest.raises(DatabaseConfigError):
        pf.connect_portfolio("https://research-db.turso.io/")


def test_research_database_is_refused_for_every_write_path(db):
    with pytest.raises(DatabaseConfigError):
        pf.migrate_portfolio(db)
    with pytest.raises(DatabaseConfigError):
        pf.create_portfolio(db, "owner-a", "main")
    with pytest.raises(DatabaseConfigError):
        pf.add_alert_rule(db, "owner-a", kind="new_event", ticker="OGDC")
    with pytest.raises(DatabaseConfigError):
        pf.run_alerts(db, db, "owner-a", as_of=AS_OF)
    assert not db.execute("SELECT name FROM sqlite_master WHERE name IN ('portfolios', 'alert_rules')")


def test_connect_portfolio_refuses_a_research_schema(tmp_path):
    from database.migrate import migrate
    path = tmp_path / "research.db"
    r = SQLiteDatabase(str(path))
    migrate(r)
    r.close()
    with pytest.raises(DatabaseConfigError):
        pf.connect_portfolio(f"sqlite://{path}")
