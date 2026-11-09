"""Owner-assisted document intake (M2): owner-downloaded PDFs to a reproducible, page-referenced import.

The owner downloads a document in their own browser and supplies the file. This module never fetches
anything. It:

* checks the file is a readable PDF (pdfplumber, the approved reader) before storing anything;
* stores the ORIGINAL bytes in a vault directory OUTSIDE the Git repository, named by SHA-256, never
  overwritten with different content;
* detects an identical document (same SHA-256 already imported) and a possible revised version (same
  company, report type, period and scope, different bytes), which is reported and NOT imported;
* extracts statement lines with page references and records unparsed lines and scanned pages for review;
* hands the result to engines/financials.import_report, which keeps the existing reconciliation,
  page-reference and promotion gates. Nothing is promoted here.

No OCR, no external processing, no network access.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from engines import financials as fin
from engines import pdf_extraction as pe
from engines import pdf_reader

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT_ENV = "PSXNI_DOCUMENT_VAULT"
_REQUIRED = ("company_ticker", "doc_type", "period_end", "scope", "currency", "unit_scale", "audit_status",
             "columns", "retrieved_at_utc", "filed_at_utc")
STATEMENTS = ("IS", "BS", "CF", "EQ")


class IntakeError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def vault_dir(explicit: str | Path | None = None) -> Path:
    """Vault: explicit path or PSXNI_DOCUMENT_VAULT; absolute, and outside the repository."""
    raw = explicit or os.environ.get(VAULT_ENV)
    if not raw:
        raise IntakeError(f"no vault: set {VAULT_ENV} to a directory outside the repository")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise IntakeError("the vault path must be absolute")
    resolved = p.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise IntakeError("the vault must be outside the Git repository")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    return resolved


def store_original(pdf: Path | str, vault: Path) -> tuple[Path, str]:
    """Verify the file is a readable PDF, then keep its original bytes in the vault under its SHA-256."""
    src = Path(pdf)
    doc = pdf_reader.read(src)  # raises ValueError for a missing, non-PDF or empty file: nothing is stored
    if not doc.pages:
        raise IntakeError("PDF has no pages")
    data = src.read_bytes()
    sha = pe.sha256_file(src)
    dest = vault / f"{sha}.pdf"
    if dest.exists():
        if dest.read_bytes() != data:  # a SHA-256 collision or a corrupted vault: never overwrite
            raise IntakeError("vault file with this hash has different bytes; refusing to overwrite")
        return dest, sha
    fd, tmp = tempfile.mkstemp(dir=vault, suffix=".part")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest, sha


def _ticker_company(db, ticker: str) -> str:
    row = db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                     "AND valid_to IS NULL", (ticker,))
    if not row:
        raise IntakeError(f"ticker {ticker!r} is not in the company master (not added automatically)")
    return row[0]["company_id"]


def _existing_by_hash(db, sha: str) -> dict | None:
    row = db.execute(
        "SELECT fr.report_id, fr.company_id, fr.doc_type, fr.period_end, fr.scope FROM financial_reports fr "
        "JOIN source_items si ON si.source_item_id = fr.source_item_id WHERE si.content_sha256 = ? "
        "ORDER BY fr.report_id LIMIT 1", (sha,))
    return dict(row[0]) if row else None


def _revisions(db, company_id: str, meta: dict, sha: str) -> list[dict]:
    rows = db.execute(
        "SELECT fr.report_id, si.content_sha256 FROM financial_reports fr JOIN source_items si "
        "ON si.source_item_id = fr.source_item_id WHERE fr.company_id = ? AND fr.doc_type = ? AND "
        "fr.period_end = ? AND fr.scope = ?",
        (company_id, meta["doc_type"], meta["period_end"], meta["scope"]))
    return [{"report_id": r["report_id"], "sha256": r["content_sha256"]} for r in rows
            if r["content_sha256"] != sha]


def intake(db, pdf: Path | str, meta: dict, *, vault: Path, importer: str, rights_attestation: str) -> dict:
    """Store, extract and import one owner-supplied document. Returns a review record; never promotes."""
    if not importer.strip() or not rights_attestation.strip():
        raise IntakeError("importer and rights_attestation are required")
    missing = [k for k in _REQUIRED if meta.get(k) in (None, "", [])]
    if missing:
        raise IntakeError(f"missing metadata: {missing}")
    if not (meta.get("original_url") or meta.get("source_note")):
        raise IntakeError("a document needs its source: original_url or source_note")
    stored, sha = store_original(pdf, vault)
    prior = _existing_by_hash(db, sha)
    if prior:
        return {"status": "duplicate", "sha256": sha, "report_id": prior["report_id"],
                "stored_as": stored.name}
    company_id = _ticker_company(db, meta["company_ticker"])
    revisions = _revisions(db, company_id, meta, sha)
    if revisions:  # a different file for the same period: a possible revision, reported and not imported
        return {"status": "possible_revision", "sha256": sha, "stored_as": stored.name,
                "existing_reports": revisions,
                "note": "same company, report type, period and scope with different bytes; "
                        "confirm whether this is a restatement before importing"}
    doc = pe.extract(stored)
    columns = list(meta["columns"])
    located = pe.locate_statements(doc)
    pages_by_stmt = meta.get("statement_pages") or located
    lines, unparsed, used = [], [], {}
    for st in STATEMENTS:
        pages = pages_by_stmt.get(st)
        if not pages:
            continue
        r = pe.to_statement_lines(doc, st, pages, columns=columns)
        lines.extend({**ln, "statement": st} for ln in r["lines"])
        unparsed.extend({**u, "statement": st} for u in r["unparsed"])
        used[st] = pages
    scanned = [pg.number for pg in doc.pages if not pg.has_text]
    rec = {k: meta[k] for k in ("company_ticker", "doc_type", "period_end", "scope", "currency", "unit_scale",
                                "audit_status", "filed_at_utc", "retrieved_at_utc") if k in meta}
    rec.update({"document_sha256": sha, "source": "manual_pdf", "extraction_method": "pdf_text",
                "original_url": meta.get("original_url"), "source_note": meta.get("source_note"),
                "auditor_opinion": meta.get("auditor_opinion"), "title": meta.get("title"),
                "lines": lines})
    result = fin.import_report(db, rec, importer=importer, rights_attestation=rights_attestation)
    review = bool(unparsed or scanned or not lines or result["status"] != "reconciled")
    return {"status": "needs_review" if review else "reconciled", "sha256": sha, "stored_as": stored.name,
            "pages": len(doc.pages), "statement_pages": used, "scanned_pages": scanned,
            "lines_extracted": len(lines), "unparsed": unparsed, "import": result}
