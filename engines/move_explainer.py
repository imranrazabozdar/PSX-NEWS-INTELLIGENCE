"""Why did it move? Candidate explanations for a price move, ranked by the evidence on file. No model.

This never states a cause as certain. It lists what the brain holds that is consistent with the move (dated,
sourced), how much of the move the sector or the market also made, and says "no identified cause in the
evidence on file" when nothing fits. It gives no buy or sell view. Missing evidence is reported as missing,
never as zero.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from engines import materiality

MOVE_PCT = 5.0
VOLUME_X = 3.0
SECTOR_MIN_PEERS = 3
SECTOR_MOVE = 2.0  # sector median move (same direction) that counts as moving with the sector
MARKET_MOVE = 1.5  # market median move (same direction) that counts as a market-wide move
EVENT_LOOKBACK_DAYS = 2  # results and announcements often land the evening before the move
MACRO_TOPICS = {
    "market.rates",
    "market.fx",
    "market.fiscal",
    "market.energy",
    "market.inflation",
    "market.kse100_drivers",
    "market.kse100_move",
}
# Investify announcement labels (announcements.<label>). Material ones are company-specific disclosures;
# scheduled ones are routine notices that say a date is coming, not why a price moved. Everything else
# (report transmission, briefings, auditor certificates, insider lines, "Other") stays out of the explanation.
MATERIAL_LABELS = {
    "Material Disclosure",
    "Management Change",
    "Financing / Restructuring",
    "M&A / Public Offer",
    "Legal / Regulatory",
    "Capacity / Shutdown",
    "Operations Update",
    "Unusual Movement Reply",
    "Share Buyback",
    "Share Split",
    "Credit Rating",
    "Scheme / Arrangement",
    "Rights / Bonus",
    "Corporate Action",
}
SCHEDULED_LABELS = {"Board Meeting", "AGM / EGM", "Book Closure", "Dividend", "Meetings"}
PER_KIND_CAP = 3
STRENGTH = {
    "company_event": 3,
    "company_news": 2,
    "company_announcement": 2,
    "sector": 2,
    "market": 1,
    "scheduled_notice": 1,
}
COMPANY_KINDS = ("company_event", "company_news", "company_announcement")


def pct(a: float, b: float) -> float | None:
    return (b / a - 1) * 100 if a and a > 0 else None


def daily_moves(bars: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(symbol, day) -> {move, volume_x} for each session with a previous one; volume_x needs 20 prior."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for sym, rows in bars.items():
        rows = sorted(rows, key=lambda r: r["trade_date"])
        for i in range(1, len(rows)):
            move = pct(float(rows[i - 1]["close"]), float(rows[i]["close"]))
            if move is None:
                continue
            window = rows[max(0, i - 20) : i]
            base = sum(float(r["volume"]) for r in window) / len(window) if len(window) >= 20 else 0
            vol = float(rows[i]["volume"]) / base if base > 0 else None
            out[(sym, rows[i]["trade_date"])] = {"move": move, "volume_x": vol}
    return out


def notable(moves: dict[tuple[str, str], dict[str, Any]], since: str) -> list[dict[str, Any]]:
    out = []
    for (sym, day), m in moves.items():
        if day < since:
            continue
        if abs(m["move"]) >= MOVE_PCT or (m["volume_x"] or 0) >= VOLUME_X:
            out.append({"symbol": sym, "day": day, **m})
    return sorted(out, key=lambda r: (r["day"], abs(r["move"])), reverse=True)


def median_move(
    moves: dict[tuple[str, str], dict[str, Any]], symbols: list[str], day: str
) -> tuple[float | None, int]:
    vals = [moves[(s, day)]["move"] for s in symbols if (s, day) in moves]
    return (statistics.median(vals), len(vals)) if vals else (None, 0)


def _within(day: str, event_day: str) -> bool:
    d, e = date.fromisoformat(day), date.fromisoformat(event_day)
    return d - timedelta(days=EVENT_LOOKBACK_DAYS) <= e <= d


def explain(
    mv: dict[str, Any],
    *,
    facts: list[dict[str, Any]],
    history: list[dict[str, Any]],
    news_rows: list[dict[str, Any]],
    sector: str | None,
    sector_symbols: list[str],
    moves: dict[tuple[str, str], dict[str, Any]],
    all_symbols: list[str],
    macro_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    sym, day, move = mv["symbol"], mv["day"], mv["move"]
    evidence: list[dict[str, Any]] = []
    unknown: list[str] = []

    for f in sorted(facts, key=lambda f: f["source_date"], reverse=True):
        t, d = str(f["topic"]), f["source_date"]
        if not _within(day, d):
            continue
        if t.startswith(materiality.RESULT_TOPICS) or t.startswith(materiality.CORPORATE_TOPICS):
            evidence.append(
                {
                    "kind": "company_event",
                    "date": d,
                    "text": f["fact_text"][:220],
                    "source": f["source_name"],
                    "is_result": t.startswith(materiality.RESULT_TOPICS),
                }
            )
    for f in sorted(facts, key=lambda f: f["source_date"], reverse=True):
        t, d = str(f["topic"]), f["source_date"]
        if (
            not t.startswith("announcements.")
            or t.startswith(materiality.RESULT_TOPICS)
            or not _within(day, d)
        ):
            continue
        label = t[len("announcements.") :]
        kind = (
            "company_announcement"
            if label in MATERIAL_LABELS
            else "scheduled_notice"
            if label in SCHEDULED_LABELS
            else None
        )
        if kind and sum(1 for e in evidence if e["kind"] == kind) < PER_KIND_CAP:
            evidence.append(
                {"kind": kind, "date": d, "text": f["fact_text"][:220], "source": f["source_name"]}
            )
    if any(e.get("is_result") for e in evidence):
        change, why = materiality.eps_pair(history)
        if change and change.get("pct") is not None:
            evidence.append(
                {
                    "kind": "company_event",
                    "date": day,
                    "source": "stored EPS facts",
                    "text": f"EPS {change['label']}: {change['prev']:g} -> {change['cur']:g} "
                    f"({change['pct']:+.0f}%)",
                }
            )
        elif change:
            evidence.append(
                {
                    "kind": "company_event",
                    "date": day,
                    "source": "stored EPS facts",
                    "text": f"EPS changed sign, {change['label']}: {change['prev']:g} -> {change['cur']:g}",
                }
            )
        else:
            unknown.append(f"result size unknown: {why}")

    for r in news_rows:
        if _within(day, r["day"]) and r["stories"] > 0 and r.get("top_title"):
            evidence.append(
                {
                    "kind": "company_news",
                    "date": r["day"],
                    "source": "news_rollup",
                    "text": f"{r['stories']} stories; top: {str(r['top_title'])[:160]}",
                }
            )
    if not any(e["kind"] in COMPANY_KINDS for e in evidence):
        unknown.append("no company news or announcement on file for the days before the move")

    sector_move, peers = (None, 0)
    if sector:
        others = [s for s in sector_symbols if s != sym]
        sector_move, peers = median_move(moves, others, day)
        if (
            sector_move is not None
            and peers >= SECTOR_MIN_PEERS
            and move * sector_move > 0
            and abs(sector_move) >= SECTOR_MOVE
        ):
            evidence.append(
                {
                    "kind": "sector",
                    "date": day,
                    "source": "price_daily",
                    "text": f"its sector ({sector}) also moved: median {sector_move:+.1f}% "
                    f"across {peers} peers",
                }
            )
    else:
        unknown.append("sector unknown")
    market_move, n = median_move(moves, [s for s in all_symbols if s != sym], day)
    if market_move is not None and move * market_move > 0 and abs(market_move) >= MARKET_MOVE:
        evidence.append(
            {
                "kind": "market",
                "date": day,
                "source": "price_daily",
                "text": f"the whole tracked market moved too: median {market_move:+.1f}% across {n} symbols",
            }
        )

    context = [
        f for f in facts if str(f["topic"]).startswith("technical.") and _within(day, f["source_date"])
    ]
    base = sector_move if sector_move is not None and peers >= SECTOR_MIN_PEERS else market_move
    residual = move - base if base is not None else None
    macro = [
        f"{f['source_date']}: {str(f['fact_text'])[:150]} ({f['topic']})"
        for f in sorted(macro_facts, key=lambda f: f["source_date"], reverse=True)
        if f["topic"] in MACRO_TOPICS and _within(day, f["source_date"])
    ][:2]
    ranked = sorted(evidence, key=lambda e: -STRENGTH[e["kind"]])
    company = [e for e in ranked if e["kind"] in COMPANY_KINDS]
    if company:
        verdict = "evidence on file about this company is consistent with the move"
    elif any(e["kind"] in ("sector", "market") for e in ranked):
        verdict = "the move was shared with its sector or the market; no company-specific evidence on file"
    elif ranked:
        verdict = "only routine scheduled notices are on file for this company; no company-specific cause"
    else:
        verdict = "no identified cause in the evidence on file"
    return {
        "symbol": sym,
        "day": day,
        "move": round(move, 2),
        "volume_x": mv.get("volume_x"),
        "residual_vs_group": None if residual is None else round(residual, 2),
        "verdict": verdict,
        "evidence": ranked,
        "unknown": unknown,
        "technical_context": [f["fact_text"][:160] for f in context[:2]],
        "macro_context": macro,
    }


def render_markdown(items: list[dict[str, Any]], day: str, universe: int) -> str:
    lines = [
        f"# Why did it move: notable moves up to {day}",
        "",
        "Candidate explanations from the evidence on file. They are not proof of cause and not "
        "recommendations. Where nothing fits it says so.",
        "",
        f"{len(items)} moves explained, {universe} symbols tracked.",
        "",
    ]
    none = [i for i in items if i["verdict"].startswith("no identified cause")]
    lines.append(f"Unexplained (no cause on file): {len(none)} of {len(items)}.")
    for i in sorted(none, key=lambda i: -abs(i["move"]) * (i.get("volume_x") or 1))[:10]:
        vol = f", volume {i['volume_x']:.1f}x" if i.get("volume_x") else ""
        lines.append(f"- {i['symbol']} {i['move']:+.1f}% on {i['day']}{vol}")
    lines.append("")
    for i in items:
        vol = f", volume {i['volume_x']:.1f}x" if i.get("volume_x") else ""
        lines.append(f"## {i['symbol']} {i['move']:+.1f}% on {i['day']}{vol}")
        lines.append(f"- verdict: {i['verdict']}")
        if i["residual_vs_group"] is not None:
            lines.append(f"- move beyond its sector/market median: {i['residual_vs_group']:+.1f} points")
        for e in i["evidence"]:
            lines.append(f"- [{e['kind']}] {e['text']} ({e['date']}; {e['source']})")
        for u in i["unknown"]:
            lines.append(f"- unknown: {u}")
        for m in i.get("macro_context", []):
            lines.append(f"- market context on those days (not shown to cause this move): {m}")
        for t in i["technical_context"]:
            lines.append(f"- technical context (heuristic, not a cause): {t}")
        lines.append("")
    return "\n".join(lines)
