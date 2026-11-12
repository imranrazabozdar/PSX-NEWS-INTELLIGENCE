"""Load one ticker's distilled research facts into psx-library research_fact.

Validate every row (engines/research_facts.py). Open psx-library through engines/library_db.py, where the
target guard runs first. Apply the approved research_fact schema (CREATE TABLE IF NOT EXISTS only). Insert
the rows, then read back the count per topic and five samples. Refuses to load a ticker twice.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engines import library_db
from engines import research_facts as rf
from scripts import apply_library_migration as mig

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0002_research_fact.sql"
INSERT = ("INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name, "
          "source_url, source_date, as_of, confidence, created_at) "
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def load_rows(path: Path, ticker: str) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise rf.ResearchFactError("the facts file must be a non-empty JSON list")
    clean = []
    for row in rows:
        checked = rf.validate_fact(row)
        if checked["company"] != ticker:
            raise rf.ResearchFactError(f"row for {checked['company']!r} in the {ticker} file: refused")
        clean.append(checked)
    return clean


def load(ticker: str, facts: Path, environ: Mapping[str, str] | None = None, db: Any = None) -> int:
    """Return 0 on success. db is for tests only; production always goes through library_db."""
    rows = load_rows(facts, ticker)
    if db is None:
        conn = library_db.get_library_connection(environ)  # target guard runs here
        db, host = conn.db, conn.host
    else:
        host = "test-database"
    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    existing = db.execute("SELECT COUNT(*) AS n FROM research_fact WHERE company = ?", (ticker,))[0]["n"]
    if existing:
        print(f"refused: {existing} row(s) for {ticker} already exist; this loader does not load twice")
        return 6
    for row in rows:
        db.execute(INSERT, tuple(row[c] for c in rf.COLUMNS))
    print(f"research_fact loaded for {ticker} -> host={host}: {len(rows)} row(s) inserted")
    counts = db.execute("SELECT topic, COUNT(*) AS n FROM research_fact WHERE company = ? "
                        "GROUP BY topic ORDER BY topic", (ticker,))
    print("count per topic:")
    for r in counts:
        print(f"  {r['topic']}: {r['n']}")
    print("five sample rows:")
    sample_sql = ("SELECT id, topic, fact_text, value, unit, period, source_name, source_date, confidence "
                  "FROM research_fact WHERE company = ? ORDER BY id LIMIT 5")
    for r in db.execute(sample_sql, (ticker,)):
        print(f"  {dict(r)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--facts", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return load(args.ticker, args.facts)
    except library_db.LibraryConfigError as exc:
        print(f"load REFUSED: {exc}")
        return 2
    except rf.ResearchFactError as exc:
        print(f"load REFUSED: {exc}")
        return 7


if __name__ == "__main__":
    sys.exit(main())
