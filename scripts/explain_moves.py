"""Explain notable price moves (engines/move_explainer.py) from psx-library. Read only: no writes.

Reads: price_daily (about 45 days), news_rollup for the last days, the sector of each symbol, and
research_fact for the moving symbols only (company/date index), plus a long look-back only for companies
with a result in the window.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from engines import library_db, materiality, move_explainer
from engines import research_facts as rf
from scripts.build_radar import FACT_COLS, event_date


def load_bars(db: Any, today: date, days: int) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute(
        "SELECT symbol, trade_date, close, volume FROM price_daily WHERE trade_date >= ? "
        "ORDER BY symbol, trade_date",
        ((today - timedelta(days=days + 45)).isoformat(),),
    )
    bars: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        bars.setdefault(r["symbol"], []).append(dict(r))
    return bars


def sectors_of(db: Any, symbols: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rf.facts_for(db, symbols, "company, topic, fact_text"):
        if r["topic"] == "profile.sector" and str(r["fact_text"]).startswith("Sector: "):
            out[r["company"]] = str(r["fact_text"])[len("Sector: ") :]
    return out


def build(db: Any, today: date, days: int = 5, top: int = 20) -> tuple[list[dict[str, Any]], int]:
    bars = load_bars(db, today, days)
    moves = move_explainer.daily_moves(bars)
    since = (today - timedelta(days=days)).isoformat()
    picked = move_explainer.notable(moves, since)[:top]
    all_symbols = sorted(bars)
    sector = sectors_of(db, all_symbols)
    by_sector: dict[str, list[str]] = {}
    for s, sec in sector.items():
        by_sector.setdefault(sec, []).append(s)
    symbols = sorted({m["symbol"] for m in picked})
    first = min((m["day"] for m in picked), default=since)
    fact_since = (
        date.fromisoformat(first) - timedelta(days=move_explainer.EVENT_LOOKBACK_DAYS + 1)
    ).isoformat()
    facts: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, symbols, FACT_COLS, since=fact_since):
        f = dict(r)
        f["source_date"] = event_date(f)
        facts.setdefault(f["company"], []).append(f)
    with_results = [
        s for s, fs in facts.items() if any(str(f["topic"]).startswith(materiality.RESULT_TOPICS) for f in fs)
    ]
    history: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, with_results, FACT_COLS, since=(today - timedelta(days=800)).isoformat()):
        history.setdefault(r["company"], []).append(dict(r))
    roll: dict[str, list[dict[str, Any]]] = {}
    macro_facts = [
        {**dict(r), "source_date": event_date(dict(r))}
        for r in rf.facts_for(db, ["MACRO:PAKISTAN"], FACT_COLS, since=fact_since)
    ]
    for r in db.execute(
        "SELECT day, entity, stories, topics, top_title FROM news_rollup WHERE day >= ?", (fact_since,)
    ):
        r = dict(r)
        if r["entity"] in symbols:
            roll.setdefault(r["entity"], []).append(r)
    items = [
        move_explainer.explain(
            m,
            facts=facts.get(m["symbol"], []),
            history=history.get(m["symbol"], []),
            news_rows=roll.get(m["symbol"], []),
            sector=sector.get(m["symbol"]),
            sector_symbols=by_sector.get(sector.get(m["symbol"], ""), []),
            moves=moves,
            all_symbols=all_symbols,
            macro_facts=macro_facts,
        )
        for m in picked
    ]
    return items, len(all_symbols)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out-dir", type=Path, default=Path(".moves"))
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    today = datetime.now(UTC).date()
    items, universe = build(db, today, args.days, args.top)
    md = move_explainer.render_markdown(items, today.isoformat(), universe)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "moves.md").write_text(md, encoding="utf-8")
    (args.out_dir / "moves.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    print(md[:9000])
    print(f"usage: {db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
