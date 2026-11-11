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


class ArchiveNotReady(RuntimeError):
    """The archive is not fully migrated, or its schema has drifted. Nothing is applied from a repository."""


def require_archive_ready(adb) -> dict:
    """Refuse unless the archive is fully migrated and matches the reference schema. Never applies DDL.

    DDL is applied only by the approved gate (database/archive_migrations/archive_gate.py and
    scripts/archive_migrate). A repository that could apply DDL would bypass the approval string."""
    require_role(adb, "archive")
    from database.archive_migrations import archive_gate as gate

    report = gate.probe(adb)
    if not report["fully_migrated"]:
        raise ArchiveNotReady(
            f"archive is not ready: ledger {report['state']['ledger_versions']}, "
            f"ledger checksums match the repository: {report['ledger_checksums_match_repository']}, "
            f"structure drift: {report['structure_drift_for_ledger_state']}"
        )
    return report


def archive_promoted(main_db, archive_db, report_id: int) -> dict:
    """Copy one reconciled report's promoted metrics into the archive. Idempotent on the document hash."""
    require_role(main_db, "main")
    require_role(archive_db, "archive")
    rep = main_db.execute(
        "SELECT fr.report_id, fr.company_id, fr.doc_type, fr.period_end, fr.scope, fr.currency, "
        "fr.unit_scale, "
        "fr.audit_status, fr.extraction_status, si.content_sha256 FROM financial_reports fr "
        "JOIN source_items si ON si.source_item_id = fr.source_item_id WHERE fr.report_id = ?",
        (report_id,),
    )
    if not rep:
        raise ValueError(f"report {report_id} not found in the operational database")
    rep = rep[0]
    if rep["extraction_status"] != "reconciled":
        return {
            "archived": 0,
            "refused": f"report is {rep['extraction_status']}; only reconciled reports are archived",
        }
    sha = rep["content_sha256"]
    metrics = main_db.execute(
        "SELECT period_end, period_type, metric, value, unit, currency, basis FROM financial_metrics "
        "WHERE report_id = ? ORDER BY metric",
        (report_id,),
    )
    now = _now()
    stmts = [
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
            "currency, "
            "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(report_sha256) DO NOTHING",
            (
                sha,
                f"{sha}.pdf",
                rep["company_id"],
                rep["doc_type"],
                rep["period_end"],
                rep["scope"],
                rep["currency"],
                rep["unit_scale"],
                rep["audit_status"],
                "reconciled",
                now,
            ),
        )
    ]
    for m in metrics:
        stmts.append(
            (
                "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, "
                "metric_name, "
                "value, unit, currency, basis, report_sha256, archived_at_utc) VALUES"
                "(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    rep["company_id"],
                    m["period_end"],
                    m["period_type"],
                    rep["scope"],
                    m["metric"],
                    m["value"],
                    m["unit"],
                    m["currency"],
                    m["basis"],
                    sha,
                    now,
                ),
            )
        )
    archive_db.batch(stmts, transactional=True)
    return {"archived": len(metrics), "report_sha256": sha}


def annual_series(archive_db, company_id: str, *, scope: str, metrics: tuple[str, ...] | None = None) -> dict:
    """Multi-period annual series read from the archive only. Conflicting reports for one period are listed,
    not chosen between."""
    require_role(archive_db, "archive")
    rows = archive_db.execute(
        "SELECT period_end_date, metric_name, value, basis, report_sha256 FROM archive_financial_tuples "
        "WHERE company_id = ? AND scope = ? AND period_type = 'FY' ORDER BY period_end_date, metric_name",
        (company_id, scope),
    )
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
        periods.append(
            {
                "period_end": pe,
                "basis": "restated" if "restated" in p["basis"] else "reported",
                "metrics": dict(sorted(p["metrics"].items())),
            }
        )
    return {
        "company_id": company_id,
        "scope": scope,
        "periods": periods,
        "gaps": year_gaps(periods),
        "conflicts": conflicts,
    }


