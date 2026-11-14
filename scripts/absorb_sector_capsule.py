"""Absorb one sector knowledge capsule into psx-library research_fact.

A capsule is a JSON list of research_fact rows (see engines/research_facts.py). Default is a DRY RUN: it
validates every row, prints counts per company, and writes nothing. --apply writes, skipping any row whose
(company, topic, fact_text) already exists, so re-running a capsule is safe. Placeholder sources are refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from engines import library_db
from engines import research_facts as rf

PLACEHOLDER_MARKERS = ("...", "<", "TODO", "xxx")


def load_capsule(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise rf.ResearchFactError("a capsule must be a non-empty JSON list")
    clean = []
    for i, row in enumerate(rows):
        checked = rf.validate_fact(row)
        source = str(checked["source_name"])
        if any(marker in source for marker in PLACEHOLDER_MARKERS):
            raise rf.ResearchFactError(f"row {i}: source_name looks like a placeholder: {source[:60]!r}")
        clean.append(checked)
    return clean


def absorb(path: Path, *, apply: bool, db: Any = None) -> int:
    rows = load_capsule(path)
    print(f"capsule valid: {len(rows)} row(s)")
    for company, n in sorted(Counter(r["company"] for r in rows).items()):
        print(f"  {company}: {n}")
    if not apply:
        print("dry run: nothing written. Re-run with --apply to write.")
        return 0
    if db is None:
        conn = library_db.get_library_connection()  # target guard runs here
        db = conn.db
        print(f"target host: {conn.host}")
    for stmt in _schema_statements():
        db.execute(stmt)
    written = skipped = 0
    for r in rows:
        dup = db.execute(_DUP, (r["company"], r["topic"], r["fact_text"]))[0]["n"]
        if dup:
            skipped += 1
            continue
        db.execute(_INSERT, tuple(r[c] for c in rf.COLUMNS))
        written += 1
    print(f"written: {written}, already present (skipped): {skipped}")
    return 0


def _schema_statements() -> list[str]:
    from scripts import apply_library_migration as mig

    schema = Path(__file__).resolve().parents[1] / "database" / "library" / "0002_research_fact.sql"
    return list(mig.statements(schema.read_text(encoding="utf-8")))


_DUP = "SELECT COUNT(*) AS n FROM research_fact WHERE company = ? AND topic = ? AND fact_text = ?"
_INSERT = ("INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name, "
           "source_url, source_date, as_of, confidence, created_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capsule", type=Path)
    parser.add_argument("--apply", action="store_true", help="write to psx-library (default: dry run)")
    args = parser.parse_args(argv)
    try:
        return absorb(args.capsule, apply=args.apply)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2
    except rf.ResearchFactError as exc:
        print(f"REFUSED: {exc}")
        return 7


if __name__ == "__main__":
    sys.exit(main())
