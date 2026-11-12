"""Batch extraction and reconciliation for fetched investor-relations reports, with a coverage record.

Reads the vault manifest (written by engines/ir_fetcher.py). For each fetched PDF it runs the existing
pipeline
(pdf_reader -> extraction -> statement_pipeline) and records, per statement and per identity, the status
with its
reason. Facts are written to a THROWAWAY LOCAL SQLite archive. This script never connects to a Turso or
production
database. Every failure is recorded as a status and the batch continues.

  python -m scripts.run_ir_batch --vault <dir> --db <throwaway.sqlite> --out <coverage.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase
from engines import pdf_reader
from engines import report_metadata as rm
from engines import statement_pipeline as sp
from engines.document_intake import safe_filename
from scripts import financial_intake as fi

STATEMENTS = ("BS", "IS", "OCI", "CF", "EQ")
GREEN = frozenset({"reconciled", "reconciled_with_rounding"})
EXTRACTOR = fi.EXTRACTOR_VERSION


def open_throwaway_archive(path: Path) -> SQLiteDatabase:
    """A local SQLite file, outside the repository, with the archive migrations applied through the gate."""
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    adb = SQLiteDatabase(str(path))
    adb.role = "archive"
    gate.apply(adb, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    return adb


def _record(row: dict, status: str, reason: str, **extra: Any) -> dict:
    base = {
        "symbol": row["symbol"],
        "report_type": row["report_type"],
        "period_end": row["period_end"],
        "fiscal_label": row.get("fiscal_label"),
        "pdf_url": row.get("pdf_url"),
        "sha256": row.get("sha256"),
        "status": status,
        "reason": reason,
        "statements": {s: "not_extracted" for s in STATEMENTS},
        "identities": {},
        "statement_pages": {},
    }
    base.update(extra)
    return base


def process(row: dict, *, vault: Path, adb: SQLiteDatabase, now: datetime) -> dict:
    pdf = vault / row["vault_path"]
    try:
        doc = pdf_reader.read(pdf)
    except (ValueError, OSError) as exc:
        return _record(row, "insufficient_data", f"not a readable PDF: {exc}")
    if not any(p.has_text for p in doc.pages):
        return _record(row, "insufficient_data", "no text layer (image-only PDF)")
    layout = rm.detect_layout(doc, row["period_end"])
    pages = {k: v for k, v in layout.get("statement_pages", {}).items()}
    if layout["missing"]:
        return _record(row, "requires_review", "; ".join(layout["missing"]), statement_pages=pages)
    try:
        out = fi.analyse(
            vault,
            pdf,
            symbol=row["symbol"],
            period_end=row["period_end"],
            columns=layout["columns"],
            unit_scale=layout["unit_scale"],
            currency=layout["currency"],
            consolidation=layout["consolidation"],
        )
    except Exception as exc:  # a layout the pipeline does not handle is recorded, not fatal
        return _record(
            row,
            "requires_review",
            f"extraction did not complete: {type(exc).__name__}: {exc}",
            statement_pages=pages,
        )
    statements, _facts = sp.statuses_for(out["_tagged"], out["_recon"], ias7_status=out.get("_ias7"))
    identities = sp.identity_rows(out["_recon"], consolidation=layout["consolidation"])
    stmt_status: dict[str, str] = {}
    for s in statements:
        if s["column_period_end"] == row["period_end"]:
            stmt_status[s["statement_type"]] = s["status"]
    store_note = ""
    try:
        meta = {
            "report_sha256": out["_sha"],
            "psx_symbol": row["symbol"],
            "company_id": f"unassigned-{row['symbol']}",
            "doc_type": "annual" if row["report_type"] == "annual_report" else "interim",
            "financial_year": int(row["fiscal_year"]),
            "period_end": row["period_end"],
            "consolidation": layout["consolidation"],
            "audit_status": "unknown",
            "original_filename": safe_filename(pdf.name),
            "vault_ref": out["vault"]["vault_ref"],
            "source_id": "ir_fetcher_batch",
            "retrieved_at_utc": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        sp.store(
            adb,
            registry_meta=meta,
            file_size_bytes=out["_size"],
            tagged=out["_tagged"],
            reconciliation=out["_recon"],
            extractor_version=EXTRACTOR,
            audit=out["_audit"],
            ias7_status=out.get("_ias7"),
        )
    except Exception as exc:
        store_note = f"; fact store refused: {type(exc).__name__}: {exc}"
    located = layout["statement_pages"]
    statements_out = {s: stmt_status.get(s, "not_extracted") for s in STATEMENTS}
    for code in ("BS", "IS", "CF", "EQ"):
        if code not in located:
            statements_out[code] = "not_extracted"
    worst = "reconciled"
    order = [
        "unreconciled",
        "requires_review",
        "not_verifiable_from_disclosure",
        "insufficient_data",
        "unmapped",
        "reconciled_with_rounding",
        "reconciled",
    ]
    for s in statements_out.values():
        if s == "not_extracted":
            continue
        if s in order and order.index(s) < order.index(worst):
            worst = s
    extracted = [v for v in statements_out.values() if v != "not_extracted"]
    status = worst if extracted else "insufficient_data"  # nothing extracted is never reported as reconciled
    reason = "statements extracted; see per-statement status" + store_note
    return _record(
        row,
        status,
        reason,
        statements=statements_out,
        identities={i["identity"]: i["status"] for i in identities},
        identity_detail=[
            {
                "identity": i["identity"],
                "column": i["column_period_end"],
                "status": i["status"],
                "reason": i["reason"],
            }
            for i in identities
        ],
        statement_pages=located,
        columns=layout["columns"],
        unit_scale=layout["unit_scale"],
        consolidation=layout["consolidation"],
        extracted_lines=len(out["_tagged"]["lines"]),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extraction and reconciliation batch for fetched IR reports")
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path, help="throwaway local SQLite file (never a Turso URL)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--symbols", nargs="*")
    args = ap.parse_args(argv)
    if "://" in str(args.db):
        print("refused: the throwaway archive must be a local file", file=sys.stderr)
        return 2
    manifest = [
        json.loads(x) for x in (args.vault / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x
    ]
    rows = [
        r
        for r in manifest
        if r.get("source") == "ir_fetch" and (not args.symbols or r["symbol"] in args.symbols)
    ]
    adb = open_throwaway_archive(args.db)
    now = datetime.now(UTC)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for row in rows:
            try:
                rec = process(row, vault=args.vault, adb=adb, now=now)
            except Exception as exc:  # the batch never stops on one report
                rec = _record(row, "requires_review", f"unexpected: {type(exc).__name__}: {exc}")
            results.append(rec)
    finally:
        adb.close()
    with args.out.open("w", encoding="utf-8") as fh:
        for rec in results:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"reports": len(results), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