# ------------------------------------------------------------------ non-PDF historical summaries (loader)
SUMMARY_REQUIRED = (
    "ticker",
    "period_end",
    "doc_type",
    "scope",
    "currency",
    "unit_scale",
    "audit_status",
    "source_note",
    "provenance",
    "metrics",
)
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
    bad = [
        k
        for k, x in metrics.items()
        if x is not None and (isinstance(x, bool) or not isinstance(x, (int, float)))
    ]
    if bad:
        reasons.append(f"non-numeric metric values: {bad}")
    values = {
        k: (float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None)
        for k, x in metrics.items()
    }
    checks = fin.identity_checks(values)
    if any(c["result"] == "fail" for c in checks):
        reasons.append(
            "reporting identity failed: " + ", ".join(c["check"] for c in checks if c["result"] == "fail")
        )
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
    stmts = [
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
            "currency, unit_scale, audit_status, reconciliation, archived_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(report_sha256) DO NOTHING",
            (
                sha,
                f"{sha}.json",
                company_id,
                "annual",
                summary["period_end"],
                summary["scope"],
                cur,
                unit_scale,
                summary["audit_status"],
                "reconciled",
                now,
            ),
        )
    ]
    n = 0
    for code, x in sorted(summary["metrics"].items()):
        if x is None:
            continue  # not reported: no row, never zero
        val, unit = _scaled(code, float(x), cur, unit_scale)
        n += 1
        stmts.append(
            (
                "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, "
                "metric_name, value, unit, currency, basis, report_sha256, archived_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (
                    company_id,
                    summary["period_end"],
                    "FY",
                    summary["scope"],
                    code,
                    val,
                    unit,
                    cur,
                    "reported",
                    sha,
                    now,
                ),
            )
        )
    archive_db.batch(stmts, transactional=True)
    return {"archived": n, "summary_sha256": sha}


def archive_disclosure(
    archive_db,
    *,
    company_id: str,
    kind: str,
    published_at_utc: str,
    title: str,
    payload: dict,
    pdf_sha256: str | None = None,
) -> dict:
    """Store one parsed disclosure as bounded JSON. The PDF itself is never passed here: only its hash."""
    require_role(archive_db, "archive")
    if kind not in ("financial_statement", "material_disclosure"):
        raise ValueError("kind must be financial_statement or material_disclosure")
    if not title.strip() or not published_at_utc:
        raise ValueError("title and published_at_utc are required")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(body.encode()) > MAX_PAYLOAD_BYTES:
        return {
            "archived": 0,
            "refused": [f"payload exceeds {MAX_PAYLOAD_BYTES} bytes; store the summary only"],
        }
    key = b"|".join([body.encode(), (pdf_sha256 or "").encode(), company_id.encode(), title.encode()])
    sha = hashlib.sha256(key).hexdigest()
    if archive_db.execute("SELECT 1 FROM archive_disclosures WHERE disclosure_sha256 = ?", (sha,)):
        return {"archived": 0, "status": "existing", "disclosure_sha256": sha}
    archive_db.batch(
        [
            (
                "INSERT INTO archive_disclosures(disclosure_sha256, company_id, kind,"
                "published_at_utc, title, "
                "payload_json, pdf_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (sha, company_id, kind, published_at_utc, title, body, pdf_sha256, _now()),
            )
        ],
        transactional=True,
    )
    return {"archived": 1, "status": "stored", "disclosure_sha256": sha}


def disclosures(archive_db, company_id: str, *, limit: int = 50) -> list[dict]:
    require_role(archive_db, "archive")
    return [
        dict(r)
        for r in archive_db.execute(
            "SELECT disclosure_sha256, kind, published_at_utc, title, payload_json FROM archive_disclosures "
            "WHERE company_id = ? ORDER BY published_at_utc DESC LIMIT ?",
            (company_id, limit),
        )
    ]


# ------------------------------------------------------------------ document registry and extraction evidence
DOC_TYPES = ("annual", "half_yearly", "quarterly", "nine_month")
CONSOLIDATIONS = ("consolidated", "unconsolidated", "mixed", "unknown")
STATEMENTS = ("IS", "BS", "CF", "EQ", "OCI", "NOTE")
EXTRACTION_METHODS = ("manual", "pdf_text", "pdf_table", "ocr", "structured_json")
REGISTRY_FIELDS = (
    "report_sha256",
    "psx_symbol",
    "company_id",
    "doc_type",
    "financial_year",
    "period_end",
    "consolidation",
    "audit_status",
    "original_filename",
    "vault_ref",
    "source_id",
    "retrieved_at_utc",
)


