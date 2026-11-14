"""Copy distilled facts from the extracted annual-report fixtures into psx-library.

Reads only the reconciliation fixtures in tests/fixtures/real_reports (manifest + expected values), which were
produced from the owner's uploaded PDFs. No PDF text and no page images are stored: each row is one printed
figure or key audit matter, with its page cited. Writes through the guarded connection
(engines/library_db.py). A report already present for that company and statement date is skipped.
Default is a dry run; pass --apply to write.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines import library_db
from engines import research_facts as rf

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_reports"
REPORTS = {"luck_ar2026": "LUCK", "ogdc_ar2026_standalone": "OGDC", "ubl_ar2025": "UBL"}


def report_rows(created_at: str) -> list[tuple[str, str, list[dict]]]:
    out = []
    for key, company in sorted(REPORTS.items()):
        base = FIXTURES / key
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        expected = json.loads((base / "expected.json").read_text(encoding="utf-8"))
        rows = rf.rows_from_report(company=company, manifest=manifest, expected=expected,
                                   created_at=created_at)
        out.append((key, company, rows))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write to psx-library (default: dry run)")
    args = ap.parse_args(argv)
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    reports = report_rows(created)
    for key, company, rows in reports:
        figures = sum(1 for r in rows if r["topic"] == "report.figure")
        print(f"{key:<26} {company:<5} {len(rows)} rows ({figures} figures, {len(rows) - figures} KAMs)")
    if not args.apply:
        print("dry run: nothing written")
        return 0
    try:
        conn = library_db.get_library_connection()  # target guard runs here
    except library_db.LibraryConfigError as exc:
        print(f"import REFUSED: {exc}")
        return 2
    library_db.auth_check(conn)
    for key, company, rows in reports:
        if not rows:
            print(f"{key:<26} skipped: no rows")
            continue
        present = conn.db.execute(
            "SELECT COUNT(*) AS n FROM research_fact WHERE company = ? AND topic LIKE 'report.%' "
            "AND source_date = ?", (company, rows[0]["source_date"]))[0]["n"]
        if present:
            print(f"{key:<26} skipped: {present} rows already in psx-library for that statement date")
            continue
        print(f"{key:<26} wrote {rf.insert_rows(conn.db, rows)} rows")
    print(f"import finished on host={conn.host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
