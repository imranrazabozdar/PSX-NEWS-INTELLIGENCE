"""Absorb one sector knowledge capsule into psx-library research_fact.

A capsule is a JSON list of research_fact rows (see engines/research_facts.py). Default is a DRY RUN: it
validates every row, prints counts per company, and writes nothing. --apply writes, skipping any row that is
already known: an exact repeat, or a NEAR-duplicate of a row stored for the same company and topic family.
That second check is what lets a company's profile be updated by later capsules without restating itself.
Placeholder sources are refused.
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
from scripts.prepare_transcript_capsule import is_near_duplicate, normalise

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
    written = skipped = near = 0
    exact, known = _existing(db, {r["company"] for r in rows})
    pending: list[tuple[Any, ...]] = []
    for r in rows:
        if (r["company"], r["topic"], r["fact_text"]) in exact:
            skipped += 1
            continue
        words = normalise(r["fact_text"])
        family = r["topic"].split(".", 1)[0]
        bucket = known.setdefault((r["company"], family), [])
        if any(is_near_duplicate(words, prior) for prior in bucket):
            near += 1
            continue
        exact.add((r["company"], r["topic"], r["fact_text"]))
        bucket.append(words)  # later rows in this capsule compare against it too
        pending.append(tuple(r[c] for c in rf.COLUMNS))
        written += 1
    for i in range(0, len(pending), BATCH):
        db.batch([(_INSERT, params) for params in pending[i:i + BATCH]], transactional=True)
    print(f"written: {written}, exact repeats skipped: {skipped}, near-duplicates skipped: {near}")
    return 0


def _schema_statements() -> list[str]:
    from scripts import apply_library_migration as mig

    schema = Path(__file__).resolve().parents[1] / "database" / "library" / "0002_research_fact.sql"
    return list(mig.statements(schema.read_text(encoding="utf-8")))


BATCH = 200  # statements per transactional batch: a few dozen round trips instead of thousands


def _existing(db: Any, companies: set[str]) -> tuple[set[tuple[str, str, str]],
                                                      dict[tuple[str, str], list[frozenset[str]]]]:
    """What is already stored for these companies, read once: exact keys, and word bags per topic family."""
    exact: set[tuple[str, str, str]] = set()
    known: dict[tuple[str, str], list[frozenset[str]]] = {}
    names = sorted(companies)
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        marks = ", ".join("?" for _ in chunk)
        # only "?" placeholders are interpolated; every value is bound separately
        sql = f"SELECT company, topic, fact_text FROM research_fact WHERE company IN ({marks})"  # noqa: S608
        for row in db.execute(sql, tuple(chunk)):
            exact.add((row["company"], row["topic"], row["fact_text"]))
            known.setdefault((row["company"], str(row["topic"]).split(".", 1)[0]), []).append(
                normalise(str(row["fact_text"])))
    return exact, known


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
