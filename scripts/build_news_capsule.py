"""Turn stored news headlines into a research_fact capsule (a dry run by default: it only writes a JSON file).

Reads psx-library news_item, matches companies, sectors and Pakistan macro topics with
engines/news_facts.py (no model), and writes a capsule that scripts/absorb_sector_capsule.py can load.
The loader skips exact repeats and near-duplicates per company and topic family, so the same story from
two outlets is stored once.

    python -m scripts.build_news_capsule --out capsule.json [--days 30] [--examples 20]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engines import library_db
from engines import news_facts as nf

ROOT = Path(__file__).resolve().parents[1]


def load_vocabulary(db) -> nf.Vocabulary:
    listing = json.loads((ROOT / "docs/research/psx_listed_companies.json").read_text("utf-8"))
    companies = dict(listing["companies"])
    for sym, note in listing.get("owner_confirmed", {}).items():
        if not sym.startswith("_"):
            companies.setdefault(sym, note)
    aliases = json.loads((ROOT / "docs/research/arn/entity_aliases.json").read_text("utf-8"))["aliases"]
    names = {
        r["company"][7:]
        for r in db.execute("SELECT DISTINCT company FROM research_fact WHERE company LIKE 'SECTOR:%'")
    }
    return nf.build_vocabulary(companies, aliases, names)


def build(db, days: int | None) -> tuple[list[dict], int, list[tuple[dict, list[dict]]]]:
    vocab = load_vocabulary(db)
    sql = "SELECT source, url, title, published_at, section, snippet FROM news_item"
    args: tuple = ()
    if days:
        sql += " WHERE published_at >= ?"
        args = ((datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),)
    items = db.execute(sql + " ORDER BY published_at", args)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    seen: list[tuple[dict, list[dict]]] = []
    for item in items:
        made = nf.rows_for_item(vocab, dict(item), created_at=created)
        rows.extend(made)
        seen.append((dict(item), made))
    return rows, len(items), seen


def report(rows: list[dict], n_items: int, seen: list[tuple[dict, list[dict]]], examples: int) -> None:
    matched = sum(1 for _i, made in seen if made)
    print(
        f"news items read: {n_items}; items that became at least one row: {matched} "
        f"({100 * matched // max(n_items, 1)}%); rows: {len(rows)}"
    )
    kinds = Counter(
        "company" if not r["company"].startswith(("SECTOR:", "MACRO:")) else r["company"].split(":")[0]
        for r in rows
    )
    print("rows by kind:", dict(kinds))
    print("rows by topic:", dict(Counter(r["topic"] for r in rows).most_common(12)))
    print("top companies:", Counter(r["company"] for r in rows if ":" not in r["company"]).most_common(12))
    print("rows by outlet:", dict(Counter(r["source_name"].split(" news,")[0] for r in rows)))
    shown = 0
    print("\nexamples (headline -> company / topic):")
    for item, made in seen:
        if (
            made
            and shown < examples
            and shown % 1 == 0
            and item["source"] in ("dawn_business", "brecorder", "profit", "tribune_business", "mettis")
        ):
            if hash(item["url"]) % 5 == 0:
                print(f"  [{item['source'][:8]}] {item['title'][:78]}")
                print("      ->", "; ".join(f"{r['company']} / {r['topic']}" for r in made))
                shown += 1
    print("\nskipped examples (no company, sector or Pakistan market topic):")
    skipped = [i for i, made in seen if not made][:8]
    for item in skipped:
        print(f"  [{item['source'][:8]}] {item['title'][:90]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--examples", type=int, default=20)
    args = ap.parse_args(argv)
    db = library_db.get_library_connection().db
    rows, n_items, seen = build(db, args.days)
    report(rows, n_items, seen, args.examples)
    if rows:
        args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"\ncapsule written: {args.out} ({len(rows)} rows). Nothing was loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
