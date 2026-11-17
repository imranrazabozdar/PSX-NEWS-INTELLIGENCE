"""Score the move explanations against what the price did next (engines/explanation_scoring.py). Read only.

Every notable move in price_daily is explained with only the evidence dated on or before its day, filed in a
bucket by the verdict, and described by the signed return over the next sessions. Descriptive; not a forecast.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from engines import explanation_scoring as sc
from engines import library_db, materiality, move_explainer
from engines import research_facts as rf
from scripts.build_radar import FACT_COLS, event_date
from scripts.explain_moves import load_bars, sectors_of


def build(db: Any, today: date) -> tuple[dict[str, Any], str, str, int]:
    bars = load_bars(db, today, 200)
    symbols = sorted(bars)
    moves = move_explainer.daily_moves(bars)
    first_day = min((b[0]["trade_date"] for b in bars.values() if b), default=today.isoformat())
    picked = move_explainer.notable(moves, first_day)
    sector = sectors_of(db, symbols)
    by_sector: dict[str, list[str]] = {}
    for s, sec in sector.items():
        by_sector.setdefault(sec, []).append(s)
    facts: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, symbols, FACT_COLS, since=(today - timedelta(days=800)).isoformat()):
        f = dict(r)
        f["source_date"] = event_date(f)
        facts.setdefault(f["company"], []).append(f)
    roll: dict[str, list[dict[str, Any]]] = {}
    for r in db.execute(
        "SELECT day, entity, stories, topics, top_title FROM news_rollup WHERE day >= ?", (first_day,)
    ):
        roll.setdefault(r["entity"], []).append(dict(r))
    macro = [
        {**dict(r), "source_date": event_date(dict(r))}
        for r in rf.facts_for(db, ["MACRO:PAKISTAN"], FACT_COLS, since=first_day)
    ]
    rows = []
    for m in picked:
        sym, day = m["symbol"], m["day"]
        own = facts.get(sym, [])
        # no hindsight: only facts dated on or before the move's day, and only history up to that day
        known = [f for f in own if f["source_date"] <= day]
        history = [f for f in known if str(f["topic"]).startswith(materiality.RESULT_TOPICS)]
        item = move_explainer.explain(
            m,
            facts=known,
            history=history,
            news_rows=[r for r in roll.get(sym, []) if r["day"] <= day],
            sector=sector.get(sym),
            sector_symbols=by_sector.get(sector.get(sym, ""), []),
            moves=moves,
            all_symbols=symbols,
            macro_facts=[f for f in macro if f["source_date"] <= day],
        )
        rows.append(
            {
                "bucket": sc.bucket_of(item),
                "move": m["move"],
                "forward": sc.forward_signed(bars[sym], day, m["move"]),
            }
        )
    last = max((b[-1]["trade_date"] for b in bars.values() if b), default=today.isoformat())
    return sc.summarise(rows), first_day, last, len(symbols)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=Path(".scoring"))
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    summary, first, last, n = build(db, datetime.now(UTC).date())
    md = sc.render_markdown(summary, first, last, n)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "scoring.md").write_text(md, encoding="utf-8")
    (args.out_dir / "scoring.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    print(md)
    print(f"usage: {db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
