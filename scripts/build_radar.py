"""Build the company radar (engines/materiality.py) from psx-library. Read only: no database is written.

Reads, all indexed or small: price_daily (about 35 days), news_rollup (primary key starts with day),
research_fact for the candidate companies over the last few days (company/date index), and a longer
look back only for companies that have a results fact in the window (for the like-for-like EPS comparison).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from engines import announcement_substance as asub
from engines import company_names, library_db, materiality, news_rollup
from engines import research_facts as rf

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FACT_COLS = "company, topic, fact_text, value, unit, period, source_name, source_url, source_date"
NOT_COMPANY = ("SECTOR:", "MACRO:")


def price_moves(db: Any, today: date, days: int) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Per symbol, the largest move in the last `days` sessions, and its volume vs the prior 20."""
    rows = db.execute(
        "SELECT symbol, trade_date, close, volume FROM price_daily WHERE trade_date >= ? "
        "ORDER BY symbol, trade_date",
        ((today - timedelta(days=days + 40)).isoformat(),),
    )
    by: dict[str, list[Any]] = {}
    for r in rows:
        by.setdefault(r["symbol"], []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for sym, bars in by.items():
        best = None
        for i in range(max(1, len(bars) - days), len(bars)):
            prev, cur = float(bars[i - 1]["close"]), float(bars[i]["close"])
            window = bars[max(0, i - 20) : i]
            base = sum(float(b["volume"]) for b in window) / len(window) if len(window) >= 20 else 0
            move = (cur / prev - 1) * 100 if prev > 0 else None
            vol = float(bars[i]["volume"]) / base if base > 0 else None
            if move is None:
                continue
            cand = {"day": bars[i]["trade_date"], "move": move, "volume_x": vol}
            if best is None or abs(move) > abs(best["move"]):
                best = cand
        if best:
            out[sym] = best
    return out, set(by)


def event_date(f: dict[str, Any]) -> str:
    """The day the thing happened. Announcement facts from the Investify load carry the LOAD date as
    source_date and the announcement date in `period`; using the load date would show old results as new."""
    if str(f["topic"]).startswith("announcements.") and _ISO.match(str(f.get("period") or "")):
        return str(f["period"])
    return str(f["source_date"])


def build(db: Any, today: date, days: int = 3, top: int = 25) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    since = (today - timedelta(days=days)).isoformat()
    moves, price_symbols = price_moves(db, today, days)
    roll = [
        dict(r)
        for r in db.execute(
            "SELECT day, entity, stories, topics, top_title, top_url FROM news_rollup WHERE day >= ?",
            ((today - timedelta(days=news_rollup.BASELINE_DAYS + 9)).isoformat(),),
        )
    ]
    signals = {s["company"]: s for s in news_rollup.signals(roll, today, stamp)}
    recent = {r["entity"] for r in roll if r["day"] >= since and not r["entity"].startswith(NOT_COMPANY)}
    recent.discard(news_rollup.ALL)
    candidates = sorted(price_symbols | recent)
    window_facts = []
    for r in rf.facts_for(db, candidates, FACT_COLS, since=since):
        f = dict(r)
        f["source_date"] = event_date(f)
        if f["source_date"] >= since:
            window_facts.append(f)
    by_company: dict[str, list[dict[str, Any]]] = {}
    for f in window_facts:
        by_company.setdefault(f["company"], []).append(f)
    with_results = [
        c
        for c, fs in by_company.items()
        if any(str(f["topic"]).startswith(materiality.RESULT_TOPICS) for f in fs)
    ]
    history: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, with_results, FACT_COLS, since=(today - timedelta(days=800)).isoformat()):
        history.setdefault(r["company"], []).append(dict(r))
    # company size for the announcements' size bands (only companies with an announcement in the window)
    announcing = [
        c for c, fs in by_company.items() if any(str(f["topic"]).startswith("announcements.") for f in fs)
    ]
    mcaps: dict[str, float | None] = {}
    caps_by_company: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(
        db,
        announcing,
        "company, topic, fact_text, source_date",
        since=(today - timedelta(days=120)).isoformat(),
    ):
        if r["topic"] == "fundamentals.market_cap":
            caps_by_company.setdefault(r["company"], []).append(dict(r))
    for c in announcing:
        mcaps[c] = asub.market_cap(caps_by_company.get(c, []))
    scored = [
        materiality.score_company(
            c,
            window_facts=by_company.get(c, []),
            history_facts=history.get(c, []),
            price=moves.get(c),
            news_signal=signals.get(c),
            has_prices=c in price_symbols,
            company_names=company_names.names_for(c),
            mcap=mcaps.get(c),
        )
        for c in candidates
    ]
    ranked = materiality.rank(scored, top)
    return ranked, {"checked": len(candidates), "with_price": len(price_symbols & set(candidates))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out-dir", type=Path, default=Path(".radar"))
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    today = datetime.now(UTC).date()
    ranked, stats = build(db, today, args.days, args.top)
    md = materiality.render_markdown(ranked, today.isoformat(), stats["checked"], stats["with_price"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "radar.md").write_text(md, encoding="utf-8")
    (args.out_dir / "radar.json").write_text(
        json.dumps(ranked, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    print(md[:6000])
    print(f"usage: {db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
