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
}
REPORTED = {"car_pct": ("bank",)}  # shown as reported by the company, not recalculated
GROWTH = ("revenue", "profit_after_tax", "eps_basic", "net_interest_income", "net_premium", "total_assets")
DIMENSIONS = {
    "A": ("gross_margin", "operating_margin", "net_margin", "roe", "roe_average_equity", "roa",
          "cash_conversion", "claims_ratio",
          "nii_share_of_income", "cost_to_income"),
    "B": ("debt_to_equity", "current_ratio", "interest_cover", "liabilities_to_assets",
          "advances_to_deposits",
          "npl_to_advances", "car_pct"),
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def metrics(db, company_id: str, period_end: str, period_type: str, scope: str) -> dict[str, dict]:
    """Latest non-superseded value per metric: restated beats reported; never estimated."""
    rows = db.execute(
        "SELECT metric_id, metric, value, unit, basis, source_item_id, report_id FROM financial_metrics "
        "WHERE company_id = ? AND period_end = ? AND period_type = ? AND scope = ? "
        "AND basis IN ('reported','restated') "
        "ORDER BY CASE basis WHEN 'restated' THEN 0 ELSE 1 END, metric_id DESC",
        (company_id, period_end, period_type, scope))
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["metric"], dict(r))
    return out


def ratio(name: str, m: dict[str, dict], framework: str) -> dict:
    fws, formula, num, den = RATIOS[name]
    res = {"ratio": name, "formula": formula, "state": "ok", "value": None, "inputs": {}, "missing": []}
    if framework not in fws:
        res["state"] = "not_applicable"
        return res
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
    if name in ("cost_to_income", "claims_ratio"):
        n = abs(n)  # expenses may be presented as negatives
    if name == "interest_cover":
        d = abs(d)
    if d <= 0:
        res["state"] = "not_applicable"
        res["reason"] = "denominator is zero or negative"
        return res
    res["value"] = n / d
    return res


def choose_scope(db, company_id: str, period_end: str, period_type: str) -> str | None:
    scopes = {r["scope"] for r in db.execute(
        "SELECT DISTINCT scope FROM financial_metrics WHERE company_id = ? AND period_end = ? AND "
        "period_type = ? AND scope IS NOT NULL", (company_id, period_end, period_type))}
    return "consolidated" if "consolidated" in scopes else ("unconsolidated" if scopes else None)


def _prior_period(db, company_id: str, period_end: str, period_type: str, scope: str) -> str | None:
    target = date.fromisoformat(period_end) - timedelta(days=365)
    rows = db.execute("SELECT DISTINCT period_end FROM financial_metrics WHERE company_id = ? "
                      "AND period_type = ? "
                      "AND scope = ? AND period_end < ?", (company_id, period_type, scope, period_end))
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


def analyse(db, company_id: str, *, period_end: str, period_type: str = "FY") -> dict:
    framework = framework_for(db, company_id)
    scope = choose_scope(db, company_id, period_end, period_type)
    if scope is None:
        return {"company_id": company_id, "state": "insufficient_data", "reason": "no reported metrics",
                "framework": framework}
    m = metrics(db, company_id, period_end, period_type, scope)
    ratios = {name: ratio(name, m, framework) for name in RATIOS}
    for k, fws in REPORTED.items():
        ratios[k] = ({"ratio": k, "formula": "as reported", "state": "ok", "value": m[k]["value"],
                      "inputs": {k: {"metric_id": m[k]["metric_id"]}}, "missing": []}
                     if k in m and framework in fws else
                     {"ratio": k, "state": "not_applicable" if framework not in fws else "insufficient_data",
                      "value": None, "missing": [] if framework not in fws else [k]})
    prior = _prior_period(db, company_id, period_end, period_type, scope)
    pm = metrics(db, company_id, prior, period_type, scope) if prior else None
    g = {k: growth(m, pm, k) for k in GROWTH}
    ratios["roe_average_equity"] = roe_average(m, pm, framework)
    return {"company_id": company_id, "framework": framework, "period_end": period_end,
            "period_type": period_type, "scope": scope, "prior_period_end": prior, "ratios": ratios,
            "growth": g, "fcf": _fcf(m)}


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


def assess(db, company_id: str, *, period_end: str, period_type: str = "FY",
           as_of_date: str | None = None) -> dict:
    """Write dimensions A, B and C for one period. Re-running the same version and date is a no-op."""
    a = analyse(db, company_id, period_end=period_end, period_type=period_type)
    as_of = as_of_date or datetime.now(UTC).date().isoformat()
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
