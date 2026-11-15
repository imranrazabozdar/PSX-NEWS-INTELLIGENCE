"""Load gated company links into psx-library company_link. Dry run by default; idempotent.

Every batch is judged against the facts it was extracted from (scripts.check_links_batch); only links
that pass that check are stored, so a stored link always cites a real fact with an exact quote.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from database.canonical import now_utc
from scripts import apply_library_migration as mig
from scripts import check_links_batch as chk

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0007_company_link.sql"
INSERT = ("INSERT OR IGNORE INTO company_link (driver, affected, direction, fact_id, quote, created_at) "
          "VALUES (?, ?, ?, ?, ?, ?)")
BATCH = 200


def collect(pairs: list[tuple[Path, Path]]) -> tuple[list[dict], dict]:
    """Valid links from (links_file, facts_file) pairs, de-duplicated; plus a per-batch report."""
    seen: set[tuple] = set()
    keep: list[dict] = []
    report = {}
    for links_path, facts_path in pairs:
        result = chk.judge(json.loads(links_path.read_text()), json.loads(facts_path.read_text()))
        bad = {json.dumps(b, sort_keys=True) for b in result["invalid"]}
        report[links_path.name] = {k: result[k] for k in ("links", "valid", "valid_share", "passes")}
        for link in json.loads(links_path.read_text()):
            if json.dumps(link, sort_keys=True) in bad:
                continue
            key = (link["fact_id"], link["driver"].lower(), link["affected"].upper(), link["quote"])
            if key not in seen:
                seen.add(key)
                keep.append(link)
    return keep, report


def apply(links: list[dict], db) -> int:
    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    stamp = now_utc()
    rows = [(x["driver"], x["affected"].upper(), x["direction"], int(x["fact_id"]), x["quote"], stamp)
            for x in links]
    for i in range(0, len(rows), BATCH):
        db.batch([(INSERT, r) for r in rows[i:i + BATCH]])
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True,
                        help="folder with in/<id>.json facts and out/<id>.json links")
    parser.add_argument("--extra", nargs=2, action="append", default=[], metavar=("LINKS", "FACTS"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    pairs = [(p, args.dir / "in" / p.name) for p in sorted((args.dir / "out").glob("*.json"))]
    pairs += [(Path(a), Path(b)) for a, b in args.extra]
    links, report = collect(pairs)
    for name, r in report.items():
        print(name, r)
    print(f"{len(links)} valid, de-duplicated link(s)")
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply.")
        return 0
    from engines import library_db

    conn = library_db.get_library_connection()
    print(f"stored {apply(links, conn.db)} link(s) -> {conn.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
