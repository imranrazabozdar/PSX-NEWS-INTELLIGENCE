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


def _val_setup(db, *, short_term=True, filed="2025-09-30T00:00:00Z"):
    """Valuation fixture. The FY2025 report is filed on a known date before the as-of date (strict default);
    pass filed=None to model an unknown filing date."""
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
    _val_setup(db, filed=None)  # unknown filing date: excluded in strict mode, and not used at all
    strict = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)
    assert strict["inputs"]["fy_period_end"] is None  # strict: the unfiled report is not used
    lenient = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False, strict_point_in_time=False)
    assert lenient["inputs"]["fy_period_end"] == "2025-06-30"
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


# ---------------------------------------------------------------- DCF basis (FCFF vs FCFE)
def _dcf(db, **a):
    rng = {"cash_flow_growth": (0.0, 0.0, 0.0), "terminal_growth": (0.0, 0.0, 0.0), "years": 1,
           "base_cash_flow": 100_000.0}
    out = va.value(db, "cmp-ogdc", as_of=AS_OF, assumptions={"dcf": {**rng, **a}}, store=False)
    return {x["method"]: x for x in out["results"]}["dcf"]


def test_fcff_at_wacc_gives_ev_then_equity(db):
    _val_setup(db)  # shares derived 10,000; borrowings 80,000 + 20,000, cash 40,000 (PKR)
    d = _dcf(db, basis="fcff", wacc=(0.10, 0.10, 0.10), other_claims=50_000.0)
    # PV = 100,000/1.1 + 100,000/0.1/1.1 = 1,000,000 (enterprise value); net debt 60,000 (reported)
    assert d["state"] == "ok" and d["inputs"]["present_value_kind"] == "enterprise_value"
    assert d["inputs"]["base_present_value"] == pytest.approx(1_000_000)
    assert d["inputs"]["net_debt"] == pytest.approx(60_000) and "reported" in d["inputs"]["net_debt_source"]
    assert d["base"] == pytest.approx((1_000_000 - 60_000 - 50_000) / 10_000)


def test_fcfe_at_cost_of_equity_is_equity_without_net_debt(db):
    _val_setup(db)
    d = _dcf(db, basis="fcfe", cost_of_equity=(0.10, 0.10, 0.10), net_debt=999_999.0)
    assert d["inputs"]["present_value_kind"] == "equity_value" and "net_debt" not in d["inputs"]
    assert d["base"] == pytest.approx(1_000_000 / 10_000)  # net debt never deducted from FCFE value


def test_dcf_refuses_missing_or_mixed_inputs(db):
    _val_setup(db)
    assert _dcf(db, wacc=(0.1, 0.1, 0.1), other_claims=0)["state"] == "insufficient_data"  # no basis
    assert "other_claims" in _dcf(db, basis="fcff", wacc=(0.1, 0.1, 0.1))["missing"]
    mixed = _dcf(db, basis="fcff", cost_of_equity=(0.1, 0.1, 0.1), other_claims=0)
    assert mixed["state"] == "insufficient_data" and "mix bases" in mixed["note"]
    assert _dcf(db, basis="fcfe", wacc=(0.1, 0.1, 0.1))["state"] == "insufficient_data"
    unordered = _dcf(db, basis="fcfe", cost_of_equity=(0.12, 0.10, 0.11))
    assert unordered["state"] == "insufficient_data"
    none = va.value(db, "cmp-ogdc", as_of=AS_OF, store=False)
    assert {x["method"]: x for x in none["results"]}["dcf"]["state"] == "needs_assumptions"


def test_dcf_net_debt_required_when_not_reported(db):
    _val_setup(db, short_term=False)
    d = _dcf(db, basis="fcff", wacc=(0.1, 0.1, 0.1), other_claims=0)
    assert d["state"] == "insufficient_data" and d["base"] is None
    assert _dcf(db, basis="fcff", wacc=(0.1, 0.1, 0.1), other_claims=0, net_debt=0.0)["state"] == "ok"


def test_dcf_invalid_rate_and_terminal_consistency(db):
    _val_setup(db)
    bad = _dcf(db, basis="fcfe", cost_of_equity=(0.02, 0.03, 0.04), terminal_growth=(0.03, 0.03, 0.03))
    assert bad["state"] == "not_applicable" and bad["base"] is None
    # 2 explicit years at 10% growth, terminal growth 2%, discount 12%: hand calculation
    d = _dcf(db, basis="fcfe", cost_of_equity=(0.12, 0.12, 0.12), years=2, cash_flow_growth=(0.1, 0.1, 0.1),
             terminal_growth=(0.02, 0.02, 0.02))
    c1, c2 = 110_000, 121_000
    pv = c1 / 1.12 + c2 / 1.12 ** 2 + c2 * 1.02 / (0.12 - 0.02) / 1.12 ** 2
    assert d["inputs"]["base_present_value"] == pytest.approx(pv)