def register_document(archive_db, meta: dict, *, now: str | None = None) -> dict:
    """Register one original document. Idempotent on the file hash: the same bytes return the existing row.
    A new version of the same company, period and consolidation basis gets document_version + 1."""
    require_role(archive_db, "archive")
    missing = [k for k in REGISTRY_FIELDS if meta.get(k) in (None, "")]
    if missing:
        raise ValueError(f"missing registry fields: {missing}")
    if meta["doc_type"] not in DOC_TYPES or meta["consolidation"] not in CONSOLIDATIONS:
        raise ValueError("doc_type or consolidation is not an accepted value")
    sha = meta["report_sha256"]
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("report_sha256 must be a 64-character lowercase hex SHA-256")
    for k in ("original_filename", "vault_ref"):
        if "/" in meta[k] or "\\" in meta[k]:
            raise ValueError(f"{k} must be a file name, never a path")
    existing = archive_db.execute("SELECT * FROM archive_document_registry WHERE report_sha256 = ?", (sha,))
    if existing:
        return {
            "status": "duplicate",
            "report_sha256": sha,
            "document_version": existing[0]["document_version"],
        }
    prior = archive_db.execute(
        "SELECT COALESCE(MAX(document_version), 0) AS v FROM archive_document_registry WHERE company_id = ? "
        "AND doc_type = ? AND period_end = ? AND consolidation = ?",
        (meta["company_id"], meta["doc_type"], meta["period_end"], meta["consolidation"]),
    )[0]["v"]
    version = prior + 1
    ts = now or _now()
    archive_db.batch(
        [
            (
                "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id,"
                "doc_type, financial_year, "
                "period_end, consolidation, audit_status, publication_date, original_filename,"
                "vault_ref, source_id, "
                "source_url, retrieved_at_utc, document_version, registered_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sha,
                    meta["psx_symbol"],
                    meta["company_id"],
                    meta["doc_type"],
                    int(meta["financial_year"]),
                    meta["period_end"],
                    meta["consolidation"],
                    meta["audit_status"],
                    meta.get("publication_date"),
                    meta["original_filename"],
                    meta["vault_ref"],
                    meta["source_id"],
                    meta.get("source_url"),
                    meta["retrieved_at_utc"],
                    version,
                    ts,
                ),
            ),
            (
                "INSERT INTO archive_processing_events(report_sha256, status, detail, recorded_at_utc) "
                "VALUES (?,?,?,?)",
                (sha, "registered", f"version {version}", ts),
            ),
        ],
        transactional=True,
    )
    return {"status": "registered", "report_sha256": sha, "document_version": version}


def record_processing(archive_db, sha: str, status: str, detail: str) -> None:
    require_role(archive_db, "archive")
    if status not in ("registered", "extracting", "extracted", "reconciled", "needs_review", "failed"):
        raise ValueError("unknown processing status")
    archive_db.batch(
        [
            (
                "INSERT INTO archive_processing_events(report_sha256, status, detail, recorded_at_utc) "
                "VALUES (?,?,?,?)",
                (sha, status, detail, _now()),
            )
        ],
        transactional=True,
    )


