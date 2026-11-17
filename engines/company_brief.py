"""One company, everything the brain holds, assembled for display. Read only; no model; no price view.

`market_context()` is the expensive, shared part (every symbol's recent bars and sectors): compute it once and
cache it. `load()` is the per-company part: its own facts, news days and price bars.
Missing things are listed under `unknown`; nothing is estimated or shown as zero.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from engines import announcement_substance as asub
from engines import company_names, materiality, move_explainer
from engines import research_facts as rf
from scripts import explain_moves as ex
from scripts.build_radar import FACT_COLS, event_date

FUNDAMENTAL_KEYS = (
    ("fundamentals.latest_quarter_eps", "Latest quarter EPS"),
    ("fundamentals.annual_eps", "Annual EPS"),
    ("fundamentals.annual_p_e", "P/E (annual)"),
    ("fundamentals.price_book", "Price / book"),
    ("fundamentals.dividend_yield", "Dividend yield"),
    ("fundamentals.return_on_equity", "Return on equity"),
    ("fundamentals.market_cap", "Market cap"),
)


def market_context(db: Any, today: date, days: int = 30) -> dict[str, Any]:
    bars = ex.load_bars(db, today, days)
    symbols = sorted(bars)
    sector = ex.sectors_of(db, symbols)
    by_sector: dict[str, list[str]] = {}
    for s, sec in sector.items():
        by_sector.setdefault(sec, []).append(s)
    return {"bars": bars, "moves": move_explainer.daily_moves(bars), "sector": sector, "by_sector": by_sector}


def _latest(facts: list[dict[str, Any]], topic: str) -> dict[str, Any] | None:
    rows = [f for f in facts if f["topic"] == topic]
    return max(rows, key=lambda f: f["source_date"]) if rows else None


def load(db: Any, symbol: str, today: date, ctx: dict[str, Any], days: int = 30) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    unknown: list[str] = []
    facts = []
    for r in rf.facts_for(db, [symbol], FACT_COLS):
        f = dict(r)
        f["event_date"] = event_date(f)
        facts.append(f)
    if not facts:
        unknown.append("no facts on file for this symbol")

    sector = ctx["sector"].get(symbol)
    if not sector:
        unknown.append("sector unknown")

    bars = sorted(ctx["bars"].get(symbol, []), key=lambda b: b["trade_date"])
    price: dict[str, Any] | None = None
    if bars:
        last = bars[-1]
        close = float(last["close"])

        def chg(n: int) -> float | None:
            return move_explainer.pct(float(bars[-1 - n]["close"]), close) if len(bars) > n else None

        price = {
            "date": last["trade_date"],
            "close": close,
            "change_1d": chg(1),
            "change_5d": chg(5),
            "change_20d": chg(20),
            "series": [(b["trade_date"], float(b["close"])) for b in bars],
        }
    else:
        unknown.append("no price series (the technical engine does not cover this symbol)")

    since = (today - timedelta(days=days)).isoformat()
    notable = [m for m in move_explainer.notable(ctx["moves"], since) if m["symbol"] == symbol][:5]
    history = [f for f in facts if str(f["topic"]).startswith(materiality.RESULT_TOPICS)]
    news_rows = [
        dict(r)
        for r in db.execute(
            "SELECT day, entity, stories, topics, top_title, top_url FROM news_rollup WHERE day >= ?",
            ((today - timedelta(days=days + 3)).isoformat(),),
        )
        if r["entity"] == symbol
    ]
    macro = [
        {**dict(r), "source_date": event_date(dict(r))}
        for r in rf.facts_for(db, ["MACRO:PAKISTAN"], FACT_COLS, since=since)
    ]
    sym_facts = [dict(f, source_date=f["event_date"]) for f in facts]
    explained = [
        move_explainer.explain(
            m,
            facts=sym_facts,
            history=history,
            news_rows=news_rows,
            sector=sector,
            sector_symbols=ctx["by_sector"].get(sector or "", []),
            moves=ctx["moves"],
            all_symbols=sorted(ctx["bars"]),
            macro_facts=macro,
        )
        for m in notable
    ]

    results = sorted(
        (f for f in facts if str(f["topic"]).startswith("results.")),
        key=lambda f: f["event_date"],
        reverse=True,
    )[:8]
    change, why = materiality.eps_pair(facts)
    if not results:
        unknown.append("no results on file")
    elif change is None:
        unknown.append(f"result size unknown: {why}")
    actions = sorted(
        (
            f
            for f in facts
            if str(f["topic"]).startswith(materiality.CORPORATE_TOPICS)
            and f["event_date"] >= (today - timedelta(days=365)).isoformat()
        ),
        key=lambda f: f["event_date"],
        reverse=True,
    )[:10]
    cutoff = (today - timedelta(days=days)).isoformat()
    announcements = []
    mcap = asub.market_cap(facts)
    names = company_names.names_for(symbol)
    for f in sorted(facts, key=lambda f: f["event_date"], reverse=True):
        topic = str(f["topic"])
        if not topic.startswith("announcements.") or f["event_date"] < cutoff:
            continue
        label = topic[len("announcements.") :]
        weight = (
            "material"
            if label in materiality.MATERIAL_LABELS
            else "scheduled"
            if label in materiality.SCHEDULED_LABELS
            else "routine"
        )
        size = (
            asub.assess(label, f["fact_text"], company_names=names, mcap=mcap)
            if weight == "material"
            else None
        )
        announcements.append(
            {
                "date": f["event_date"],
                "label": label,
                "weight": weight,
                "text": f["fact_text"],
                "source": f["source_name"],
                "tier": size["tier"] if size else None,
                "points": size["points"] if size else None,
                "basis": size["basis"] if size else [],
            }
        )
    # newest first, then material (largest size first), then scheduled, then routine (the sort is stable)
    announcements.sort(key=lambda a: a["date"], reverse=True)
    announcements.sort(key=lambda a: -(a["points"] or 0))
    announcements.sort(key=lambda a: {"material": 0, "scheduled": 1, "routine": 2}[a["weight"]])
    news = sorted(news_rows, key=lambda r: r["day"], reverse=True)[:10]
    if not news:
        unknown.append("no news for this company in the last month")
    tech = sorted(
        (f for f in facts if str(f["topic"]).startswith("technical.")),
        key=lambda f: f["event_date"],
        reverse=True,
    )[:6]
    if not tech:
        unknown.append("no technical-engine signals on file")
    fundamentals = []
    for topic, label in FUNDAMENTAL_KEYS:
        f = _latest(facts, topic)
        if f:
            fundamentals.append(
                {
                    "label": label,
                    "text": f["fact_text"],
                    "value": f["value"],
                    "as_of": f["source_date"],
                    "source": f["source_name"],
                }
            )
    if not fundamentals:
        unknown.append("no fundamentals snapshot on file")
    return {
        "symbol": symbol,
        "sector": sector,
        "price": price,
        "moves": explained,
        "results": results,
        "eps_change": change,
        "actions": actions,
        "announcements": announcements,
        "news": news,
        "technical": tech,
        "fundamentals": fundamentals,
        "unknown": unknown,
    }
