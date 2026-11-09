"""Fundamentals: framework-specific ratios and dimensions A-C (master plan M3; architecture §3B and §5).

Inputs are canonical `financial_metrics` only (reported or restated, one scope at a time; consolidated is
preferred when both exist, and scopes are never mixed). Every ratio carries its formula, its inputs with
their period and source rows, and a state:
  ok | insufficient_data (an input is not reported; the missing inputs are listed) | not_applicable
  (the ratio does not apply to the framework, or its denominator is zero or negative).
Ratios use closing balances (stated in each formula); averages are not invented from one balance sheet.
ROE is reported on both bases: `roe` (closing equity, unchanged) and `roe_average_equity` (opening and closing
equity), which is `insufficient_data` when the prior fiscal year's equity is not imported.

Dimensions written to `dimension_assessments`:
  A fundamental quality (margins, returns), B financial strength (leverage, coverage, liquidity),
  C earnings growth (year-on-year, same period type).
Bands stay NULL until the owner sets thresholds (U9): the engine describes, it does not grade.
Reported, calculated and interpreted values are kept apart; nothing is estimated.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from engines.financials import framework_for

ENGINE_VERSION = "fundamentals/1"

# name: (frameworks, formula text, numerator terms, denominator terms, sign handling)
RATIOS: dict[str, tuple[tuple[str, ...], str, tuple[str, ...], tuple[str, ...]]] = {
    "gross_margin": (("corporate",), "gross_profit / revenue", ("gross_profit",), ("revenue",)),
    "operating_margin": (("corporate",), "operating_profit / revenue", ("operating_profit",), ("revenue",)),
    "net_margin": (("corporate",), "profit_after_tax / revenue", ("profit_after_tax",), ("revenue",)),
    "roe": (("corporate", "bank", "insurer"),
            "profit_after_tax / closing total_equity (closing-equity basis: overstates ROE when equity grew)",
            ("profit_after_tax",), ("total_equity",)),
    "roa": (("corporate", "bank", "insurer"), "profit_after_tax / closing total_assets",
            ("profit_after_tax",), ("total_assets",)),
    "asset_turnover_average": (("corporate",), "revenue / average(opening, closing) total_assets",
                               ("revenue",), ("total_assets",)),
    "roa_average_assets": (("corporate", "bank", "insurer"),
                           "profit_after_tax / average(opening, closing) total_assets",
                           ("profit_after_tax",), ("total_assets",)),
    "debt_to_equity": (("corporate",), "(long_term_borrowings + short_term_borrowings) / total_equity",
                       ("long_term_borrowings", "short_term_borrowings"), ("total_equity",)),
    "current_ratio": (("corporate",), "current_assets / current_liabilities", ("current_assets",),
                      ("current_liabilities",)),
    "interest_cover": (("corporate",), "operating_profit / finance_cost", ("operating_profit",),
                       ("finance_cost",)),
    "cash_conversion": (("corporate",), "cfo / profit_after_tax", ("cfo",), ("profit_after_tax",)),
    "liabilities_to_assets": (("corporate", "bank", "insurer"), "total_liabilities / total_assets",
                              ("total_liabilities",), ("total_assets",)),
    "advances_to_deposits": (("bank",), "advances_net / deposits", ("advances_net",), ("deposits",)),
    "npl_to_advances": (("bank",), "npl_gross / advances_net (net advances: stated)", ("npl_gross",),
                        ("advances_net",)),
    "nii_share_of_income": (("bank",), "net_interest_income / (net_interest_income + non_markup_income)",
                            ("net_interest_income",), ("net_interest_income", "non_markup_income")),
    "cost_to_income": (("bank",), "operating_expenses / (net_interest_income + non_markup_income)",
                       ("operating_expenses",), ("net_interest_income", "non_markup_income")),
    "claims_ratio": (("insurer",), "net_claims / net_premium", ("net_claims",), ("net_premium",)),
    # efficiency (fiscal-year figures; closing balances, stated)
    "asset_turnover": (("corporate",), "revenue / closing total_assets", ("revenue",), ("total_assets",)),
    "receivable_days": (("corporate",), "365 x closing trade_receivables / revenue", ("trade_receivables",),
                        ("revenue",)),
    "inventory_days": (("corporate",), "365 x closing inventory / |cost_of_sales|", ("inventory",),
                       ("cost_of_sales",)),
    # dividend sustainability
    "payout_ratio": (("corporate", "bank", "insurer"), "|dividends_paid| / profit_after_tax (cash basis)",
                     ("dividends_paid",), ("profit_after_tax",)),
}
DAYS = {"receivable_days", "inventory_days"}
ABS_NUM = {"cost_to_income", "claims_ratio", "payout_ratio"}
ABS_DEN = {"interest_cover", "inventory_days"}
REPORTED = {"car_pct": ("bank",)}  # shown as reported by the company, not recalculated
GROWTH = ("revenue", "profit_after_tax", "eps_basic", "net_interest_income", "net_premium", "total_assets")
DIMENSIONS = {
    "A": ("gross_margin", "operating_margin", "net_margin", "roe", "roe_average_equity", "roa",
          "cash_conversion", "claims_ratio", "asset_turnover", "receivable_days", "inventory_days",
          "nii_share_of_income", "cost_to_income"),
    "B": ("debt_to_equity", "current_ratio", "interest_cover", "liabilities_to_assets",
          "advances_to_deposits",
          "npl_to_advances", "car_pct", "payout_ratio", "dividend_cover_fcf"),
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _known(as_of: str, strict: bool) -> tuple[str, tuple]:
    """Filing gate for a report: filed on or before as_of. With `strict`, a report with NO filing date is
    excluded; otherwise it is kept and flagged by the caller. The SQL text is constant: the mode is a
    parameter, so no SQL is assembled from strings."""
    return ("((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL AND "
            "substr(r.filed_at_utc, 1, 10) <= ?))", (int(strict), as_of))


# The filing gate is written out in each query (constant SQL text). Parameters: (strict flag, as_of).
_GATE = ("((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL AND "
         "substr(r.filed_at_utc, 1, 10) <= ?))")
_METRICS_SQL = (
    "SELECT m.metric_id, m.metric, m.value, m.unit, m.basis, m.source_item_id, m.report_id, r.filed_at_utc "
    "FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
    "WHERE m.company_id = ? AND m.period_end = ? AND m.period_type = ? AND m.scope = ? "
    "AND m.basis IN ('reported','restated') "
    "AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
    "AND substr(r.filed_at_utc, 1, 10) <= ?)) "
    "ORDER BY CASE m.basis WHEN 'restated' THEN 0 ELSE 1 END, m.metric_id DESC")
_SCOPES_SQL = (
    "SELECT DISTINCT m.scope FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
    "WHERE m.company_id = ? AND m.period_end = ? AND m.period_type = ? AND m.scope IS NOT NULL "
    "AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
    "AND substr(r.filed_at_utc, 1, 10) <= ?))")
_PRIOR_SQL = (
    "SELECT DISTINCT m.period_end FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
    "WHERE m.company_id = ? AND m.period_type = ? AND m.scope = ? AND m.period_end < ? "
    "AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
    "AND substr(r.filed_at_utc, 1, 10) <= ?))")


def metrics(db, company_id: str, period_end: str, period_type: str, scope: str, *, as_of: str,
            strict: bool = False) -> dict[str, dict]:
    """Latest value per metric among reports FILED by `as_of`: restated beats reported, never estimated.
    A restatement filed after as_of is invisible, so it cannot change an earlier analysis."""
    rows = db.execute(_METRICS_SQL, (company_id, period_end, period_type, scope, int(strict), as_of))
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["metric"], dict(r))
    return out


# Ratios that divide a flow by a balance, or count days, depend on the length of the period. For an interim
# period they are scaled to a full year (flows) or to the days in the period (day counts); FY is unchanged.
ANNUALISE = {"asset_turnover", "roe", "roa", "asset_turnover_average", "roa_average_assets"}
PERIOD_MONTHS = {"FY": 12, "9M": 9, "H1": 6, "H2": 6, "Q1": 3, "Q2": 3, "Q3": 3, "Q4": 3}


# Ratios that divide a period flow by a balance use the average of opening and closing balances when the
# opening balance is available as a promoted metric; otherwise the closing balance, labelled as approximation.
# The existing ratios keep their closing-balance definitions (a documented contract). Average-balance versions
# are separate ratios; they are not computed without a promoted opening balance, never from a guess.
AVERAGE_RATIOS = {"asset_turnover_average": "total_assets", "roa_average_assets": "total_assets"}
CLOSING_APPROX = {"asset_turnover", "roe", "roa"}
# Day counts that use closing receivables or inventory are proxies, not exact collection or holding periods.
PROXY_DAYS = {"receivable_days", "inventory_days"}


def _months_before(period_end: str, months: int) -> str:
    """The last day of the month `months` before `period_end` (a balance date, e.g. 30 Jun for a Q1)."""
    from calendar import monthrange

    d = date.fromisoformat(period_end)
    y, mo = d.year, d.month - months
    while mo <= 0:
        mo += 12
        y -= 1
    return date(y, mo, monthrange(y, mo)[1]).isoformat()


def ratio(name: str, m: dict[str, dict], framework: str, period_months: int = 12,
          opening: dict[str, dict] | None = None) -> dict:
    fws, formula, num, den = RATIOS[name]
    res = {"ratio": name, "formula": formula, "state": "ok", "value": None, "inputs": {}, "missing": []}
    if framework not in fws:
        res["state"] = "not_applicable"
        return res
    if name in AVERAGE_RATIOS:
        key = AVERAGE_RATIOS[name]
        if not (opening and key in opening and key in m):
            res["state"] = "insufficient_data"
            res["missing"] = [f"opening {key}"]  # no opening balance promoted for this scope: not estimated
            return res
        den = (key,)
        res["average_balance"] = {"opening": opening[key]["value"], "closing": m[key]["value"]}
        res["basis"] = "average of opening and closing balance"
    elif name in CLOSING_APPROX:
        res["approximation"] = "closing balance used; see the average-balance ratio where available"
    if name == "payout_ratio" and period_months != 12:
        res["period_note"] = "interim period: compare only with other interim periods"
    if name in PROXY_DAYS:
        res["approximation"] = ("proxy: closing balance over period revenue or cost; "
                                "not an exact collection or holding period")
    for k in num + den:
        if k not in m:
            res["missing"].append(k)
        else:
            res["inputs"][k] = {"value": m[k]["value"], "metric_id": m[k]["metric_id"],
                                "basis": m[k]["basis"]}
    if res["missing"]:
        res["state"] = "insufficient_data"
        return res
    n = sum(m[k]["value"] for k in num)
    d = sum(m[k]["value"] for k in den)
    if "average_balance" in res:
        d = (res["average_balance"]["opening"] + res["average_balance"]["closing"]) / 2
    if name in ABS_NUM:
        n = abs(n)  # expenses and outflows may be presented as negatives
    if name in ABS_DEN:
        d = abs(d)
    if d <= 0:
        res["state"] = "not_computable"  # a zero or negative denominator: never shown as a ratio
        res["reason"] = "denominator is zero or negative"
        return res
    value = n / d
    if name in DAYS:
        value *= 365 * period_months / 12  # days in the period, not a fixed 365 for a quarter
        res["period_basis"] = f"days in a {period_months}-month period"
    elif name in ANNUALISE and period_months != 12:
        value *= 12 / period_months  # annual equivalent of a flow over a balance
        res["period_basis"] = f"annualised from a {period_months}-month period"
    res["value"] = value
    if res["value"] < 0:
        # A loss-making numerator is shown as a negative value with an explicit flag, never as a strong ratio.
        res["sign"] = "negative_numerator"
    return res


def choose_scope(db, company_id: str, period_end: str, period_type: str, *, as_of: str,
                 strict: bool = False) -> str | None:
    scopes = {r["scope"] for r in db.execute(_SCOPES_SQL, (company_id, period_end, period_type,
                                                           int(strict), as_of))}
    return "consolidated" if "consolidated" in scopes else ("unconsolidated" if scopes else None)


def _prior_period(db, company_id: str, period_end: str, period_type: str, scope: str, *, as_of: str,
                  strict: bool = False) -> str | None:
    target = date.fromisoformat(period_end) - timedelta(days=365)
    rows = db.execute(_PRIOR_SQL, (company_id, period_type, scope, period_end, int(strict), as_of))
    for r in rows:
        if abs((date.fromisoformat(r["period_end"]) - target).days) <= 10:
            return r["period_end"]
    return None


def growth(cur: dict, prev: dict | None, key: str) -> dict:
    res = {"metric": key, "formula": f"{key}(t) / {key}(t-1y) - 1", "state": "ok", "value": None}
    if prev is None:
        return {**res, "state": "insufficient_data", "missing": ["prior-year period"]}
    if key not in cur or key not in prev:
        miss = [k for k, d in (("current", cur), ("prior", prev)) if key not in d]
        return {**res, "state": "insufficient_data", "missing": miss}
    a, b = cur[key]["value"], prev[key]["value"]
    if b <= 0:
        return {**res, "state": "not_applicable", "reason": "prior value is zero or negative",
                "current": a, "prior": b}
    return {**res, "value": a / b - 1, "current": a, "prior": b}


def _opening_balances(db, company_id: str, scope: str, period_end: str, months: int, *, as_of: str,
                      strict: bool) -> dict[str, dict]:
    """Promoted balances at the opening date of this period, for the same scope only."""
    opening_end = _months_before(period_end, months)
    rows = db.execute(
        "SELECT m.metric, m.value, m.metric_id, m.basis "
        "FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
        "WHERE m.company_id = ? AND m.period_end = ? AND m.scope = ? "
        "AND m.metric IN ('total_assets','total_equity') AND m.basis IN ('reported','restated') "
        "AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
        "AND substr(r.filed_at_utc, 1, 10) <= ?))",
        (company_id, opening_end, scope, int(strict), as_of))
    return {r["metric"]: {"value": r["value"], "metric_id": r["metric_id"], "basis": r["basis"]}
            for r in rows}


def analyse(db, company_id: str, *, period_end: str, as_of: str, period_type: str = "FY",
            strict: bool = True) -> dict:
    """Ratios for one period, using only reports filed by `as_of` (required).
    Unknown filing dates are kept unless `strict`; `filing_dates_unknown` lists the reports relying on them.
    """
    framework = framework_for(db, company_id)
    scope = choose_scope(db, company_id, period_end, period_type, as_of=as_of, strict=strict)
    if scope is None:
        return {"company_id": company_id, "state": "insufficient_data", "reason": "no reported metrics filed "
                "by the as-of date", "framework": framework, "as_of": as_of}
    m = metrics(db, company_id, period_end, period_type, scope, as_of=as_of, strict=strict)
    months = PERIOD_MONTHS.get(period_type, 12)
    opening = _opening_balances(db, company_id, scope, period_end, months, as_of=as_of, strict=strict)
    ratios = {name: ratio(name, m, framework, months, opening) for name in RATIOS}
    for k, fws in REPORTED.items():
        ratios[k] = ({"ratio": k, "formula": "as reported", "state": "ok", "value": m[k]["value"],
                      "inputs": {k: {"metric_id": m[k]["metric_id"]}}, "missing": []}
                     if k in m and framework in fws else
                     {"ratio": k, "state": "not_applicable" if framework not in fws else "insufficient_data",
                      "value": None, "missing": [] if framework not in fws else [k]})
    prior = _prior_period(db, company_id, period_end, period_type, scope, as_of=as_of, strict=strict)
    pm = metrics(db, company_id, prior, period_type, scope, as_of=as_of, strict=strict) if prior else None
    unknown = sorted({r["report_id"] for r in db.execute(
        "SELECT DISTINCT m.report_id FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
        "WHERE m.company_id = ? AND m.scope = ? AND m.period_type = ? AND m.period_end IN (?, ?) "
        "AND r.filed_at_utc IS NULL AND m.report_id IS NOT NULL", (company_id, scope, period_type, period_end,
                                                                  prior or period_end))})
    g = {k: growth(m, pm, k) for k in GROWTH}
    ratios["roe_average_equity"] = roe_average(m, pm, framework)
    ratios["dividend_cover_fcf"] = _dividend_cover(m)
    return {"company_id": company_id, "framework": framework, "period_end": period_end, "as_of": as_of,
            "period_type": period_type, "scope": scope, "prior_period_end": prior, "ratios": ratios,
            "growth": g, "fcf": _fcf(m), "filing_dates_unknown": unknown, "strict": strict,
            "state": "ok" if not unknown or strict else "ok_with_unknown_filing_dates"}


def roe_average(cur: dict, prev: dict | None, framework: str) -> dict:
    """PAT / average of opening (prior FY closing) and closing equity. Kept separate from `roe`, which
    uses closing equity only and is unchanged for compatibility."""
    res = {"ratio": "roe_average_equity", "formula": "profit_after_tax / ((total_equity(t) + "
                                                     "total_equity(t-1)) / 2)",
           "basis": "average equity", "state": "ok", "value": None, "inputs": {}, "missing": []}
    need = [("profit_after_tax", cur), ("total_equity", cur)]
    res["missing"] = [k for k, d in need if k not in d]
    if prev is None or "total_equity" not in prev:
        res["missing"].append("opening total_equity (prior fiscal year)")
    if res["missing"]:
        return {**res, "state": "insufficient_data",
                "note": "use `roe` (closing-equity basis) and its stated limitation"}
    avg = (cur["total_equity"]["value"] + prev["total_equity"]["value"]) / 2
    def ref(d, k):
        return {"value": d[k]["value"], "metric_id": d[k]["metric_id"]}

    res["inputs"] = {"profit_after_tax": ref(cur, "profit_after_tax"),
                     "closing_equity": ref(cur, "total_equity"),
                     "opening_equity": ref(prev, "total_equity")}
    if avg <= 0:
        return {**res, "state": "not_applicable", "reason": "average equity is zero or negative"}
    return {**res, "value": cur["profit_after_tax"]["value"] / avg}


def _dividend_cover(m: dict) -> dict:
    res = {"ratio": "dividend_cover_fcf", "formula": "(cfo - |capex|) / |dividends_paid|", "state": "ok",
           "value": None, "missing": [k for k in ("cfo", "capex", "dividends_paid") if k not in m]}
    if res["missing"]:
        return {**res, "state": "insufficient_data"}
    div = abs(m["dividends_paid"]["value"])
    if div == 0:
        return {**res, "state": "not_applicable", "reason": "no dividends paid"}
    return {**res, "value": (m["cfo"]["value"] - abs(m["capex"]["value"])) / div,
            "inputs": {k: {"value": m[k]["value"], "metric_id": m[k]["metric_id"]}
                       for k in ("cfo", "capex", "dividends_paid")}}


def _fcf(m: dict) -> dict:
    if "cfo" not in m or "capex" not in m:
        return {"state": "insufficient_data", "missing": [k for k in ("cfo", "capex") if k not in m]}
    return {"state": "ok", "formula": "cfo - |capex|", "value": m["cfo"]["value"] - abs(m["capex"]["value"])}


def _state(items: list[dict]) -> str:
    app = [i for i in items if i["state"] != "not_applicable"]
    if not app:
        return "not_applicable"
    ok = sum(i["state"] == "ok" for i in app)
    return "ok" if ok == len(app) else ("partial" if ok else "insufficient_data")


def assess(db, company_id: str, *, period_end: str, as_of_date: str, period_type: str = "FY",
           strict: bool = True) -> dict:
    """Write dimensions A, B and C for one period as known on `as_of_date` (required). Re-running the same
    version and date is a no-op."""
    as_of = as_of_date
    a = analyse(db, company_id, period_end=period_end, period_type=period_type, as_of=as_of, strict=strict)
    if a.get("state") == "insufficient_data":
        dims = {d: ([], "insufficient_data") for d in "ABC"}
    else:
        dims = {d: ([a["ratios"][n] for n in names], None) for d, names in DIMENSIONS.items()}
        dims["C"] = (list(a["growth"].values()), None)
    out = {}
    for d, (items, forced) in dims.items():
        st = forced or _state(items)
        db.execute(
            "INSERT INTO dimension_assessments(company_id, dimension, as_of_date, period_end, scope, "
            "data_state, band, components_json, evidence_json, engine_version, created_at_utc) "
            "VALUES (?,?,?,?,?,?,NULL,?,?,?,?) ON CONFLICT DO NOTHING",
            (company_id, d, as_of, period_end, a.get("scope"), st, json.dumps(items),
             json.dumps({"period_type": period_type, "framework": a.get("framework"),
                         "prior_period_end": a.get("prior_period_end"),
                         "band_note": "no band: thresholds are an owner decision (U9)"}),
             ENGINE_VERSION, _now()))
        out[d] = st
    return {"analysis": a, "dimensions": out}
