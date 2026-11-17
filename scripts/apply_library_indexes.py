"""Create or drop the approved indexes on psx-library (migrations 0010 and 0011), and nothing else.

Guarded like the other library migrations: the connection goes through engines.library_db (target guard),
and only statements on the allowlist below may run. Building an index reads and writes every row once, so
run it on its own, outside a collector run, with the budgets raised for this one job:

    PSXNI_DB_MAX_ROWS_WRITTEN=120000 PSXNI_DB_MAX_ROWS_READ=120000 \
        python -m scripts.apply_library_indexes 0011
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

from engines import library_db

DIR = Path(__file__).resolve().parents[1] / "database" / "library"
FILES = {
    "0010": "0010_research_fact_index.sql",
    "0011": "0011_research_fact_company_date_index.sql",
}
_CREATE = "CREATE INDEX IF NOT EXISTS"
_ALLOWED = tuple(
    re.compile(f"^{text}$", re.I)
    for text in (
        rf"{_CREATE} idx_research_fact_company ON research_fact \(company, topic\)",
        rf"{_CREATE} idx_research_fact_company_date ON research_fact \(company, source_date\)",
        rf"{_CREATE} idx_news_item_published ON news_item \(published_at\)",
        r"DROP INDEX IF EXISTS idx_research_fact_company",
    )
)


def statements(sql: str) -> list[str]:
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    out = [s.strip() for s in body.split(";") if s.strip()]
    for stmt in out:
        if not any(p.match(" ".join(stmt.split())) for p in _ALLOWED):
            raise ValueError(f"refused: not an approved index statement: {stmt[:70]!r}")
    return out


def apply(key: str, environ: Mapping[str, str] | None = None, db=None) -> int:
    if key not in FILES:
        print(f"unknown migration {key!r}; choose one of {sorted(FILES)}")
        return 2
    todo = statements((DIR / FILES[key]).read_text(encoding="utf-8"))
    if db is None:
        try:
            conn = library_db.get_library_connection(environ)  # target guard runs here
        except library_db.LibraryConfigError as exc:
            print(f"index REFUSED: {exc}")
            return 2
        db = conn.db
    for stmt in todo:
        db.execute(stmt)
    print(f"{key}: {len(todo)} statement(s) applied")
    return 0


if __name__ == "__main__":
    sys.exit(apply(sys.argv[1] if len(sys.argv) > 1 else "0011"))
