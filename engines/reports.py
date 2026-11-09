"""Integrated research reports and reproducible snapshots (master plan M9).

`company_report` assembles 13 sections from STORED results only: Stage 2 event / exposure / impact
(engines.research), fundamentals (M3), valuation (M5), market behaviour (M4) and macro drivers (M6). A
section whose module has no data says so (`not_processed` / `data_unavailable`) instead of being omitted.

Reproducibility: `snapshot` canonicalises the report (sorted keys, no generation timestamp in the hashed
body), stores it with its engine versions and SHA-256, and `verify_snapshot` rebuilds it from the same stored
inputs and compares hashes.

The report separates reporting, official confirmation, corroboration, rumour, opinion, prediction, inference
and scenario through the states its inputs carry. It contains no buy/sell recommendations and no price
targets; model values appear only as assumption-driven ranges.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from engines import fundamentals, macro, market_intel, research, valuation

VERSIONS = {"report": "reports/1", "fundamentals": fundamentals.ENGINE_VERSION,
            "valuation": valuation.ENGINE_VERSION, "market_intel": market_intel.ENGINE_VERSION}
SECTIONS = ("executive_summary", "news_and_events", "source_quality", "company_exposure",
            "fundamental_performance", "financial_strength_and_cash_flow", "valuation", "macro_and_sector",
            "market_behaviour_and_liquidity", "scenarios", "risks_catalysts_invalidation",
            "confidence_and_missing_data", "references")
DISCLAIMER = ("Research support only. Not investment advice; no buy/sell recommendation or price target. "
              "Scenarios are conditional, not forecasts.")


def _latest_fy(db, company_id: str, as_of: str) -> str | None:
    """Latest fiscal year known on `as_of`: period ended and, where recorded, filed by then (as valuation)."""
    return db.execute(
        "SELECT MAX(m.period_end) AS p FROM financial_metrics m LEFT JOIN financial_reports r "
        "USING(report_id) "
        "WHERE m.company_id = ? AND m.period_type = 'FY' AND m.period_end <= ? AND "
        "(r.filed_at_utc IS NULL OR substr(r.filed_at_utc, 1, 10) <= ?)", (company_id, as_of, as_of))[0]["p"]


def _filing_unknown(db, company_id: str, period_end: str) -> bool:
    return bool(db.execute("SELECT 1 FROM financial_metrics m LEFT JOIN financial_reports r USING(report_id) "
                           "WHERE m.company_id = ? AND m.period_end = ? AND m.period_type = 'FY' AND "
                           "r.filed_at_utc IS NULL LIMIT 1", (company_id, period_end)))


def _ticker(db, company_id: str) -> str | None:
    r = db.execute("SELECT value FROM company_identifiers WHERE company_id = ? AND id_type = 'psx_ticker' "
                   "AND valid_to IS NULL", (company_id,))
    return r[0]["value"] if r else None


def _stored_valuations(db, company_id: str, as_of: str) -> list[dict]:
    rows = db.execute("SELECT method, state, conservative, base, optimistic, missing_json, inputs_json, "
                      "assumptions_json FROM valuations WHERE company_id = ? AND as_of_date = ? "
                      "ORDER BY method", (company_id, as_of))
    return [{**dict(r), "missing": json.loads(r["missing_json"]), "inputs": json.loads(r["inputs_json"]),
             "assumptions": json.loads(r["assumptions_json"])} for r in rows]


def company_report(db, company_id: str, *, as_of: str) -> dict | None:
    base = research.company_report(db, company_id)
    if base is None:
        return None
    t = _ticker(db, company_id)
    fy = _latest_fy(db, company_id, as_of)
    fa = fundamentals.analyse(db, company_id, period_end=fy, as_of=as_of) if fy else None
    vals = _stored_valuations(db, company_id, as_of)
    mkt = market_intel.measures(db, t, as_of=as_of) if t else None
    mechs = sorted({m for m in base.get("impact_by_mechanism", {})})
    window_start = f"{int(as_of[:4]) - 1}{as_of[4:]}"
    drivers = {m: macro.driver_changes(db, m, start=window_start, end=as_of) for m in mechs}
    impacts = [a for rows in base.get("impact_by_mechanism", {}).values() for a in rows]
    missing = []
    if fa is None:
        missing.append("financial statements: no reported fiscal-year metrics imported")
    elif _filing_unknown(db, company_id, fy):
        missing.append(f"filing date of the FY{fy[:4]} report not recorded: assumed known from its "
                       "period end (possible look-ahead for past as-of dates)")
    if not vals:
        missing.append("valuation: not run for this as-of date")
    if mkt is None or mkt["consecutive_sessions"] == 0:
        missing.append("market data: no stored daily bars")
    if not any(d for d in drivers.values()):
        missing.append("macro: no series observations linked to this company's mechanisms")
    ratios = (fa or {}).get("ratios", {})
    a_names = fundamentals.DIMENSIONS["A"]
    b_names = fundamentals.DIMENSIONS["B"]
    ok_vals = [v for v in vals if v["state"] == "ok"]
    scen = {
        "valuation_ranges": [{"method": v["method"], "adverse": v["conservative"], "base": v["base"],
                              "bull": v["optimistic"], "assumptions": v["assumptions"]}
                             for v in ok_vals if v["conservative"] is not None],
        "event_scenarios": base.get("scenarios", {}),
        "note": "bull / base / adverse are conditional on the stated assumptions and event scenarios",
    }
    body = {
        "company": base["company"], "ticker": t, "as_of": as_of, "disclaimer": DISCLAIMER,
        "executive_summary": {
            "events": base["executive_summary"],
            "fundamentals": {"period_end": fy, "framework": (fa or {}).get("framework"),
                             "ok_ratios": sum(1 for r in ratios.values() if r["state"] == "ok"),
                             "state": "ok" if fa else "data_unavailable"},
            "valuation_methods_ok": [v["method"] for v in ok_vals],
            "liquidity": (mkt or {}).get("liquidity", {}).get("state", "no_market_data"),
            "note": "facts, interpretations and scenarios are listed separately below",
        },
        "news_and_events": {"latest": base["latest_developments"],
                            "company_specific": base["company_specific_news"],
                            "sector": base["sector_developments"]},
        "source_quality": {"evidence_basis": base["limitations"]["evidence_basis"],
                           "evidence": base["evidence_references"],
                           "note": "repeated reports of one original count once; X posts are claims, never "
                                   "independent corroboration"},
        "company_exposure": base["exposure"],
        "fundamental_performance": ({"state": "ok", **{k: ratios[k] for k in a_names if k in ratios},
                                     "growth": fa["growth"]} if fa else {"state": "data_unavailable"}),
        "financial_strength_and_cash_flow": ({"state": "ok",
                                              **{k: ratios[k] for k in b_names if k in ratios},
                                              "fcf": fa["fcf"]} if fa else {"state": "data_unavailable"}),
        "valuation": {"state": "ok" if vals else "not_processed", "methods": vals,
                      "consensus": "not available (U6)"},
        "macro_and_sector": {"mechanisms": mechs, "driver_changes": drivers,
                             "macro_exposure": base["macro_geopolitical_exposure"]},
        "market_behaviour_and_liquidity": mkt or {"state": "no_market_data"},
        "scenarios": scen,
        "risks_catalysts_invalidation": {"risks_and_invalidation": base["risks_and_invalidation"],
                                         "impact_count": len(impacts),
                                         "fundamental_vs_sentiment": "price moves are reported as market "
                                         "behaviour only and are not treated as evidence about fundamentals"},
        "confidence_and_missing_data": {"missing": missing, "limitations": base["limitations"]},
        "references": {"evidence": base["evidence_references"],
                       "financial_metrics": sorted({
                           i["metric_id"] for r in ratios.values()
                           for i in r.get("inputs", {}).values() if "metric_id" in i}),
                       "engine_versions": VERSIONS},
    }
    if any(s not in body for s in SECTIONS):  # programming error: a section was dropped
        raise RuntimeError("report is missing a section")
    return body


def _canonical(body: dict) -> str:
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in ("generated_at_utc",)}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return json.dumps(strip(body), sort_keys=True, ensure_ascii=False, default=str)


def snapshot(db, company_id: str, *, as_of: str) -> dict:
    body = company_report(db, company_id, as_of=as_of)
    if body is None:
        raise ValueError("unknown company")
    text = _canonical(body)
    sha = hashlib.sha256(text.encode()).hexdigest()
    db.execute("INSERT INTO report_snapshots(kind, subject, as_of_date, generated_at_utc, "
               "input_versions_json, "
               "content_sha256, body_json) VALUES ('company',?,?,?,?,?,?) ON CONFLICT DO NOTHING",
               (company_id, as_of, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(VERSIONS),
                sha, text))
    return {"subject": company_id, "as_of": as_of, "sha256": sha}


def verify_snapshot(db, company_id: str, *, as_of: str) -> dict:
    stored = db.execute("SELECT content_sha256 FROM report_snapshots WHERE kind = 'company' AND subject = ? "
                        "AND "
                        "as_of_date = ? ORDER BY snapshot_id DESC LIMIT 1", (company_id, as_of))
    if not stored:
        return {"state": "no_snapshot"}
    now = hashlib.sha256(_canonical(company_report(db, company_id, as_of=as_of)).encode()).hexdigest()
    return {"state": "reproduced" if now == stored[0]["content_sha256"] else "inputs_changed",
            "stored": stored[0]["content_sha256"], "rebuilt": now}


def sector_view(db, sector_name: str, *, as_of: str) -> dict:
    rows = db.execute(
        "SELECT c.company_id, ci.value AS ticker FROM companies c JOIN company_classifications cc "
        "USING(company_id) "
        "JOIN sectors s USING(sector_id) JOIN company_identifiers ci ON ci.company_id = c.company_id AND "
        "ci.id_type = 'psx_ticker' AND ci.valid_to IS NULL WHERE s.name = ? AND cc.valid_to IS NULL "
        "ORDER BY ci.value", (sector_name,))
    out = []
    for r in rows:
        dims = {d["dimension"]: d["data_state"] for d in db.execute(
            "SELECT dimension, data_state FROM dimension_assessments WHERE company_id = ? AND as_of_date <= "
            "? "
            "ORDER BY as_of_date", (r["company_id"], as_of))}
        out.append({"ticker": r["ticker"], "dimensions": dims or "not_processed"})
    return {"sector": sector_name, "as_of": as_of, "companies": out,
            "note": "dimension states per company; no sector score is computed (no validated composite)"}


def market_view(db, *, as_of: str) -> dict:
    from engines import universe

    u = universe.universe(db, as_of=as_of)
    counts: dict[str, int] = {}
    for r in u:
        counts[r["liquidity_state"]] = counts.get(r["liquidity_state"], 0) + 1
    macro_events = research.events_page(db, macro_only=True, limit=10)
    return {"as_of": as_of, "universe_size": len(u), "priority_count": sum(r["priority"] for r in u),
            "liquidity_states": counts, "macro_events": macro_events,
            "benchmark": "not_evaluable (U5)", "disclaimer": DISCLAIMER}


def report_markdown(body: dict) -> str:
    name = body["company"].get("legal_name", body["ticker"])
    lines = [f"# {name} ({body['ticker']}) — as of {body['as_of']}",
             "", f"_{body['disclaimer']}_", ""]
    for s in SECTIONS:
        lines += [f"## {s.replace('_', ' ').capitalize()}", "", "```json",
                  json.dumps(body[s], indent=1, ensure_ascii=False, default=str)[:4000], "```", ""]
    return "\n".join(lines)
