"""Valuation (master plan M5; architecture §3C). Ranges with stated assumptions, never price targets.

Inputs (all traceable): the latest stored SCS daily close on or before the as-of date (actual, unadjusted),
the latest fiscal-year canonical metrics with period end on or before the as-of date (and, where the filing
date is recorded, filed on or before it: no look-ahead), and owner-recorded cash dividends.

Methods and states:
* pe, pb, ev_ebitda, dividend_yield: observed multiples from reported data. `not_applicable` when the
  denominator is zero or negative (e.g. a loss-making P/E) or the method does not fit the framework
  (EV/EBITDA for banks and insurers); `insufficient_data` with the missing inputs otherwise.
* forward_pe: needs consensus estimates, which have no approved source (U6). Always `insufficient_data`;
  internal scenarios are never presented as consensus.
* ddm, dcf, justified_pb (banks): model values per share computed ONLY from owner-supplied assumptions,
  each given as (low, base, high). Without them the state is `needs_assumptions` and the required keys are
  listed. conservative / base / optimistic use the pessimistic, central and optimistic combination, and a
  sensitivity grid is stored. These are model outputs under stated assumptions, not forecasts or targets.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from engines.financials import framework_for

ENGINE_VERSION = "valuation/1"
REQUIRED = {
    "ddm": ("cost_of_equity", "dividend_growth"),
    "dcf": ("discount_rate", "fcf_growth", "terminal_growth", "years"),
    "justified_pb": ("cost_of_equity", "sustainable_growth"),
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ticker(db, company_id: str) -> str | None:
    r = db.execute("SELECT value FROM company_identifiers WHERE company_id = ? AND id_type = 'psx_ticker' "
                   "AND valid_to IS NULL", (company_id,))
    return r[0]["value"] if r else None


def inputs(db, company_id: str, *, as_of: str) -> dict:
    t = _ticker(db, company_id)
    px = db.execute("SELECT session_date_pkt, close FROM market_bars_current WHERE source_id = 'scs_chart' "
                    "AND "
                    "symbol = ? AND timeframe = '1d' AND session_date_pkt <= ? ORDER BY session_date_pkt "
                    "DESC "
                    "LIMIT 1", (t, as_of)) if t else []
    fy = db.execute(
        "SELECT m.period_end, m.scope FROM financial_metrics m LEFT JOIN financial_reports r "
        "USING(report_id) "
        "WHERE m.company_id = ? AND m.period_type = 'FY' AND m.period_end <= ? AND m.basis IN "
        "('reported','restated') AND (r.filed_at_utc IS NULL OR substr(r.filed_at_utc, 1, 10) <= ?) "
        "ORDER BY m.period_end DESC, CASE m.scope WHEN 'consolidated' THEN 0 ELSE 1 END LIMIT 1",
        (company_id, as_of, as_of))
    m: dict[str, dict] = {}
    if fy:
        for r in db.execute(
            "SELECT metric_id, metric, value, basis FROM financial_metrics WHERE company_id = ? AND "
            "period_type = 'FY' AND period_end = ? AND scope = ? AND basis IN ('reported','restated') "
            "ORDER BY CASE basis WHEN 'restated' THEN 0 ELSE 1 END, metric_id DESC",
                (company_id, fy[0]["period_end"], fy[0]["scope"])):
            m.setdefault(r["metric"], dict(r))
    shares, shares_basis = None, None
    if "shares_outstanding" in m:
        shares, shares_basis = m["shares_outstanding"]["value"], "reported"
    elif "profit_after_tax" in m and m.get("eps_basic", {}).get("value"):
        shares = m["profit_after_tax"]["value"] / m["eps_basic"]["value"]
        shares_basis = "derived: profit_after_tax / eps_basic (weighted average, approximate)"
    start = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
    dps = db.execute("SELECT COALESCE(SUM(amount_per_share), 0) AS s, COUNT(*) AS n FROM corporate_actions "
                     "WHERE company_id = ? AND action_type = 'cash_dividend' AND status <> 'cancelled' AND "
                     "ex_date > ? AND ex_date <= ?", (company_id, start, as_of))[0]
    return {"ticker": t, "price": px[0]["close"] if px else None, "price_date": px[0]["session_date_pkt"]
            if px else None, "fy_period_end": fy[0]["period_end"] if fy else None,
            "scope": fy[0]["scope"] if fy else None, "metrics": m, "shares": shares,
            "shares_basis": shares_basis,
            "dps_ttm": dps["s"] if dps["n"] else None, "framework": framework_for(db, company_id)}


def _v(i: dict, k: str) -> float | None:
    return i["metrics"].get(k, {}).get("value")


def _res(method, state, *, inputs_=None, missing=(), base=None, cons=None, opt=None, assumptions=None,
         sensitivity=None, note=None):
    return {"method": method, "state": state, "inputs": inputs_ or {}, "missing": list(missing),
            "conservative": cons, "base": base, "optimistic": opt, "assumptions": assumptions or {},
            "sensitivity": sensitivity, "note": note}


def _need(i, keys):
    return [k for k in keys if (i.get(k) if k in ("price", "shares", "dps_ttm") else _v(i, k)) is None]


def multiples(i: dict) -> list[dict]:
    out = []
    miss = _need(i, ("price", "eps_basic"))
    if miss:
        out.append(_res("pe", "insufficient_data", missing=miss))
    elif _v(i, "eps_basic") <= 0:
        out.append(_res("pe", "not_applicable", inputs_={"eps_basic": _v(i, "eps_basic")},
                        note="earnings per share is zero or negative"))
    else:
        out.append(_res("pe", "ok", base=i["price"] / _v(i, "eps_basic"),
                        inputs_={"price": i["price"], "eps_basic": _v(i, "eps_basic")}, note="trailing FY"))
    miss = _need(i, ("price", "shares", "total_equity"))
    if miss:
        out.append(_res("pb", "insufficient_data", missing=miss))
    elif _v(i, "total_equity") <= 0 or i["shares"] <= 0:
        out.append(_res("pb", "not_applicable", note="book value is zero or negative"))
    else:
        bvps = _v(i, "total_equity") / i["shares"]
        out.append(_res("pb", "ok", base=i["price"] / bvps, inputs_={"price": i["price"], "bvps": bvps,
                                                                     "shares_basis": i["shares_basis"]}))
    if i["framework"] != "corporate":
        out.append(_res("ev_ebitda", "not_applicable", note=f"not meaningful for a {i['framework']}"))
    else:
        miss = _need(i, ("price", "shares", "operating_profit", "depreciation_amortisation",
                         "long_term_borrowings", "cash_and_equivalents"))
        if miss:
            out.append(_res("ev_ebitda", "insufficient_data", missing=miss))
        else:
            debt = _v(i, "long_term_borrowings") + (_v(i, "short_term_borrowings") or 0.0)
            ev = i["price"] * i["shares"] + debt - _v(i, "cash_and_equivalents")
            ebitda = _v(i, "operating_profit") + abs(_v(i, "depreciation_amortisation"))
            note = (None if _v(i, "short_term_borrowings") is not None
                    else "short-term borrowings not reported")
            out.append(_res("ev_ebitda", "ok" if ebitda > 0 else "not_applicable",
                            base=ev / ebitda if ebitda > 0 else None,
                            inputs_={"ev": ev, "ebitda": ebitda, "debt": debt}, note=note))
    miss = _need(i, ("price", "dps_ttm"))
    out.append(_res("dividend_yield", "insufficient_data", missing=miss) if miss else
               _res("dividend_yield", "ok", base=i["dps_ttm"] / i["price"],
                    inputs_={"dps_ttm": i["dps_ttm"], "price": i["price"]},
                    note="owner-recorded cash dividends with ex-date in the last 365 days"))
    out.append(_res("forward_pe", "insufficient_data", missing=["consensus_eps (U6: no approved source)"]))
    return out


def _gordon(d0, r, g):
    return None if r <= g else d0 * (1 + g) / (r - g)


def _dcf(fcf0, r, g, tg, years):
    if r <= tg:
        return None
    pv, f = 0.0, fcf0
    for t in range(1, int(years) + 1):
        f *= 1 + g
        pv += f / (1 + r) ** t
    return pv + f * (1 + tg) / (r - tg) / (1 + r) ** int(years)


def models(i: dict, assumptions: dict | None) -> list[dict]:
    a = assumptions or {}
    out = []
    for method, keys in REQUIRED.items():
        if method == "justified_pb" and i["framework"] != "bank":
            out.append(_res(method, "not_applicable", note="justified P/B is used for banks"))
            continue
        if method not in a or any(k not in a[method] for k in keys):
            have = a.get(method, {})
            out.append(_res(method, "needs_assumptions", missing=[k for k in keys if k not in have],
                            note="owner-supplied (low, base, high) assumptions required"))
            continue
        aa = {k: tuple(a[method][k]) for k in keys}
        note = "model value per share under the stated assumptions; not a forecast or target"
        if method == "ddm":
            if i["dps_ttm"] is None or i["dps_ttm"] <= 0:
                out.append(_res(method, "insufficient_data", missing=["dps_ttm"], assumptions=aa))
                continue
            r, g = aa["cost_of_equity"], aa["dividend_growth"]
            vals = (_gordon(i["dps_ttm"], r[2], g[0]), _gordon(i["dps_ttm"], r[1], g[1]),
                    _gordon(i["dps_ttm"], r[0], g[2]))
            grid = {f"r={rr:.4f}": {f"g={gg:.4f}": _gordon(i["dps_ttm"], rr, gg) for gg in g} for rr in r}
        elif method == "dcf":
            miss = _need(i, ("cfo", "capex", "shares"))
            if miss:
                out.append(_res(method, "insufficient_data", missing=miss, assumptions=aa))
                continue
            fcf_ps = (_v(i, "cfo") - abs(_v(i, "capex"))) / i["shares"]
            if fcf_ps <= 0:
                out.append(_res(method, "not_applicable", note="latest free cash flow is zero or negative",
                                assumptions=aa))
                continue
            r, g, tg, n = aa["discount_rate"], aa["fcf_growth"], aa["terminal_growth"], aa["years"][1]
            vals = (_dcf(fcf_ps, r[2], g[0], tg[0], n), _dcf(fcf_ps, r[1], g[1], tg[1], n),
                    _dcf(fcf_ps, r[0], g[2], tg[2], n))
            grid = {f"r={rr:.4f}": {f"tg={t:.4f}": _dcf(fcf_ps, rr, g[1], t, n) for t in tg} for rr in r}
            note = ("free cash flow per share discounted; net debt is not deducted (stated); "
                    "model value under the stated assumptions, not a forecast or target")
        else:  # justified_pb for banks
            miss = _need(i, ("profit_after_tax", "total_equity", "shares"))
            if miss:
                out.append(_res(method, "insufficient_data", missing=miss, assumptions=aa))
                continue
            roe = _v(i, "profit_after_tax") / _v(i, "total_equity")
            bvps = _v(i, "total_equity") / i["shares"]
            r, g = aa["cost_of_equity"], aa["sustainable_growth"]

            def jpb(rr, gg, roe=roe, bvps=bvps):
                return None if rr <= gg else (roe - gg) / (rr - gg) * bvps
            vals = (jpb(r[2], g[0]), jpb(r[1], g[1]), jpb(r[0], g[2]))
            grid = {f"r={rr:.4f}": {f"g={gg:.4f}": jpb(rr, gg) for gg in g} for rr in r}
        if any(v is None for v in vals):
            out.append(_res(method, "not_applicable", assumptions=aa,
                            note="discount rate must exceed growth in every case"))
            continue
        out.append(_res(method, "ok", cons=vals[0], base=vals[1], opt=vals[2], assumptions=aa,
                        sensitivity=grid, note=note))
    return out


def value(db, company_id: str, *, as_of: str, assumptions: dict | None = None, store: bool = True) -> dict:
    i = inputs(db, company_id, as_of=as_of)
    results = multiples(i) + models(i, assumptions)
    if store:
        for r in results:
            db.execute(
                "INSERT INTO valuations(company_id, as_of_date, method, state, inputs_json, "
                "assumptions_json, "
                "conservative, base, optimistic, sensitivity_json, missing_json, engine_version, "
                "created_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (company_id, as_of, r["method"], r["state"],
                 json.dumps({**r["inputs"], "price_date": i["price_date"],
                             "fy_period_end": i["fy_period_end"],
                             "scope": i["scope"], "note": r["note"]}),
                 json.dumps(r["assumptions"]), r["conservative"] if r["state"] == "ok" else None,
                 r["base"] if r["state"] == "ok" else None, r["optimistic"] if r["state"] == "ok" else None,
                 json.dumps(r["sensitivity"]) if r["sensitivity"] else None, json.dumps(r["missing"]),
                 ENGINE_VERSION, _now()))
    return {"company_id": company_id, "as_of": as_of,
            "inputs": {k: v for k, v in i.items() if k != "metrics"},
            "results": results,
            "disclaimer": "Descriptive multiples and assumption-driven model values; not advice or price "
                          "targets."}
