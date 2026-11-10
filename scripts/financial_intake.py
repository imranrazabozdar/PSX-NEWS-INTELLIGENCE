"""Real-report intake: vault placement, extraction, evidence, reconciliation, metrics. One PDF per run.

Only owner-supplied documents are accepted. This tool fetches nothing.

Example (PSXNI_DOCUMENT_VAULT must name a directory OUTSIDE the repository and outside both databases):

  export PSXNI_DOCUMENT_VAULT=/secure/psx-vault
  python -m scripts.financial_intake \\
      --file /path/to/OGDC-annual-report-2025.pdf \\
      --symbol OGDC --period-end 2025-06-30 --columns 2025-06-30,2024-06-30 \\
      --unit-scale 1000 --consolidation unconsolidated --company-id <operational company id>

Optional prior-year comparison (the earlier filing, owner-supplied):

      --prior-file /path/to/OGDC-annual-report-2024.pdf --prior-period 2024-06-30 \\
      --prior-columns 2024-06-30,2023-06-30 --prior-unit-scale 1000

Default: stores the PDF in the vault (an identical file is reported as a duplicate, never stored twice),
analyses it and prints a JSON report. It writes NO database.

--archive also writes the analysis to the archive database. It needs PSXNI_ARCHIVE_TURSO_URL and
PSXNI_ARCHIVE_TURSO_AUTH_TOKEN, a fully migrated archive (the readiness check refuses otherwise), and it never
runs DDL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from engines import document_intake as di
from engines import notes_extraction as ne
from engines import pdf_extraction as pe
from engines import statement_pipeline as sp

EXTRACTOR_VERSION = "pdfplumber-0.11.10/pipeline-2026.11.1"
VAULT_ENV = "PSXNI_DOCUMENT_VAULT"


class IntakeRefused(RuntimeError):
    pass


def vault_from_env() -> Path:
    raw = os.environ.get(VAULT_ENV, "")
    if not raw:
        raise IntakeRefused(f"{VAULT_ENV} is not set: name a vault directory outside the repository")
    return di.vault_dir(raw)


def _stored_pdf(vault: Path, pdf: Path) -> tuple[dict, Path]:
    """Place the PDF in the vault, then verify the stored bytes before anything is analysed."""
    stored = di.store_manual_upload(pdf, vault)
    di.read_verified(vault, stored["report_sha256"])  # raises if the vault copy does not match its hash
    return stored, vault / stored["vault_ref"]


def _tagged(
    path: Path,
    *,
    sha: str,
    symbol: str,
    period_end: str,
    columns: list[str],
    unit_scale: int,
    currency: str,
    consolidation: str,
) -> tuple[dict, dict]:
    doc = pe.extract(path)
    ex = sp.extract(doc, columns=columns)
    document = {
        "document_id": sha,
        "file_hash": sha,
        "symbol": symbol,
        "period_end": period_end,
        "currency": currency,
        "unit_scale": unit_scale,
        "consolidation": consolidation,
        "restated_flag": False,
    }
    return sp.tag(ex, document=document, extractor_version=EXTRACTOR_VERSION, mapping=sp.load_mappings()), ex


def analyse(
    vault: Path,
    pdf: Path,
    *,
    symbol: str,
    period_end: str,
    columns: list[str],
    unit_scale: int,
    currency: str,
    consolidation: str,
    prior_spec: dict | None = None,
) -> dict:
    stored, path = _stored_pdf(vault, pdf)
    sha = stored["report_sha256"]
    tagged, ex = _tagged(
        path,
        sha=sha,
        symbol=symbol,
        period_end=period_end,
        columns=columns,
        unit_scale=unit_scale,
        currency=currency,
        consolidation=consolidation,
    )
    prior = None
    prior_report = None
    if prior_spec:
        p_stored, p_path = _stored_pdf(vault, prior_spec["file"])
        p_sha = p_stored["report_sha256"]
        p_tagged, _ = _tagged(
            p_path,
            sha=p_sha,
            symbol=symbol,
            period_end=prior_spec["period"],
            columns=prior_spec["columns"],
            unit_scale=prior_spec["unit_scale"],
            currency=currency,
            consolidation=consolidation,
        )
        prior = {**p_tagged, "period": prior_spec["period"]}
        prior_report = {"vault": p_stored["status"], "report_sha256": p_sha, "period": prior_spec["period"]}
    recon = sp.reconcile(tagged, period_end=period_end, prior=prior)
    metrics = sp.compute_metrics(tagged, period_end=period_end, prior=prior)
    notes_view = {"lines": ex["note_lines"], "notes": ex["note_index"]}
    receivables = ne.receivables_quality(notes_view, period_end)
    contingencies = ne.contingency_summary(notes_view, period_end)
    diagnostic = build_diagnostic(tagged, recon, ex["audit"], receivables, contingencies)
    return {
        "diagnostic": diagnostic,
        "receivables": receivables,
        "contingencies": contingencies,
        "vault": {
            "status": stored["status"],
            "report_sha256": sha,
            "vault_ref": stored["vault_ref"],
            "size_bytes": stored["size_bytes"],
        },
        "prior_filing": prior_report,
        "pages": ex["pages"],
        "statement_pages": ex["statement_pages"],
        "scanned_pages_needing_ocr": ex["scanned_pages"],
        "lines": {
            "statement": sum(1 for x in tagged["lines"] if x["statement_type"] != "NOTE"),
            "note": sum(1 for x in tagged["lines"] if x["statement_type"] == "NOTE"),
            "unparsed": len(tagged["unparsed"]) + len(ex["note_unparsed"]),
        },
        "reconciliation": {
            "overall": recon["overall"],
            "checks": recon["checks"],
            "conflicts": recon["conflicts"],
        },
        "metrics": [{k: m[k] for k in ("metric", "value", "missing")} for m in metrics],
        "auditor": sp.audit_payload(ex["audit"]),
        "_tagged": tagged,
        "_recon": recon,
        "_audit": ex["audit"],
        "_sha": sha,
        "_size": stored["size_bytes"],
    }


def build_diagnostic(tagged: dict, recon: dict, audit: dict, receivables: dict, contingencies: dict) -> dict:
    """A short, plain summary: what mapped, what did not, what reconciled, and what the auditor said."""
    stmt = [x for x in tagged["lines"] if x["statement_type"] != "NOTE"]
    notes = [x for x in tagged["lines"] if x["statement_type"] == "NOTE"]
    status = {c["check"]: c["status"] for c in recon["checks"]}
    return {
        "statement_lines": {
            "mapped": sum(1 for x in stmt if x["canonical_code"]),
            "unmapped": sum(1 for x in stmt if not x["canonical_code"]),
        },
        "disclosure_lines": {
            "mapped": sum(1 for x in notes if x["canonical_code"]),
            "unmapped": sum(1 for x in notes if not x["canonical_code"]),
        },
        "unparsed_lines": len(tagged["unparsed"]),
        "reconciliation": {
            "balance_sheet": status.get("balance_sheet", "not_run"),
            "cash_flow": status.get("cash_flow", "not_run"),
            "overall": recon["overall"],
        },
        "auditor_opinion": audit["opinion"].get("opinion"),
        "key_audit_matters": [
            {"heading": k["heading"], "page": k["page"], "excerpt": k["excerpt"][:160]} for k in audit["kams"]
        ],
        "receivables": {
            "gross": receivables["gross_trade_debts"],
            "ecl_coverage": receivables["ecl_coverage_ratio"],
            "overdue_percentage": receivables["overdue_percentage"],
            "overdue_over_90": receivables["overdue_over_90_ratio"],
            "unclassified_brackets": receivables["unclassified_brackets"],
        },
        "contingencies": {k: round(v["total_reported"], 2) for k, v in contingencies["by_type"].items()},
        "contingencies_recognised_on_balance_sheet": contingencies["recognised_on_balance_sheet"],
    }


def render_text(out: dict) -> str:
    d = out["diagnostic"]
    rec = d["reconciliation"]
    r = d["receivables"]
    lines = [
        f"Vault: {out['vault']['status']} {out['vault']['vault_ref']}  pages: {out['pages']}",
        f"Statement lines: {d['statement_lines']['mapped']} mapped, "
        f"{d['statement_lines']['unmapped']} unmapped",
        f"Disclosure lines: {d['disclosure_lines']['mapped']} mapped, "
        f"{d['disclosure_lines']['unmapped']} kept unmapped",
        f"Unparsed lines (for review): {d['unparsed_lines']}",
        f"Reconciliation: balance sheet {rec['balance_sheet']}, cash flow {rec['cash_flow']}, "
        f"overall {rec['overall']}",
        f"Auditor opinion: {d['auditor_opinion']}",
    ]
    lines += [f"  KAM p.{k['page']}: {k['heading']} - {k['excerpt']}" for k in d["key_audit_matters"]]
    lines.append(
        f"Receivables: gross {r['gross']}, ECL coverage {r['ecl_coverage']}, "
        f"overdue {r['overdue_percentage']}, over 90 days {r['overdue_over_90']}"
    )
    if r["unclassified_brackets"]:
        lines.append(f"  unclassified ageing rows (kept, not bucketed): {r['unclassified_brackets']}")
    lines.append(f"Contingent items (not recognised): {d['contingencies'] or 'none found'}")
    return "\n".join(lines)


def store_in_archive(
    out: dict, *, symbol: str, company_id: str, consolidation: str, period_end: str, original_name: str
) -> dict:
    from database import financial_repo as repo
    from database.connection import connect_archive

    adb = connect_archive()
    try:
        repo.require_archive_ready(adb)
        meta = {
            "report_sha256": out["_sha"],
            "psx_symbol": symbol,
            "company_id": company_id or f"unassigned-{symbol}",
            "doc_type": "annual",
            "financial_year": int(period_end[:4]),
            "period_end": period_end,
            "consolidation": consolidation,
            "audit_status": "unknown",
            "original_filename": di.safe_filename(original_name),
            "vault_ref": out["vault"]["vault_ref"],
            "source_id": "company_reports_manual",
            "retrieved_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        res = sp.store(
            adb,
            registry_meta=meta,
            file_size_bytes=out["_size"],
            tagged=out["_tagged"],
            reconciliation=out["_recon"],
            extractor_version=EXTRACTOR_VERSION,
            audit=out["_audit"],
        )
        return {
            "status": "stored",
            "run_id": res["run_id"],
            "run": res["run"],
            "lines": res["lines"],
            "processing_status": res["status"],
        }
    finally:
        adb.close()


def _parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, type=Path, help="owner-supplied annual report (PDF)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--period-end", required=True)
    ap.add_argument("--columns", required=True, help="comma-separated period ends, current period first")
    ap.add_argument("--unit-scale", required=True, type=int, choices=(1, 1000, 1000000, 1000000000))
    ap.add_argument("--currency", default="PKR")
    ap.add_argument("--consolidation", required=True, choices=("consolidated", "unconsolidated"))
    ap.add_argument("--company-id", default="", help="company id from the operational database")
    ap.add_argument("--prior-file", type=Path)
    ap.add_argument("--prior-period")
    ap.add_argument("--prior-columns")
    ap.add_argument("--prior-unit-scale", type=int, choices=(1, 1000, 1000000, 1000000000))
    ap.add_argument("--archive", action="store_true", help="also write the analysis to the archive database")
    ap.add_argument("--text", action="store_true", help="print the diagnostic summary as text, not JSON")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        vault = vault_from_env()
        symbol = args.symbol.upper()
        columns = [c.strip() for c in args.columns.split(",") if c.strip()]
        if args.period_end not in columns:
            raise IntakeRefused("--period-end must appear in --columns")
        prior_spec = None
        if args.prior_file:
            if not (args.prior_period and args.prior_columns and args.prior_unit_scale):
                raise IntakeRefused(
                    "--prior-file needs --prior-period, --prior-columns and --prior-unit-scale"
                )
            prior_spec = {
                "file": args.prior_file,
                "period": args.prior_period,
                "columns": [c.strip() for c in args.prior_columns.split(",") if c.strip()],
                "unit_scale": args.prior_unit_scale,
            }
        out = analyse(
            vault,
            args.file,
            symbol=symbol,
            period_end=args.period_end,
            columns=columns,
            unit_scale=args.unit_scale,
            currency=args.currency,
            consolidation=args.consolidation,
            prior_spec=prior_spec,
        )
        if args.archive:
            try:
                out["archive"] = store_in_archive(
                    out,
                    symbol=symbol,
                    company_id=args.company_id,
                    consolidation=args.consolidation,
                    period_end=args.period_end,
                    original_name=args.file.name,
                )
            except Exception as exc:  # a configuration or readiness refusal: report it, write nothing more
                print(
                    json.dumps(
                        {"status": "archive_refused", "error": type(exc).__name__, "detail": str(exc)[:300]}
                    )
                )
                return 2
        if args.text:
            print(render_text(out))
        else:
            print(
                json.dumps(
                    {k: v for k, v in out.items() if not k.startswith("_")},
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
        return 0
    except (IntakeRefused, di.IntakeError, di.VaultIntegrityError) as exc:
        print(json.dumps({"status": "refused", "error": type(exc).__name__, "detail": str(exc)[:400]}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