def store_line_items(
    archive_db, sha: str, lines: list[dict], *, consolidation: str, currency: str, unit_scale: int
) -> dict:
    """Store extracted line items with their evidence.

    Values are stored as extracted. Missing values are stored as not_reported (NULL), never as zero. A line
    that already exists is skipped, so reprocessing adds nothing."""
    require_role(archive_db, "archive")
    stmts, skipped = [], 0
    for ln in lines:
        if ln["statement"] not in STATEMENTS or ln.get("extraction_method") not in EXTRACTION_METHODS:
            raise ValueError(f"line {ln.get('raw_label')!r}: statement or extraction method not accepted")
        state = ln.get("value_state", "reported" if ln.get("value") is not None else "not_reported")
        value = ln.get("value")
        if state == "reported" and value is None:
            raise ValueError(f"line {ln['raw_label']!r}: reported state needs a value")
        if state != "reported":
            value = None
        stmts.append(
            (
                "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label,"
                "canonical_code, "
                "column_period_end, is_comparative, value, value_state, currency, unit_scale,"
                "consolidation, page, "
                "note_ref, extraction_method, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(report_sha256, statement, line_no, column_period_end, consolidation) DO NOTHING",
                (
                    sha,
                    ln["statement"],
                    int(ln["line_no"]),
                    ln["raw_label"],
                    ln.get("canonical_code"),
                    ln["column_period_end"],
                    int(bool(ln.get("is_comparative"))),
                    value,
                    state,
                    currency,
                    unit_scale,
                    consolidation,
                    ln.get("page"),
                    ln.get("note_ref"),
                    ln["extraction_method"],
                    ln.get("confidence"),
                ),
            )
        )
    before = archive_db.execute(
        "SELECT COUNT(*) AS n FROM archive_line_items WHERE report_sha256 = ?", (sha,)
    )[0]["n"]
    archive_db.batch(stmts, transactional=True)
    after = archive_db.execute(
        "SELECT COUNT(*) AS n FROM archive_line_items WHERE report_sha256 = ?", (sha,)
    )[0]["n"]
    skipped = len(stmts) - (after - before)
    return {"inserted": after - before, "already_present": skipped}


def store_reconciliation(
    archive_db, sha: str, checks: list[dict], *, consolidation: str, column_period_end: str, tolerance: float
) -> dict:
    """Record reconciliation results (append-only).

    A check that could not be run is recorded as not_checkable."""
    require_role(archive_db, "archive")
    ts = _now()
    stmts = []
    for c in checks:
        result = c["result"]
        if result not in ("pass", "fail", "not_checkable"):
            raise ValueError("unknown check result")
        reported, expected = c.get("reported"), c.get("expected")
        diff = None if reported is None or expected is None else reported - expected
        stmts.append(
            (
                "INSERT INTO archive_reconciliation(report_sha256, check_name, column_period_end,"
                "consolidation, "
                "reported, expected, difference, tolerance, result, recorded_at_utc) VALUES"
                "(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    sha,
                    c["check"],
                    column_period_end,
                    consolidation,
                    reported,
                    expected,
                    diff,
                    tolerance,
                    result,
                    ts,
                ),
            )
        )
    archive_db.batch(stmts, transactional=True)
    return {"recorded": len(stmts)}


def record_review(
    archive_db, *, line_id: int, decision: str, reviewer: str, note: str, corrected_value: float | None = None
) -> dict:
    """Append a review. The original extracted value is never changed. A correction is a new review row."""
    require_role(archive_db, "archive")
    if decision not in ("accepted", "rejected", "corrected"):
        raise ValueError("decision must be accepted, rejected or corrected")
    if (decision == "corrected") != (corrected_value is not None):
        raise ValueError("a correction needs a corrected value; other decisions must not have one")
    if not reviewer.strip() or not note.strip():
        raise ValueError("reviewer and note are required")
    archive_db.batch(
        [
            (
                "INSERT INTO archive_line_reviews(line_id, decision, corrected_value, reviewer,"
                "note, reviewed_at_utc) "
                "VALUES (?,?,?,?,?,?)",
                (line_id, decision, corrected_value, reviewer, note, _now()),
            )
        ],
        transactional=True,
    )
    return {"recorded": 1}


# ----------------------------------------- migration 0005: versioned extraction records
def create_extraction_run(
    archive_db, *, report_sha256: str, extractor_version: str, now: str | None = None
) -> dict:
    """Create or reuse the extraction run for one (document, extractor_version).

    The same pair returns the existing run, so reprocessing with the same extractor adds nothing. A new
    extractor version creates a new run beside the old one.
    """
    require_role(archive_db, "archive")
    if not extractor_version or len(extractor_version) > 120:
        raise ValueError("extractor_version must be 1 to 120 characters")
    existing = archive_db.execute(
        "SELECT run_id FROM archive_extraction_runs WHERE report_sha256 = ? AND extractor_version = ?",
        (report_sha256, extractor_version),
    )
    if existing:
        return {"run_id": existing[0]["run_id"], "status": "existing"}
    archive_db.batch(
        [
            (
                "INSERT INTO archive_extraction_runs(report_sha256, extractor_version, started_at_utc) "
                "VALUES (?,?,?)",
                (report_sha256, extractor_version, now or _now()),
            )
        ],
        transactional=True,
    )
    run = archive_db.execute(
        "SELECT run_id FROM archive_extraction_runs WHERE report_sha256 = ? AND extractor_version = ?",
        (report_sha256, extractor_version),
    )[0]
    return {"run_id": run["run_id"], "status": "created"}


