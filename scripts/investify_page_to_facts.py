"""Turn an Investify announcements page that was ALREADY fetched (saved by an earlier dry run) into facts.

Makes no request to Investify: it only reads a local HTML file. Used to load announcements that scrolled off
the live page (it lists the newest 25) between a dry run and the real load.

    python -m scripts.investify_page_to_facts --page investify_page.html --out facts.json \
        --saved-at 2026-11-18T05:51:05Z
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from collectors import investify_library_job as lj
from collectors import investify_policy as pol
from engines import investify_collector as ic


def build(page: str, saved_at: str) -> list[dict]:
    result = ic.collect(page, watchlist=lj.listed_symbols(), retrieved_at_utc=saved_at)
    records = [
        {
            "symbol": r.symbol,
            "title": r.title,
            "category": r.category,
            "announced_at_utc": r.announced_at_utc,
            "pdf_access": r.pdf_access,
            "announced_on_pkt": r.announced_on_pkt,
            "investify_label": r.investify_label,
            "highlights": r.highlights,
            "summary": r.summary,
        }
        for r in result.records
    ]
    when = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
    return lj.facts_from_records(
        records, saved_at, with_highlights=pol.highlights_allowed(when), cutoff=pol.capture_cutoff(when)
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--saved-at", required=True, help="when the page was fetched, ISO UTC")
    args = ap.parse_args(argv)
    facts = build(args.page.read_text(encoding="utf-8"), args.saved_at)
    print(f"facts built from the saved page: {len(facts)}")
    if facts:
        args.out.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
