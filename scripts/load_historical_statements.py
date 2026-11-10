"""Historical loader: pre-parsed JSON statement summaries to the archive database. No PDFs.

Input: a directory of JSON files, one annual summary per file (owner-supplied, from a permitted route).
Schema:
  {"ticker": "OGDC", "period_end": "2025-06-30", "doc_type": "annual", "scope": "unconsolidated",
   "currency": "PKR", "unit_scale": 1000, "audit_status": "audited", "provenance": "owner_supplied",
   "source_note": "where the owner obtained the summary",
   "metrics": {"total_assets": 500, "total_liabilities": 300, "total_equity": 200, ...}}

Behaviour:
* Dry run by default. Nothing is written unless --write is given.
* Each file is validated (fields, provenance, identities) before anything is written. Refused files are
  reported.
* Ticker resolution reads the operational database; nothing is written there.
* Writes go to the archive database only, one transaction per summary. Re-running is idempotent.
* Files declared "synthetic_fixture" are refused unless --allow-synthetic (tests and demonstrations only).

Usage:
  python -m scripts.load_historical_statements --dir DIR            # dry run
  python -m scripts.load_historical_statements --dir DIR --write    # needs PSXNI_* main and archive variables
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from database import financial_repo as repo
from database import repositories as reps


def load_directory(main_db, archive_db, directory: Path, *, write: bool,
                   allow_synthetic: bool = False) -> list[dict]:
    results = []
    for path in sorted(Path(directory).glob("*.json")):
        item = {"file": path.name}
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            results.append({**item, "status": "refused",
                            "reasons": [f"unreadable JSON: {type(exc).__name__}"]})
            continue
        if summary.get("provenance") == "synthetic_fixture" and not allow_synthetic:
            results.append({**item, "status": "refused",
                            "reasons": ["synthetic fixture: pass --allow-synthetic for tests only"]})
            continue
        v = repo.validate_summary(summary)
        if not v["ok"]:
            results.append({**item, "status": "refused", "reasons": v["reasons"]})
            continue
        company = reps.company_by_ticker(main_db, str(summary["ticker"]))
        if company is None:
            results.append({**item, "status": "refused",
                            "reasons": [f"ticker {summary['ticker']!r} is not in the company master"]})
            continue
        if not write:
            results.append({**item, "status": "would_archive", "ticker": summary["ticker"],
                            "period_end": summary["period_end"],
                            "metrics": sum(1 for x in summary["metrics"].values() if x is not None)})
            continue
        out = repo.archive_summary(archive_db, summary, company_id=company["company_id"])
        results.append({**item, "status": "archived" if out.get("archived") else "refused",
                        "archived_metrics": out.get("archived", 0), "reasons": out.get("refused", [])})
    return results


def main(argv: list[str] | None = None) -> int:
    from database.connection import connect_archive, connect_main

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--write", action="store_true", help="write to the archive database (default: dry run)")
    ap.add_argument("--allow-synthetic", action="store_true", help="accept synthetic fixtures (tests only)")
    args = ap.parse_args(argv)
    mdb = connect_main()
    adb = None
    try:
        if args.write:
            adb = connect_archive()
            repo.migrate_archive(adb)
        results = load_directory(mdb, adb, args.dir, write=args.write, allow_synthetic=args.allow_synthetic)
    finally:
        mdb.close()
        if adb is not None:
            adb.close()
    for r in results:
        print(json.dumps(r, sort_keys=True))
    refused = sum(1 for r in results if r["status"] == "refused")
    print(json.dumps({"files": len(results), "refused": refused, "write": args.write}))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