LINE_V2_SQL = (
    "INSERT INTO archive_line_items_v2(run_id, extractor_version, document_id, symbol, period_end, "
    "statement_type, line_no, line_item_name, canonical_code, column_period_end, is_comparative, "
    "reported_amount, value_state, restated_flag, currency, unit_scale, consolidation, pdf_page_number, "
    "note_ref, extraction_method, confidence, processed_at_utc, report_sha256) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(run_id, statement_type, line_no, column_period_end, consolidation) DO NOTHING"
)


def store_versioned_lines(
    archive_db,
    run_id: int,
    lines: list[dict],
    *,
    extractor_version: str,
    symbol: str,
    document_id: str,
    now: str | None = None,
) -> dict:
    """Store tagged line items for one run. Every line carries its evidence. Missing values are NULL.

    A line already stored for the run (same natural key) is skipped, so reprocessing adds nothing.
    """
    require_role(archive_db, "archive")
    ts = now or _now()
    before = archive_db.execute(
        "SELECT COUNT(*) AS n FROM archive_line_items_v2 WHERE run_id = ?", (run_id,)
    )[0]["n"]
    stmts = []
    for ln in lines:
        state = ln.get("value_state", "reported" if ln.get("reported_amount") is not None else "not_reported")
        amount = ln.get("reported_amount")
        if state == "reported" and amount is None:
            raise ValueError(f"line {ln.get('line_item_name')!r}: reported state needs an amount")
        if state != "reported":
            amount = None
        args = (
            run_id,
            extractor_version,
            document_id,
            symbol,
            ln["period_end"],
            ln["statement_type"],
            int(ln["line_no"]),
            ln["line_item_name"],
            ln.get("canonical_code"),
            ln["column_period_end"],
            int(bool(ln.get("is_comparative"))),
            amount,
            state,
            int(bool(ln.get("restated_flag"))),
            ln["currency"],
            int(ln["unit_scale"]),
            ln["consolidation"],
            ln.get("pdf_page_number"),
            ln.get("note_ref"),
            ln["extraction_method"],
            ln.get("confidence"),
            ts,
            document_id,  # the source SHA-256, stored explicitly on every fact (migration 0006)
        )
        stmts.append((LINE_V2_SQL, args))
    archive_db.batch(stmts, transactional=True)
    after = archive_db.execute("SELECT COUNT(*) AS n FROM archive_line_items_v2 WHERE run_id = ?", (run_id,))[
        0
    ]["n"]
    return {"inserted": after - before, "already_present": len(stmts) - (after - before)}


RECON_V2_SQL = (
    "INSERT INTO archive_reconciliation_v2(run_id, check_name, column_period_end, consolidation, reported, "
    "expected, discrepancy, tolerance, status, recorded_at_utc, report_sha256) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT DO NOTHING"
)
RECON_STATUSES = ("RECONCILED", "RECONCILED_WITH_ROUNDING", "UNRECONCILED", "INSUFFICIENT_DATA")


def store_versioned_reconciliation(
    archive_db, run_id: int, checks: list[dict], *, consolidation: str, now: str | None = None
) -> dict:
    """Store reconciliation checks for one run, each with an explicit status.

    The exact discrepancy is kept.
    """
    require_role(archive_db, "archive")
    ts = now or _now()
    sha = archive_db.execute("SELECT report_sha256 FROM archive_extraction_runs WHERE run_id = ?", (run_id,))
    if not sha:
        raise ValueError(f"run {run_id} does not exist")
    stmts = []
    for c in checks:
        if c["status"] not in RECON_STATUSES:
            raise ValueError(f"unknown reconciliation status {c['status']!r}")
        args = (
            run_id,
            c["check"],
            c["column_period_end"],
            consolidation,
            c.get("reported"),
            c.get("expected"),
            c.get("discrepancy"),
            c.get("allowance", 0.0),
            c["status"],
            ts,
            sha[0]["report_sha256"],
        )
        stmts.append((RECON_V2_SQL, args))
    archive_db.batch(stmts, transactional=True)
    return {"recorded_attempts": len(stmts)}


