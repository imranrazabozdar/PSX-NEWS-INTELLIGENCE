"""Ranked "setups": the stocks whose measured evidence on file scores highest. Deterministic, no model.

Three rankings, each a top 10:
  * technical    : price trend, position in the recent range, volume, and the technical engine's own
                   Wyckoff / chart-pattern heuristic scores (read through the ADR-0008 link);
  * fundamental  : profitability, valuation, dividend, leverage and the like-for-like EPS change;
  * combined     : both pillars, equal weight, and a stock needs both.

What these are not: forecasts, probabilities or instructions. Every item is an equal-weight, uncalibrated
step score over measured values; an item that is not on file is left out of that stock's score and shown as
unknown, never counted as zero. Stocks are skipped when they are too thinly traded or priced too low to
matter, and when a fundamental value is an artefact (negative equity, negative earnings, a tiny-equity ROE).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from engines import company_names, materiality
from scripts.build_radar import FACT_COLS, event_date

MIN_TURNOVER = 25e6  # rupees traded per day, 20-session average
MIN_PRICE = 10.0
MIN_SESSIONS = 25
MIN_FUND_POINTS = 25  # of the 50 possible, so a score never rests on one number
MIN_TECH_POINTS = 30
TOP = 10
FUND_ITEMS = (
    ("profitability", 10),
    ("valuation_pe", 10),
    ("valuation_pb", 5),
    ("dividend", 10),
    ("leverage", 5),
    ("eps_trend", 10),
    ("announcement", 10),
    ("news", 5),
    ("corporate", 5),
)
TECH_ITEMS = (("trend20", 10), ("range_pos", 10), ("volume", 10), ("wyckoff", 10), ("pattern", 10))
LABELS = {
    "profitability": "return on equity",
    "valuation_pe": "price/earnings",
    "valuation_pb": "price/book",
    "dividend": "dividend yield",
    "leverage": "debt/equity",
    "eps_trend": "EPS change",
    "announcement": "a recent material announcement",
    "news": "unusual recent news flow",
    "corporate": "a recent corporate action",
    "trend20": "20-session price change",
    "range_pos": "position in the recent range",
    "volume": "volume against usual",
    "wyckoff": "technical engine accumulation score",
    "pattern": "technical engine pattern confidence",
}


def _latest(facts: list[dict[str, Any]], topic: str, since: str | None = None) -> dict[str, Any] | None:
    rows = [
        f
        for f in facts
        if f["topic"] == topic and f.get("value") is not None and (since is None or f["source_date"] >= since)
    ]
    return max(rows, key=lambda f: f["source_date"]) if rows else None


def _num(f: dict[str, Any] | None) -> float | None:
    try:
        return None if f is None else float(f["value"])
    except (TypeError, ValueError):
        return None


EVENT_MAX = {"announcement": 25.0, "news": 15.0, "corporate": 20.0}  # the radar's own caps per kind
EVENT_POINTS = {"announcement": 10.0, "news": 5.0, "corporate": 5.0}


def event_items(drivers: list[dict[str, Any]]) -> tuple[dict[str, float | None], dict[str, str]]:
    """Announcements, news flow and corporate actions the company radar already graded (size, stage and
    recency are in its points). Only what IS on file counts; no event leaves the item unknown, not zero."""
    pts: dict[str, float | None] = {}
    text: dict[str, str] = {}
    for kind, cap in EVENT_MAX.items():
        best = max((d for d in drivers if d["kind"] == kind), key=lambda d: d["points"], default=None)
        if best is None:
            pts[kind], text[kind] = None, ""
            continue
        pts[kind] = min(EVENT_POINTS[kind], best["points"] / cap * EVENT_POINTS[kind])
        text[kind] = f"{kind} ({best['date']}): {best['text'][:140]}"
    return pts, text


def fundamental_items(facts: list[dict[str, Any]]) -> tuple[dict[str, float | None], dict[str, str], bool]:
    """(points per item or None, the evidence text per item, usable). `usable` is False when a value on file
    is an artefact that must not be scored."""
    g = {
        k: _num(_latest(facts, f"fundamentals.{k}"))
        for k in ("return_on_equity", "annual_p_e", "price_book", "dividend_yield", "debt_equity")
    }
    roe, pe, pb, dy, de = (
        g[k] for k in ("return_on_equity", "annual_p_e", "price_book", "dividend_yield", "debt_equity")
    )
    if (
        (pb is not None and (pb <= 0 or pb > 8))
        or (pe is not None and pe <= 0)
        or (roe is not None and (roe <= 0 or roe > 60))
        or (de is not None and de < 0)
    ):
        return {}, {}, False
    change, _ = materiality.eps_pair(facts)
    if change and change.get("pct") is not None and abs(change["pct"]) > 300:
        change = None  # a jump off a tiny base is not scored
    pts: dict[str, float | None] = {
        "profitability": None if roe is None else max(0.0, min(10.0, roe / 3)),
        "valuation_pe": None if pe is None else max(0.0, (12 - pe) / 12 * 10),
        "valuation_pb": None if pb is None else max(0.0, (1.5 - pb) / 1.5 * 5),
        "dividend": None if dy is None else max(0.0, min(10.0, dy)),
        "leverage": None if de is None else (5.0 if de <= 100 else 2.5 if de <= 200 else 0.0),
        "eps_trend": None
        if not change or change.get("pct") is None
        else max(-10.0, min(10.0, change["pct"] / 3)),
    }
    text = {
        "profitability": "" if roe is None else f"return on equity {roe:.1f}%",
        "valuation_pe": "" if pe is None else f"price/earnings {pe:.1f}",
        "valuation_pb": "" if pb is None else f"price/book {pb:.2f}",
        "dividend": "" if dy is None else f"dividend yield {dy:.1f}%",
        "leverage": "" if de is None else f"debt/equity {de:.0f}%",
        "eps_trend": ""
        if not change or change.get("pct") is None
        else f"EPS {change['label']}: {change['pct']:+.0f}%",
    }
    return pts, text, True


def technical_items(
    bars: list[dict[str, Any]], facts: list[dict[str, Any]], today: date
) -> tuple[dict[str, float | None], dict[str, str]]:
    b = sorted(bars, key=lambda x: x["trade_date"])
    cl = [float(x["close"]) for x in b]
    vo = [float(x["volume"]) for x in b]
    ret20 = (cl[-1] / cl[-21] - 1) * 100
    lo, hi = min(cl), max(cl)
    pos = (cl[-1] - lo) / (hi - lo) if hi > lo else 0.5
    v5, v20 = statistics.fmean(vo[-5:]), statistics.fmean(vo[-25:-5])
    vr = v5 / v20 if v20 > 0 else None
    since = (today - timedelta(days=14)).isoformat()
    wy = _latest(facts, "technical.wyckoff", since)
    pat = _latest(facts, "technical.pattern", since)
    wscore, pconf = _num(wy), _num(pat)
    pts: dict[str, float | None] = {
        "trend20": max(0.0, min(10.0, ret20 / 1.5)),
        "range_pos": 10 * max(0.0, (pos - 0.5) * 2),
        "volume": None if vr is None else max(0.0, min(10.0, (vr - 1) * 10)),
        "wyckoff": None if wscore is None else wscore / 10,
        "pattern": None if pconf is None else max(0.0, min(10.0, pconf * 10)),
    }
    text = {
        "trend20": f"price {ret20:+.1f}% over 20 sessions",
        "range_pos": f"at {pos * 100:.0f}% of its range over the last few weeks",
        "volume": "" if vr is None else f"5-day volume {vr:.1f}x the prior 20 sessions",
        "wyckoff": ""
        if wy is None
        else f"engine accumulation score {wscore:.0f}/100 (scan {wy['source_date']})",
        "pattern": ""
        if pat is None
        else f"engine pattern confidence {pconf:.2f} (signal {pat['source_date']})",
    }
    return pts, text


def pillar(pts: dict[str, float | None], items: tuple[tuple[str, int], ...], floor: int) -> float | None:
    """0-100 over the items that are measured; None when too little is measured."""
    measured = [(k, m) for k, m in items if pts.get(k) is not None]
    maximum = sum(m for _k, m in measured)
    if maximum < floor:
        return None
    return round(max(0.0, sum(pts[k] for k, _m in measured)) / maximum * 100, 1)  # type: ignore[misc]


def unknown_items(pts: dict[str, float | None], items: tuple[tuple[str, int], ...]) -> list[str]:
    return [LABELS[k] for k, _m in items if pts.get(k) is None]


def eligible(bars: list[dict[str, Any]]) -> bool:
    if len(bars) < MIN_SESSIONS:
        return False
    b = sorted(bars, key=lambda x: x["trade_date"])
    turnover = statistics.fmean(float(x["close"]) * float(x["volume"]) for x in b[-20:])
    return turnover >= MIN_TURNOVER and float(b[-1]["close"]) >= MIN_PRICE


def score_symbol(
    sym: str,
    bars: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    today: date,
    sector: str | None,
    drivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not eligible(bars):
        return None
    tpts, ttext = technical_items(bars, facts, today)
    fpts, ftext, usable = fundamental_items(facts)
    if usable:
        epts, etext = event_items(drivers or [])
        fpts.update(epts)
        ftext.update(etext)
    tech = pillar(tpts, TECH_ITEMS, MIN_TECH_POINTS)
    fund = pillar(fpts, FUND_ITEMS, MIN_FUND_POINTS) if usable else None
    b = sorted(bars, key=lambda x: x["trade_date"])
    return {
        "symbol": sym,
        "name": company_names.official_name(sym),
        "sector": sector,
        "close": float(b[-1]["close"]),
        "technical": tech,
        "fundamental": fund,
        "combined": None if tech is None or fund is None else round((tech + fund) / 2, 1),
        "tech_evidence": [ttext[k] for k, _m in TECH_ITEMS if ttext.get(k)],
        "fund_evidence": [ftext[k] for k, _m in FUND_ITEMS if ftext.get(k)],
        "tech_unknown": unknown_items(tpts, TECH_ITEMS),
        "fund_unknown": unknown_items(fpts, FUND_ITEMS) if usable else ["fundamentals not usable"],
    }


def rank(rows: list[dict[str, Any]], key: str, top: int = TOP) -> list[dict[str, Any]]:
    live = [r for r in rows if r.get(key) is not None]
    return sorted(live, key=lambda r: (-r[key], r["symbol"]))[:top]


def skip_reason(bars: list[dict[str, Any]]) -> str:
    if not bars:
        return "no price series on file"
    if len(bars) < MIN_SESSIONS:
        return f"only {len(bars)} sessions of prices (needs {MIN_SESSIONS})"
    b = sorted(bars, key=lambda x: x["trade_date"])
    turnover = statistics.fmean(float(x["close"]) * float(x["volume"]) for x in b[-20:])
    if turnover < MIN_TURNOVER:
        return f"thinly traded (Rs {turnover / 1e6:.1f}m a day; the floor is Rs {MIN_TURNOVER / 1e6:.0f}m)"
    return f"priced under Rs {MIN_PRICE:g}"


def build(
    db: Any,
    today: date,
    bars: dict[str, list[dict[str, Any]]],
    sector: dict[str, str],
    radar: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from engines import research_facts as rf

    symbols = sorted(s for s, b in bars.items() if eligible(b))
    facts: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, symbols, FACT_COLS, since=(today - timedelta(days=800)).isoformat()):
        f = dict(r)
        f["source_date"] = event_date(f)
        facts.setdefault(f["company"], []).append(f)
    drivers = {r["symbol"]: r["drivers"] for r in (radar or [])}
    rows = [
        r
        for s in symbols
        if (r := score_symbol(s, bars[s], facts.get(s, []), today, sector.get(s), drivers.get(s))) is not None
    ]
    return {
        "eligible": len(symbols),
        "rows": {r["symbol"]: r for r in rows},
        "skipped": {s: skip_reason(b) for s, b in bars.items() if not eligible(b)},
        "technical": rank(rows, "technical"),
        "fundamental": rank(rows, "fundamental"),
        "combined": rank(rows, "combined"),
    }


def lookup(result: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Where one symbol stands, or why it is not scored. Rank is among the stocks assessed."""
    sym = symbol.strip().upper()
    row = result["rows"].get(sym)
    if row is None:
        why = result["skipped"].get(sym) or "no price series on file for this symbol"
        return {"symbol": sym, "row": None, "reason": why, "ranks": {}}
    ranks = {}
    for key in ("technical", "fundamental", "combined"):
        order = sorted((r for r in result["rows"].values() if r[key] is not None), key=lambda r: -r[key])
        pos = next((i for i, r in enumerate(order, 1) if r["symbol"] == sym), None)
        ranks[key] = (pos, len(order)) if pos else None
    return {"symbol": sym, "row": row, "reason": "", "ranks": ranks}
