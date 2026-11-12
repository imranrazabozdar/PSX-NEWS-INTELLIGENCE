"""Validation report for the Investify scale-validation batch.

Reads the progress file and the structured records in the operational database, rates each dataset per company
(OK / partial / failed / not run) with the reason, and flags extractor breakage: a transient copy whose
embedded payload lacks the markers the extractors rely on. Deletes the transient copies after checking them.

  python -m scripts.investify_validation_report --db <operational.sqlite> --progress <progress.jsonl> \
      --scratch <dir> [--delete-copies]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from scripts.investify_validation_run import COMPANIES, ENDPOINTS

FUND_MIN = 15  # a complete card page yields 19 to 25 metric cards for these companies
PROFILE_KEYS = ("sector", "leadership", "market_structure", "share_float_split", "registered_address",
                "description")


def _record(db, sym: str, ep: str) -> dict | None:
    rows = db.execute("SELECT source_metadata_json FROM source_items WHERE source_id = ? AND "
                      "(external_id = ? OR external_id LIKE ?) ORDER BY collected_at_utc DESC LIMIT 1",
                      ("investify_fundamentals", f"{sym}:{ep}", f"{sym}:{ep}:%"))
    return json.loads(rows[0]["source_metadata_json"]).get("fields") if rows else None


def _markers(copy: Path) -> dict[str, bool]:
    text = copy.read_text(encoding="utf-8", errors="replace")
    return {"next_flight": "self.__next_f" in text, "json_ld": "application/ld+json" in text,
            "symbol_index": '"sector":"' in text}


def rate(ep: str, progress: dict | None, fields: dict | None, copy: Path | None) -> tuple[str, str]:
    if progress is None:
        return "not run", "no request made"
    if progress["status"] == "skipped":
        return "not run", progress["reason"]
    if progress["status"] != "fetched":
        return "failed", f"{progress['status']}: {progress['reason']}"
    if fields is None:
        return "failed", "stored record has no structured fields"
    if ep == "announcements":
        items = fields.get("items", [])
        qualifying = [i for i in items if i.get("category") in ("financial_results", "report_transmission")]
        if not items:
            return "failed", "no items parsed"
        return "OK", f"{len(items)} items; {len(qualifying)} qualifying; page {fields.get('page')} of " \
                     f"{fields.get('pages_total')}"
    if ep == "fundamentals":
        n = fields.get("metric_count", 0)
        if n >= FUND_MIN:
            return "OK", f"{n} metric cards"
        if n > 0:
            return "partial", f"only {n} metric cards (expected about {FUND_MIN} or more)"
        return "failed", "no metric cards parsed"
    if ep == "profile":
        missing = [k for k in PROFILE_KEYS if not fields.get(k)]
        if not missing:
            return "OK", "all profile fields"
        if len(missing) < len(PROFILE_KEYS):
            return "partial", "missing: " + ", ".join(missing)
        return "failed", "no profile fields parsed"
    if ep == "competitors":
        if fields.get("peer_count", 0) > 0 and fields.get("sector"):
            return "OK", f"{fields['peer_count']} same-sector peers ({fields['sector']})"
        return "failed", "no sector or no peers in the embedded index"
    return "failed", "unknown endpoint"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Investify validation report")
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--progress", required=True, type=Path)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--delete-copies", action="store_true")
    args = ap.parse_args(argv)
    db = SQLiteDatabase(str(args.db))
    migrate(db)
    seed_loader.load(db)
    prog: dict[tuple[str, str], dict] = {}
    if args.progress.exists():
        for line in args.progress.read_text(encoding="utf-8").splitlines():
            if line:
                r = json.loads(line)
                prog[(r["symbol"], r["endpoint"])] = r
    table = {}
    for sym in COMPANIES:
        for ep in ENDPOINTS:
            copy = args.scratch / f"{sym}_{ep}.html"
            copy_path = copy if copy.exists() else None
            status, reason = rate(ep, prog.get((sym, ep)), _record(db, sym, ep), copy_path)
            if copy_path and status == "failed":
                reason += f" [markers: {_markers(copy_path)}]"
            table[(sym, ep)] = (status, reason)
            if args.delete_copies and copy_path:
                copy_path.unlink()
    print("| Company | " + " | ".join(ENDPOINTS) + " |")
    print("|---|" + "---|" * len(ENDPOINTS))
    for sym in COMPANIES:
        cells = " | ".join(f"{table[(sym, ep)][0]}: {table[(sym, ep)][1]}" for ep in ENDPOINTS)
        print(f"| {sym} | {cells} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
