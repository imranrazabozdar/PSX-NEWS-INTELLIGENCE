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


def _share_factor(db, company_id: str, after: str, until: str) -> tuple[float, list[str]]:
    """Share-count multiplier from bonus / split / consolidation with ex-date in (after, until]."""
    f, notes = 1.0, []
    for a in db.execute("SELECT action_type, ex_date, ratio FROM corporate_actions WHERE company_id = ? AND "
                        "status <> 'cancelled' AND ex_date > ? AND ex_date <= ? ORDER BY ex_date",
                        (company_id, after, until)):
        if a["action_type"] == "bonus":
            f *= 1 + a["ratio"]
        elif a["action_type"] in ("split", "consolidation"):
            f *= a["ratio"]
        elif a["action_type"] == "rights":
            notes.append(f"rights issue {a['ex_date']}: per-share inputs not adjusted for it")
    return f, notes


def inputs(db, company_id: str, *, as_of: str, strict_point_in_time: bool = False) -> dict:
    """Valuation inputs known on `as_of`.

    A report counts only if its period ended on or before `as_of` and, where its filing date is recorded,
    it was filed by then. With `strict_point_in_time` (backtests), a report with NO recorded filing date is
    excluded; otherwise it is used and flagged, because a period end is not a publication date.
    Per-share inputs are restated for bonus / split / consolidation between the period end and the price
    date, so price and per-share figures refer to the same share count.
    """
    t = _ticker(db, company_id)
    px = db.execute("SELECT session_date_pkt, close FROM market_bars_current WHERE source_id = 'scs_chart' "
                    "AND symbol = ? AND timeframe = '1d' AND session_date_pkt <= ? "
                    "ORDER BY session_date_pkt DESC LIMIT 1", (t, as_of)) if t else []
    # a report counts when filed by as_of; one with no filing date counts only outside strict mode
    strict = int(strict_point_in_time)
    fy = db.execute(
        "SELECT m.period_end, m.scope FROM financial_metrics m LEFT JOIN financial_reports r "
        "USING(report_id) "
        "WHERE m.company_id = ? AND m.period_type = 'FY' AND m.period_end <= ? AND m.basis IN "
        "('reported','restated') AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
        "AND substr(r.filed_at_utc, 1, 10) <= ?)) "
        "ORDER BY m.period_end DESC, CASE m.scope WHEN 'consolidated' THEN 0 ELSE 1 END LIMIT 1",
        (company_id, as_of, strict, as_of))
    m: dict[str, dict] = {}
    filing_known = True
    if fy:
        for r in db.execute(
            "SELECT m.metric_id, m.metric, m.value, m.basis, r.filed_at_utc FROM financial_metrics m "
            "LEFT JOIN financial_reports r USING(report_id) WHERE m.company_id = ? AND m.period_type = 'FY' "
            "AND m.period_end = ? AND m.scope = ? AND m.basis IN ('reported','restated') "
            "AND ((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL "
            "AND substr(r.filed_at_utc, 1, 10) <= ?)) "
            "ORDER BY CASE m.basis WHEN 'restated' THEN 0 ELSE 1 END, m.metric_id DESC",
                (company_id, fy[0]["period_end"], fy[0]["scope"], strict, as_of)):
            if r["metric"] not in m:
                m[r["metric"]] = dict(r)
                filing_known = filing_known and r["filed_at_utc"] is not None
    notes = []
    if fy and not filing_known:
        notes.append("filing date not recorded: the report is assumed known from its period end "
                     "(possible look-ahead; use strict_point_in_time for backtests)")
    factor = 1.0
    if fy and px:
        factor, extra = _share_factor(db, company_id, fy[0]["period_end"], px[0]["session_date_pkt"])
        notes += extra
        if factor != 1.0:
            notes.append(f"per-share inputs restated for a share-count change of x{factor:g} after the "
                         "period end")
            m = {k: (dict(v, value=v["value"] / factor) if k == "eps_basic" else v) for k, v in m.items()}
    shares, shares_basis = None, None
    if "shares_outstanding" in m:
        shares, shares_basis = m["shares_outstanding"]["value"] * factor, "reported"
    elif "profit_after_tax" in m and m.get("eps_basic", {}).get("value"):
        shares = m["profit_after_tax"]["value"] / m["eps_basic"]["value"]  # eps already restated
        shares_basis = "derived: profit_after_tax / eps_basic (weighted average, approximate)"
    start = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
    divs = db.execute("SELECT ex_date, amount_per_share FROM corporate_actions WHERE company_id = ? AND "
                      "action_type = 'cash_dividend' AND status <> 'cancelled' AND ex_date > ? AND ex_date "
                      "<= ?",
                      (company_id, start, as_of))
    until = px[0]["session_date_pkt"] if px else as_of
    dps = sum(d["amount_per_share"] / _share_factor(db, company_id, d["ex_date"], until)[0] for d in divs)
    return {"ticker": t, "price": px[0]["close"] if px else None,
            "price_date": px[0]["session_date_pkt"] if px else None,
            "fy_period_end": fy[0]["period_end"] if fy else None, "scope": fy[0]["scope"] if fy else None,
            "metrics": m, "shares": shares, "shares_basis": shares_basis, "share_factor": factor,
            "dps_ttm": dps if divs else None, "framework": framework_for(db, company_id),
            "filing_date_known": filing_known if fy else None, "notes": notes}


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
                         "long_term_borrowings", "short_term_borrowings", "cash_and_equivalents"))
        if miss:
            out.append(_res("ev_ebitda", "insufficient_data", missing=miss))
        else:
            debt = _v(i, "long_term_borrowings") + _v(i, "short_term_borrowings")  # both reported
            ev = i["price"] * i["shares"] + debt - _v(i, "cash_and_equivalents")
            ebitda = _v(i, "operating_profit") + abs(_v(i, "depreciation_amortisation"))
            note = None
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


