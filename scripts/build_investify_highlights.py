"""Announcement Highlights from the owner's Investify export, as private facts (addendum of 17 Nov 2026).

Reads the same read-only export as build_investify_capsule.py (`investify_psx.db`), takes each announcement
card's short Highlights text (the key-facts line and the summary paragraph under the title) and writes a
capsule of `announcement_highlights` facts, each linked to its title fact by the same '<date>: <title>'
prefix. Allowed only when the addendum (docs/consent/investify-2026-11-17-highlights.md) is in force. Private
use only: the facts go to psx-library, and reports quote numbers and size bands, never this text.

    python -m scripts.build_investify_highlights /path/to/investify_psx.db --out highlights.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collectors import investify_policy as pol
from collectors.investify_library_job import highlight_fact_rows
from engines import research_facts as rf
from scripts.build_investify_capsule import ANN_DATE, GROUPS_SKIP

MAX_LINES = 3  # a key-facts line, a summary paragraph, and one spare for a wrapped line


def highlight_rows(sym: str, lines: list[str], scraped: str) -> list[dict[str, Any]]:
    out = []
    for i, line in enumerate(lines):
        m = ANN_DATE.match(line)
        if not m or i < 2 or i + 1 >= len(lines):
            continue
        group, title = lines[i - 2].strip(), lines[i + 1].strip()
        if not title or group in GROUPS_SKIP or len(group) > 40:
            continue
        extra: list[str] = []
        for nxt in lines[i + 2 : i + 2 + MAX_LINES + 1]:
            if nxt in GROUPS_SKIP or ANN_DATE.match(nxt) or len(extra) >= MAX_LINES:
                break
            extra.append(" ".join(nxt.split()))
        text = " ".join(x for x in extra if x)
        if not text:
            continue
        when = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        title_text = " ".join(title.split())
        for row in highlight_fact_rows(sym, title_text, when, text, scraped):
            out.append(rf.validate_fact(row))
    return out


def build(db_path: Path) -> list[dict[str, Any]]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows: list[dict[str, Any]] = []
    for sym, js, scraped in db.execute(
        "SELECT symbol, lines_json, scraped_at FROM company_pages WHERE tab = 'announcements'"
    ):
        rows += highlight_rows(sym, [str(x) for x in json.loads(js)], scraped)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("db", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if not pol.highlights_allowed(datetime.now(UTC)):
        print("refused: the 17 Nov 2026 Highlights addendum is not in force (record missing or too early)")
        return 2
    rows = build(args.db)
    args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"highlights: {len(rows)} facts for {len({r['company'] for r in rows})} companies -> {args.out}")
    print("nothing was loaded; load with scripts.absorb_sector_capsule --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
