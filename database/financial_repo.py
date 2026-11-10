"""Financial statement history repository. Bound to the ARCHIVE database only.

* `archive_promoted` copies one RECONCILED report's promoted metrics from the operational staging tables into
  the archive as normalised tuples (company_id, period_end_date, metric_name, value, unit). It reads the
  operational database and writes the archive. It is idempotent on the document SHA-256.
* `annual_series` and `year_gaps`-based reads query the archive only.

Routing rule: every function here takes an archive handle and an operational handle where it needs both, and
checks each handle's role before touching it. Raw PDF bytes never reach this module: only the SHA-256 and the
vault file name are stored.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from database.migrate import migrate
from engines import financials as fin
from engines.financial_series import year_gaps

ARCHIVE_MIGRATIONS = Path(__file__).resolve().parent / "archive_migrations"


class ArchiveRoutingError(RuntimeError):
    """A handle with the wrong role was passed to a repository. Nothing is read or written."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_role(db, role: str) -> None:
    got = getattr(db, "role", None)
    if got != role:
        raise ArchiveRoutingError(f"this operation needs the {role!r} database handle, got {got!r}")


def migrate_archive(adb) -> list[str]:
    """Apply archive migrations with the archive's own ledger. Refuses a non-archive handle."""
    require_role(adb, "archive")
    return migrate(adb, directory=ARCHIVE_MIGRATIONS)


def archive_promoted(main_db, archive_db, report_id: int) -> dict:
    """Copy one reconciled report's promoted metrics into the archive. Idempotent on the document hash."""
    require_role(main_db, "main")
    require_role(archive_db, "archive")
    rep = main_db.execute(
        "SELECT fr.report_id, fr.company_id, fr.doc_type, fr.period_end, fr.scope, fr.currency, "
        "fr.unit_scale, "
        "fr.audit_status, fr.extraction_status, si.content_sha256 FROM financial_reports fr "
        "JOIN source_items si ON si.source_item_id = fr.source_item_id WHERE fr.report_id = ?", (report_id,))
    if not rep:
        raise ValueError(f"report {report_id} not found in the operational database")
    rep = rep[0]
    if rep["extraction_status"] != "reconciled":
        return {"archived": 0, "refused": f"report is {rep['extraction_status']}; only reconciled reports "
                                          "are archived"}
    sha = rep["content_sha256"]
    metrics = main_db.execute(
        "SELECT period_end, period_type, metric, value, unit, currency, basis FROM financial_metrics "
        "WHERE report_id = ? ORDER BY metric", (report_id,))
    now = _now()
    stmts = [(
        "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
        "currency, "
        "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(report_sha256) DO NOTHING",
        (sha, f"{sha}.pdf", rep["company_id"], rep["doc_type"], rep["period_end"], rep["scope"],
         rep["currency"], rep["unit_scale"], rep["audit_status"], "reconciled", now))]
    for m in metrics:
        stmts.append((
            "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, "
            "metric_name, "
            "value, unit, currency, basis, report_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            (rep["company_id"], m["period_end"], m["period_type"], rep["scope"], m["metric"], m["value"],
             m["unit"], m["currency"], m["basis"], sha, now)))
    archive_db.batch(stmts, transactional=True)
    return {"archived": len(metrics), "report_sha256": sha}


def annual_series(archive_db, company_id: str, *, scope: str, metrics: tuple[str, ...] | None = None) -> dict:
    """Multi-period annual series read from the archive only. Conflicting reports for one period are listed,
    not chosen between."""
    require_role(archive_db, "archive")
    rows = archive_db.execute(
        "SELECT period_end_date, metric_name, value, basis, report_sha256 FROM archive_financial_tuples "
        "WHERE company_id = ? AND scope = ? AND period_type = 'FY' ORDER BY period_end_date, metric_name",
        (company_id, scope))
    by_period: dict[str, dict] = defaultdict(lambda: {"metrics": {}, "reports": set(), "basis": set()})
    for r in rows:
        if metrics is not None and r["metric_name"] not in metrics:
            continue
        p = by_period[r["period_end_date"]]
        p["metrics"][r["metric_name"]] = r["value"]
        p["reports"].add(r["report_sha256"])
        p["basis"].add(r["basis"])
    periods, conflicts = [], []
    for pe in sorted(by_period):
        p = by_period[pe]
        if len(p["reports"]) > 1:
            conflicts.append({"period_end": pe, "report_sha256": sorted(p["reports"])})
            continue
        periods.append({"period_end": pe, "basis": "restated" if "restated" in p["basis"] else "reported",
                        "metrics": dict(sorted(p["metrics"].items()))})
    return {"company_id": company_id, "scope": scope, "periods": periods, "gaps": year_gaps(periods),
            "conflicts": conflicts}


# ------------------------------------------------------------------ non-PDF historical summaries (loader)
SUMMARY_REQUIRED = ("ticker", "period_end", "doc_type", "scope", "currency", "unit_scale", "audit_status",
                    "source_note", "provenance", "metrics")
PROVENANCE = ("owner_supplied", "synthetic_fixture")
MAX_PAYLOAD_BYTES = 65536