def record_document_file(
    archive_db, *, report_sha256: str, file_size_bytes: int, now: str | None = None
) -> dict:
    """Record the stored file size for a registered document. Once per document (append-only)."""
    require_role(archive_db, "archive")
    if file_size_bytes < 0:
        raise ValueError("file size must not be negative")
    if archive_db.execute("SELECT 1 FROM archive_document_files WHERE report_sha256 = ?", (report_sha256,)):
        return {"status": "existing"}
    archive_db.batch(
        [
            (
                "INSERT INTO archive_document_files(report_sha256, file_size_bytes, stored_at_utc) "
                "VALUES (?,?,?)",
                (report_sha256, int(file_size_bytes), now or _now()),
            )
        ],
        transactional=True,
    )
    return {"status": "recorded"}


# ----------------------------------------------------------------- status vocabulary (migration 0007)

STATEMENT_STATUS_SQL = (
    "INSERT INTO archive_statement_status(run_id, report_sha256, statement_type, consolidation, "
    "column_period_end, status, reason, evidence_page, recorded_at_utc) VALUES (?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(run_id, statement_type, consolidation, column_period_end) DO NOTHING"
)
FACT_STATUS_SQL = (
    "INSERT INTO archive_fact_status(line_id, report_sha256, status, reason, recorded_at_utc) "
    "VALUES (?,?,?,?,?) ON CONFLICT(line_id) DO NOTHING"
)


def _vocabulary() -> tuple[str, ...]:
    from engines.status_vocabulary import VOCABULARY

    return VOCABULARY


def store_statement_statuses(archive_db, run_id: int, rows: list[dict], *, now: str | None = None) -> dict:
    """One status per statement and column. Each row: statement_type, consolidation, column_period_end,
    status, reason and optional evidence_page. Statuses outside the vocabulary are refused."""
    require_role(archive_db, "archive")
    ts = now or _now()
    sha = archive_db.execute("SELECT report_sha256 FROM archive_extraction_runs WHERE run_id = ?", (run_id,))
    if not sha:
        raise ValueError(f"run {run_id} does not exist")
    stmts = []
    for r in rows:
        if r["status"] not in _vocabulary():
            raise ValueError(f"status {r['status']!r} is not in the archive vocabulary")
        stmts.append((STATEMENT_STATUS_SQL, (
            run_id, sha[0]["report_sha256"], r["statement_type"], r["consolidation"],
            r["column_period_end"], r["status"], r["reason"], r.get("evidence_page"), ts,
        )))
    archive_db.batch(stmts, transactional=True)
    return {"recorded": len(stmts)}


def store_fact_statuses(archive_db, run_id: int, rows: list[dict], *, now: str | None = None) -> dict:
    """One status per stored fact, found by its natural key within the run."""
    require_role(archive_db, "archive")
    ts = now or _now()
    stmts = []
    for r in rows:
        if r["status"] not in _vocabulary():
            raise ValueError(f"status {r['status']!r} is not in the archive vocabulary")
        found = archive_db.execute(
            "SELECT line_id, report_sha256, document_id FROM archive_line_items_v2 WHERE run_id = ? AND "
            "statement_type = ? AND line_no = ? AND column_period_end = ? AND consolidation = ?",
            (run_id, r["statement_type"], int(r["line_no"]), r["column_period_end"], r["consolidation"]),
        )
        if not found:
            raise ValueError(f"no stored fact for {r['statement_type']} line {r['line_no']}")
        line = found[0]
        stmts.append((FACT_STATUS_SQL, (
            line["line_id"], line["report_sha256"] or line["document_id"], r["status"], r["reason"], ts,
        )))
    archive_db.batch(stmts, transactional=True)
    return {"recorded": len(stmts)}
