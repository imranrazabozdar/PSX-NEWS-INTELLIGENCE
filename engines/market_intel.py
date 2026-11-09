"""Market intelligence (master plan M4; architecture §3D). SCS daily bars stored in this project only.

* Corporate-action adjustment: bonus, split, consolidation and rights (theoretical ex-rights price) from
  `corporate_actions` (status not 'cancelled'). Cash dividends do not adjust the price-return series; they
  are listed separately. A series is labelled `adjusted` only when every stored action could be applied;
  otherwise it is `unadjusted` with the reason (for example a rights issue with no cum-rights close).
* Descriptive measures only: returns over 1 / 20 / 60 sessions, annualised volatility (60 sessions, 250
  sessions a year), maximum drawdown over the stored window, and liquidity from engines.universe. Each needs
  enough consecutive stored sessions or it is `insufficient_data`; gaps are never filled.
* Benchmark-relative returns need an approved benchmark series (U5). None is configured, so they are
  `not_evaluable`. A price move is never interpreted as a change in fundamentals.
Nothing here is imported from, or exchanged with, any other project.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from engines import universe

ENGINE_VERSION = "market_intel/1"
SOURCE_ID = "scs_chart"
BENCHMARK_SYMBOL: str | None = None  # U5: owner decision; nothing is assumed
TRADING_DAYS_PER_YEAR = 250


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def import_corporate_action(db, rec: dict, *, importer: str, source_note: str) -> int:
    """Record an owner-supplied corporate action with its source document (append-only)."""
    from database import repositories as repo

    comp = db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                      "AND valid_to IS NULL", (rec["ticker"],))
    if not comp:
        raise ValueError(f"ticker {rec['ticker']!r} not in the company master")
    item = repo.record_source_item(
        db, source_id="company_reports_manual", collected_at_utc=_now(), url=rec.get("source_url"),
        external_id=f"ca:{rec['ticker']}:{rec['action_type']}:{rec['ex_date']}",
        content=json.dumps(rec, sort_keys=True),
        title=f"{rec['ticker']} {rec['action_type']} ex {rec['ex_date']}",
        provenance={"retrieval_method": "manual", "source_metadata_json": json.dumps(
            {"importer": importer, "source_note": source_note})})
    db.execute(
        "INSERT INTO corporate_actions(company_id, action_type, ex_date, record_date, ratio, "
        "amount_per_share, "
        "subscription_price, currency, source_item_id, status, recorded_at_utc) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        (comp[0]["company_id"], rec["action_type"], rec["ex_date"], rec.get("record_date"), rec.get("ratio"),
         rec.get("amount_per_share"), rec.get("subscription_price"), rec.get("currency", "PKR"),
         item.source_item_id, rec.get("status", "announced"), _now()))
    return item.source_item_id


def _company(db, symbol: str) -> str | None:
    r = db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                   "AND valid_to IS NULL", (symbol,))
    return r[0]["company_id"] if r else None


def daily_closes(db, symbol: str, *, as_of: str) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT session_date_pkt AS d, close, volume FROM market_bars_current WHERE source_id = ? AND "
        "symbol = ? "
        "AND timeframe = '1d' AND session_date_pkt <= ? ORDER BY session_date_pkt",
        (SOURCE_ID, symbol, as_of))]


def adjusted_series(db, symbol: str, *, as_of: str) -> dict:
    bars = daily_closes(db, symbol, as_of=as_of)
    cid = _company(db, symbol)
    actions = db.execute(
        "SELECT action_type, ex_date, ratio, amount_per_share, subscription_price FROM corporate_actions "
        "WHERE company_id = ? AND status <> 'cancelled' AND ex_date <= ? ORDER BY ex_date",
        (cid, as_of)) if cid else []
    factors: list[tuple[str, float, str]] = []
    problems, dividends = [], []
    for a in actions:
        t = a["action_type"]
        if t == "cash_dividend":
            dividends.append({"ex_date": a["ex_date"], "amount_per_share": a["amount_per_share"]})
            continue
        if t == "bonus":
            factors.append((a["ex_date"], 1 / (1 + a["ratio"]), f"bonus {a['ratio']}:1"))
        elif t in ("split", "consolidation"):
            factors.append((a["ex_date"], 1 / a["ratio"], f"{t} x{a['ratio']}"))
        elif t == "rights":
            cum = [b for b in bars if b["d"] < a["ex_date"]]
            if not cum:
                problems.append(f"rights {a['ex_date']}: no stored cum-rights close")
                continue
            p, r, s = cum[-1]["close"], a["ratio"], a["subscription_price"]
            terp = (p + r * s) / (1 + r)
            factors.append((a["ex_date"], terp / p, f"rights {r}:1 at {s} (TERP {terp:.4f})"))
    out = []
    for b in bars:
        f = math.prod(x for ex, x, _ in factors if b["d"] < ex)
        out.append({**b, "adj_close": b["close"] * f, "factor": f})
    state = "unadjusted" if problems else ("adjusted" if factors else "no_actions")
    return {"symbol": symbol, "state": state, "bars": out, "applied": [(ex, f, w) for ex, f, w in factors],
            "problems": problems, "cash_dividends_not_in_price_series": dividends}


def _ret(series: list[float], n: int) -> dict:
    if len(series) < n + 1:
        return {"state": "insufficient_data", "sessions": len(series), "required": n + 1}
    return {"state": "ok", "value": series[-1] / series[-n - 1] - 1}


def measures(db, symbol: str, *, as_of: str) -> dict:
    s = adjusted_series(db, symbol, as_of=as_of)
    window = universe.window(db, as_of=as_of, source_id=SOURCE_ID)
    have = {b["d"] for b in s["bars"]}
    # consecutive market sessions ending at the latest market session that the symbol traded in all
    sessions = [r["d"] for r in db.execute(
        "SELECT DISTINCT session_date_pkt AS d FROM market_bars WHERE source_id = ? AND timeframe = '1d' "
        "AND session_date_pkt <= ? ORDER BY session_date_pkt DESC LIMIT 400", (SOURCE_ID, as_of))]
    run = []
    for d in sessions:
        if d not in have:
            break
        run.append(d)
    by_d = {b["d"]: b for b in s["bars"]}
    closes = [by_d[d]["adj_close"] for d in reversed(run)]
    out = {"symbol": symbol, "as_of": as_of, "series_state": s["state"], "adjustment_problems": s["problems"],
           "consecutive_sessions": len(closes),
           "return_1d": _ret(closes, 1), "return_20s": _ret(closes, 20), "return_60s": _ret(closes, 60)}
    if len(closes) >= 61:
        lr = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 60, len(closes))]
        mu = sum(lr) / len(lr)
        sd = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1))
        out["volatility_60s_annualised"] = {"state": "ok", "value": sd * math.sqrt(TRADING_DAYS_PER_YEAR)}
    else:
        out["volatility_60s_annualised"] = {"state": "insufficient_data", "sessions": len(closes),
                                            "required": 61}
    if len(closes) >= 2:
        peak, mdd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1)
        out["max_drawdown"] = {"state": "ok", "value": mdd, "sessions": len(closes)}
    else:
        out["max_drawdown"] = {"state": "insufficient_data"}
    out["relative_to_benchmark"] = {"state": "not_evaluable",
                                    "reason": "no approved benchmark series (owner decision U5)"}
    liq = universe.liquidity(db, symbol, as_of=as_of, source_id=SOURCE_ID, sessions=window)
    out["liquidity"] = {"state": liq.state, "adv_shares": liq.adv_shares,
                        "avg_traded_value_pkr_approx": liq.avg_traded_value_pkr_approx,
                        "reasons": liq.reasons}
    if s["state"] == "unadjusted":
        for k in ("return_20s", "return_60s", "max_drawdown", "volatility_60s_annualised"):
            out[k]["warning"] = "series not fully adjusted for corporate actions"
    return out


def assess(db, symbol: str, *, as_of: str) -> dict:
    """Write dimensions I (price behaviour, descriptive) and J (liquidity) for a listed company."""
    cid = _company(db, symbol)
    if cid is None:
        return {"symbol": symbol, "state": "not_in_company_master"}
    m = measures(db, symbol, as_of=as_of)
    i_items = [m["return_20s"], m["return_60s"], m["volatility_60s_annualised"], m["max_drawdown"]]
    i_state = "ok" if all(x["state"] == "ok" for x in i_items) else (
        "partial" if any(x["state"] == "ok" for x in i_items) else "insufficient_data")
    j_state = {"qualified": "ok", "below_threshold": "ok"}.get(m["liquidity"]["state"], "insufficient_data")
    for dim, st, comp in (("I", i_state, {k: m[k] for k in ("return_1d", "return_20s", "return_60s",
                                                              "volatility_60s_annualised", "max_drawdown",
                                                              "relative_to_benchmark")}),
                          ("J", j_state, m["liquidity"])):
        db.execute(
            "INSERT INTO dimension_assessments(company_id, dimension, as_of_date, period_end, scope, "
            "data_state, "
            "band, components_json, evidence_json, engine_version, created_at_utc) "
            "VALUES (?,?,?,NULL,NULL,?,NULL,?,?,?,?) ON CONFLICT DO NOTHING",
            (cid, dim, as_of, st, json.dumps(comp), json.dumps(
                {"series_state": m["series_state"], "source": SOURCE_ID,
                 "note": "descriptive market behaviour; not evidence about fundamentals"}),
             ENGINE_VERSION, _now()))
    return m