def test_dcf_sensitivity_keeps_basis_and_conversion(db):
    _val_setup(db)
    d = _dcf(db, basis="fcff", wacc=(0.09, 0.10, 0.11), other_claims=0.0)
    assert set(d["sensitivity"]) == {"wacc=0.0900", "wacc=0.1000", "wacc=0.1100"}
    cell = d["sensitivity"]["wacc=0.1000"]["tg=0.0000"]
    assert cell == pytest.approx((1_000_000 - 60_000) / 10_000)  # every cell converts EV to equity
    assert d["conservative"] < d["base"] < d["optimistic"]


# ---------------------------------------------------------------- ROE bases
def test_roe_closing_and_average_bases(db):
    from engines import fundamentals as fu
    from engines import reports

    fin.promote(db, _imp(db, _corp())["report_id"])
    one = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)["ratios"]
    assert one["roe"]["value"] == pytest.approx(0.7) and "closing" in one["roe"]["formula"]
    assert one["roe_average_equity"]["state"] == "insufficient_data"  # no opening equity imported
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64))["report_id"])
    two = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)["ratios"]
    assert two["roe"]["value"] == pytest.approx(0.7)  # unchanged formula
    assert two["roe_average_equity"]["value"] == pytest.approx(140 / ((200 + 170) / 2))
    body = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)
    fp = body["fundamental_performance"]
    assert "closing" in fp["roe"]["formula"] and fp["roe_average_equity"]["basis"] == "average equity"


def test_report_respects_filing_dates(db):
    from engines import reports

    fin.promote(db, _imp(db, _corp(filed_at_utc="2026-12-01T00:00:00Z"))["report_id"])
    body = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)  # filed after as_of: not yet known
    assert body["fundamental_performance"] == {"state": "data_unavailable"}
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64,
                                   filed_at_utc="2025-09-30T00:00:00Z"))["report_id"])
    body = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)
    assert body["executive_summary"]["fundamentals"]["period_end"] == "2024-06-30"
    # an unknown-date report is excluded in strict mode and counted, never silently used
    r = _imp(db, _corp(filed_at_utc=None, sha="f" * 64))  # FY2025, unknown filing date, its own document
    fin.promote(db, r["report_id"])
    body = reports.company_report(db, "cmp-ogdc", as_of=AS_OF)
    assert body["point_in_time"]["excluded_unknown_filing_date_reports"] == 1
    assert body["executive_summary"]["fundamentals"]["period_end"] == "2024-06-30"


def test_efficiency_and_dividend_ratios(db):
    from engines import fundamentals as fu

    rec = _corp()
    rec["lines"] += [_line("BS", "Trade debts", "2025-06-30", 50.0),
                     _line("BS", "Stock in trade", "2025-06-30", 60.0),
                     _line("CF", "Dividends paid", "2025-06-30", -35.0)]
    fin.promote(db, _imp(db, rec)["report_id"])
    r = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)["ratios"]
    assert r["asset_turnover"]["value"] == pytest.approx(2.0)
    assert r["receivable_days"]["value"] == pytest.approx(365 * 50 / 1000)
    assert r["inventory_days"]["value"] == pytest.approx(365 * 60 / 600)
    assert r["payout_ratio"]["value"] == pytest.approx(0.25)
    assert r["dividend_cover_fcf"]["value"] == pytest.approx((175 - 70) / 35)
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64))["report_id"])
    later = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of=AS_OF)["ratios"]
    assert later["payout_ratio"]["state"] == "insufficient_data"


# ---------------------------------------------------------------- point-in-time fundamentals (PR #41 review)
def _pit_setup(db):
    """FY2024 filed 2025-09-30 (revenue 800); FY2025 filed 2026-09-30 (revenue 1000); FY2024 restated later
    (filed 2026-12-01: revenue 790 and gross profit 290, kept consistent so it reconciles). Shared by the
    point-in-time tests below."""
    from engines import financials as fin  # noqa: F401 - used by callers through promote

    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64,
                                   filed_at_utc="2025-09-30T00:00:00Z"))["report_id"])
    fin.promote(db, _imp(db, _corp(filed_at_utc="2026-09-30T00:00:00Z"))["report_id"])
    fin.promote(db, _imp(db, _corp(period="2024-06-30", prev="2023-06-30", sha="c" * 64,
                                   overrides={("Net sales", "2024-06-30"): 790.0,
                                              ("Gross profit", "2024-06-30"): 290.0},
                                   filed_at_utc="2026-12-01T00:00:00Z"))["report_id"])


