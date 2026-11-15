"""Fold name-only entities in psx-library under their PSX ticker. Dry run by default.

Reads docs/research/arn/entity_aliases.json ({name: ticker}). One UPDATE per table, with a CASE over all
names, because the tables have no index on the entity column and every statement scans them whole: one
scan per table keeps this inside the per-process row budget. Idempotent: a second run changes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ALIASES = Path(__file__).resolve().parents[1] / "docs" / "research" / "arn" / "entity_aliases.json"


def load(path: Path = ALIASES) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))["aliases"]
    for name, ticker in data.items():
        if not ticker.isalnum() or ticker != ticker.upper():
            raise ValueError(f"not a ticker: {name!r} -> {ticker!r}")
    return data


def statements(aliases: dict[str, str]) -> list[tuple[str, tuple]]:
    """research_fact.company is stored as written; company_link.affected is upper-cased."""
    out = []
    for table, column, fold in (("research_fact", "company", False), ("company_link", "affected", True)):
        names = [n.upper() if fold else n for n in aliases]
        tickers = [aliases[n] for n in aliases]
        marks = ",".join("?" for _ in names)
        case = " ".join(f"WHEN {column} = ? THEN ?" for _ in names)
        sql = f"UPDATE {table} SET {column} = CASE {case} END WHERE {column} IN ({marks})"  # noqa: S608
        params: list[str] = []
        for n, t in zip(names, tickers, strict=True):
            params += [n, t]
        out.append((sql, (*params, *names)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    aliases = load()
    print(f"{len(aliases)} alias(es)")
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply.")
        return 0
    from engines import library_db

    conn = library_db.get_library_connection()
    conn.db.batch(statements(aliases))
    print(f"aliases applied -> {conn.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