def value(db, company_id: str, *, as_of: str, assumptions: dict | None = None, store: bool = True,
          strict_point_in_time: bool = False) -> dict:
    """Run every method; with `store`, write the valuations rows and dimension D (no band, U9)."""
    i = inputs(db, company_id, as_of=as_of, strict_point_in_time=strict_point_in_time)
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
                             "scope": i["scope"], "note": r["note"], "input_notes": i["notes"],
                             "filing_date_known": i["filing_date_known"]}),
                 json.dumps(r["assumptions"]), r["conservative"] if r["state"] == "ok" else None,
                 r["base"] if r["state"] == "ok" else None, r["optimistic"] if r["state"] == "ok" else None,
                 json.dumps(r["sensitivity"]) if r["sensitivity"] else None, json.dumps(r["missing"]),
                 ENGINE_VERSION, _now()))
        ok = [r for r in results if r["state"] == "ok"]
        applicable = [r for r in results if r["state"] != "not_applicable"]
        d_state = ("not_applicable" if not applicable else "ok" if len(ok) == len(applicable)
                   else "partial" if ok else "insufficient_data")
        db.execute(
            "INSERT INTO dimension_assessments(company_id, dimension, as_of_date, period_end, scope, "
            "data_state, "
            "band, components_json, evidence_json, engine_version, created_at_utc) "
            "VALUES (?,'D',?,?,?,?,NULL,?,?,?,?) ON CONFLICT DO NOTHING",
            (company_id, as_of, i["fy_period_end"], i["scope"], d_state,
             json.dumps([{k: r[k] for k in ("method", "state", "conservative", "base", "optimistic",
                                            "missing")} for r in results]),
             json.dumps({"price_date": i["price_date"], "notes": i["notes"],
                         "band_note": "no band: valuation judgements need owner thresholds (U9)"}),
             ENGINE_VERSION, _now()))
    return {"company_id": company_id, "as_of": as_of,
            "inputs": {k: v for k, v in i.items() if k != "metrics"},
            "results": results,
            "disclaimer": "Descriptive multiples and assumption-driven model values; not advice or price "
                          "targets."}
