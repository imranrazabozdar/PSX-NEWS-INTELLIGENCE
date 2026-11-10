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

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from database.migrate import migrate
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