def summary_sha256(summary: dict) -> str:
    """Hash of the canonical JSON summary: the summary's identity in the archive (no binary involved)."""
    return hashlib.sha256(json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scaled(code: str, v: float, currency: str, unit_scale: int) -> tuple[float, str]:
    if code in fin.PER_SHARE:
        return v, f"{currency}/share"
    if code in fin.PERCENT:
        return v, "%"
    if code in fin.COUNTS:
        return v, "shares"
    return v * unit_scale, currency


def validate_summary(summary: dict) -> dict:
    """Pure validation of one historical summary. No database access, no writes.

    Returns {"ok": bool, "reasons": [...], "checks": [...]}. A summary is accepted only when its fields are
    complete, its provenance is declared, its metrics are numbers or null, and the reporting identities pass.
    Nothing is accepted that could not be checked."""
    reasons = []
    missing = [k for k in SUMMARY_REQUIRED if summary.get(k) in (None, "")]
    if missing:
        reasons.append(f"missing fields: {missing}")
    if summary.get("provenance") not in PROVENANCE:
        reasons.append(f"provenance must be one of {PROVENANCE}")
    if summary.get("doc_type") != "annual":
        reasons.append("only annual summaries are loaded by this loader")
    if summary.get("scope") not in ("consolidated", "unconsolidated"):
        reasons.append("scope must be consolidated or unconsolidated")
    if summary.get("unit_scale") not in (1, 1000, 1000000, 1000000000):
        reasons.append("unit_scale must be 1, 1000, 1000000 or 1000000000")
    metrics = summary.get("metrics") or {}
    if not isinstance(metrics, dict):
        reasons.append("metrics must be an object")
        metrics = {}
    bad = [k for k, x in metrics.items() if x is not None and (isinstance(x, bool)
                                                               or not isinstance(x, (int, float)))]
    if bad:
        reasons.append(f"non-numeric metric values: {bad}")
    values = {k: (float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None)
              for k, x in metrics.items()}
    checks = fin.identity_checks(values)
    if any(c["result"] == "fail" for c in checks):
        reasons.append("reporting identity failed: " + ", ".join(
            c["check"] for c in checks if c["result"] == "fail"))
    if not any(c["result"] == "pass" for c in checks):
        reasons.append("no reporting identity could be checked: nothing is accepted unverified")
    if not any(v is not None for v in values.values()):
        reasons.append("no reported values")
    return {"ok": not reasons, "reasons": reasons, "checks": checks}


def archive_summary(archive_db, summary: dict, *, company_id: str) -> dict:
    """Write one validated historical summary to the archive as tuples. Idempotent on the summary hash."""
    require_role(archive_db, "archive")
    v = validate_summary(summary)
    if not v["ok"]:
        return {"archived": 0, "refused": v["reasons"]}
    sha = summary_sha256(summary)
    now = _now()
    cur, unit_scale = summary["currency"], int(summary["unit_scale"])
    stmts = [(
        "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
        "currency, unit_scale, audit_status, reconciliation, archived_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(report_sha256) DO NOTHING",
        (sha, f"{sha}.json", company_id, "annual", summary["period_end"], summary["scope"], cur, unit_scale,
         summary["audit_status"], "reconciled", now))]
    n = 0
    for code, x in sorted(summary["metrics"].items()):
        if x is None:
            continue  # not reported: no row, never zero
        val, unit = _scaled(code, float(x), cur, unit_scale)
        n += 1
        stmts.append((
            "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, "
            "metric_name, value, unit, currency, basis, report_sha256, archived_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (company_id, summary["period_end"], "FY", summary["scope"], code, val, unit, cur, "reported", sha,
             now)))
    archive_db.batch(stmts, transactional=True)
    return {"archived": n, "summary_sha256": sha}


def archive_disclosure(archive_db, *, company_id: str, kind: str, published_at_utc: str, title: str,
                       payload: dict, pdf_sha256: str | None = None) -> dict:
    """Store one parsed disclosure as bounded JSON. The PDF itself is never passed here: only its hash."""
    require_role(archive_db, "archive")
    if kind not in ("financial_statement", "material_disclosure"):
        raise ValueError("kind must be financial_statement or material_disclosure")
    if not title.strip() or not published_at_utc:
        raise ValueError("title and published_at_utc are required")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(body.encode()) > MAX_PAYLOAD_BYTES:
        return {"archived": 0,
                "refused": [f"payload exceeds {MAX_PAYLOAD_BYTES} bytes; store the summary only"]}
    key = b"|".join([body.encode(), (pdf_sha256 or "").encode(), company_id.encode(), title.encode()])
    sha = hashlib.sha256(key).hexdigest()
    archive_db.batch([(
        "INSERT INTO archive_disclosures(disclosure_sha256, company_id, kind, published_at_utc, title, "
        "payload_json, pdf_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
        (sha, company_id, kind, published_at_utc, title, body, pdf_sha256, _now()))], transactional=True)
    return {"archived": 1, "disclosure_sha256": sha}


def disclosures(archive_db, company_id: str, *, limit: int = 50) -> list[dict]:
    require_role(archive_db, "archive")
    return [dict(r) for r in archive_db.execute(
        "SELECT disclosure_sha256, kind, published_at_utc, title, payload_json FROM archive_disclosures "
        "WHERE company_id = ? ORDER BY published_at_utc DESC LIMIT ?", (company_id, limit))]