def test_report_filed_after_as_of_is_invisible(db):
    from engines import fundamentals as fu

    _pit_setup(db)
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-06-30")
    assert a["state"] == "insufficient_data"  # FY2025 was filed 2026-09-30: not known on 2026-06-30
    assert a["reason"] and "filed" in a["reason"]


def test_later_restatement_does_not_leak_into_earlier_date(db):
    from engines import fundamentals as fu

    _pit_setup(db)  # FY2024 revenue 800 (filed 2025-09-30); restated to 790 on 2026-12-01
    before = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of="2026-06-30")
    assert before["ratios"]["gross_margin"]["inputs"]["revenue"]["value"] == 800_000.0  # unit scale 1000
    after = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of="2026-12-31")
    assert after["ratios"]["gross_margin"]["inputs"]["revenue"]["value"] == 790_000.0  # now filed


def test_unknown_filing_date_is_visible_and_excluded_when_strict(db):
    from engines import fundamentals as fu

    fin.promote(db, _imp(db, _corp(filed_at_utc=None))["report_id"])  # unknown filing date
    strict = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)  # strict is the default
    assert strict["state"] == "insufficient_data"
    lenient = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF, strict=False)
    assert lenient["filing_dates_unknown"] and lenient["state"] == "ok_with_unknown_filing_dates"


def test_prior_period_roe_and_growth_respect_as_of(db):
    from engines import fundamentals as fu

    _pit_setup(db)
    early = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2025-12-31")
    assert early["state"] == "insufficient_data"  # FY2025 not filed yet
    mid = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-10-01")
    assert mid["prior_period_end"] == "2024-06-30"
    assert mid["growth"]["revenue"]["prior"] == 800_000.0  # pre-restatement value (unit scale 1000)
    assert mid["ratios"]["roe_average_equity"]["state"] == "ok"
    late = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-12-31")
    assert late["growth"]["revenue"]["prior"] == 790_000.0  # restated prior year, once filed


def test_restatement_takes_precedence_once_filed_and_scope_is_kept(db):
    from engines import fundamentals as fu

    _pit_setup(db)
    rows = db.execute("SELECT basis, r.filed_at_utc FROM financial_metrics m "
                      "JOIN financial_reports r USING(report_id) WHERE m.metric = 'revenue' "
                      "AND m.period_end = '2024-06-30' ORDER BY r.filed_at_utc")
    assert [r["basis"] for r in rows] == ["reported", "reported"]  # both kept: history is not overwritten
    later = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of="2026-12-31")
    assert later["ratios"]["gross_margin"]["inputs"]["revenue"]["value"] == 790_000.0
    assert later["scope"] == "unconsolidated"


def test_ratio_missing_zero_negative_and_units(db):
    from engines import fundamentals as fu

    rec = _corp()
    rec["lines"] = [ln for ln in rec["lines"] if ln["raw_label"] != "Total current liabilities"]
    fin.promote(db, _imp(db, rec)["report_id"])
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)["ratios"]
    cr = a["current_ratio"]
    assert cr["state"] == "insufficient_data" and cr["value"] is None  # missing is never zero
    assert cr["missing"] == ["current_liabilities"]
    # Units: the same ratio is unit-free; amounts carry the unit scale, so the result is scale-invariant.
    assert a["gross_margin"]["value"] == pytest.approx(0.4)
    assert a["roe"]["inputs"]["profit_after_tax"]["value"] == 140_000.0  # PKR, scaled from thousands


def test_negative_numerator_is_flagged_and_zero_denominator_is_not_applicable(db):
    from engines import fundamentals as fu

    rec = _corp(overrides={("Operating profit", "2025-06-30"): -50.0})
    fin.promote(db, _imp(db, rec)["report_id"])
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of=AS_OF)["ratios"]
    assert a["operating_margin"]["value"] < 0 and a["operating_margin"]["sign"] == "negative_numerator"
    assert "sign" not in a["gross_margin"]
    zero = _corp(period="2024-06-30", prev="2023-06-30", sha="d" * 64,
                 overrides={("Total equity", "2024-06-30"): 0.0,
                            ("Total liabilities", "2024-06-30"): 450.0})  # assets = liabilities + equity
    fin.promote(db, _imp(db, zero)["report_id"])
    z = fu.analyse(db, "cmp-ogdc", period_end="2024-06-30", as_of=AS_OF)["ratios"]
    assert z["roe"]["state"] == "not_applicable" and z["roe"]["value"] is None
