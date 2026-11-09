"""Owner-assisted document intake (M2): owner-supplied PDFs to a reproducible, page-referenced import.

The owner supplies a document they downloaded in their own browser. This module never fetches anything. It:

* checks the file is a readable PDF (pdfplumber, the approved reader) before storing anything;
* stores the ORIGINAL bytes in a vault OUTSIDE the Git repository, named by SHA-256; a file with the same
  hash and different bytes is never overwritten;
* treats a document as a duplicate only when the same bytes were already imported for the same company,
  report type, period AND scope; the same file may legitimately hold consolidated and unconsolidated
  statements;
* reports a possible revision (same company, report type, period and scope, different bytes) and does NOT
  import it;
* reads side-by-side pages only when they are listed in `split_pages`, and then via layout detection;
* extracts statement lines with page references, adds subtotal rows recognised by deterministic rules
  (engines/subtotals.py, rule recorded in the stored label), and flags everything else for review;
* imports through engines/financials.import_report, which keeps the reconciliation, page-reference and
  promotion gates. Nothing is promoted here.

Dates are kept separate: publication (filed_at_utc), owner download (download_at_utc, or "unknown" when not
supplied), receipt by the project (receipt_at_utc, the upload date) and the financial import time. A missing
download date is never replaced by the receipt date.

No OCR, no network access, no external processing.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from engines import financials as fin
from engines import pdf_extraction as pe
from engines import pdf_reader, subtotals

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT_ENV = "PSXNI_DOCUMENT_VAULT"
_REQUIRED = ("company_ticker", "doc_type", "period_end", "scope", "currency", "unit_scale", "audit_status",
             "columns", "receipt_at_utc", "filed_at_utc")
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
        if dest.read_bytes() != data:  # never overwrite with different bytes
            raise IntakeError("vault file with this hash has different bytes; refusing to overwrite")
        return dest, sha
    fd, tmp = tempfile.mkstemp(dir=vault, suffix=".part")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest, sha


def _columns_for(meta: dict, statement: str) -> list[str]:
    """Comparatives differ by statement (quarter vs year-end): columns may be given per statement."""
    cols = meta["columns"]
    if isinstance(cols, dict):
        if statement not in cols:
            raise IntakeError(f"no column periods given for statement {statement}")
        return list(cols[statement])
    return list(cols)


def _ticker_company(db, ticker: str) -> str:
    row = db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                     "AND valid_to IS NULL", (ticker,))
    if not row:
        raise IntakeError(f"ticker {ticker!r} is not in the company master (not added automatically)")
    return row[0]["company_id"]


def _existing_same_document(db, sha: str, company_id: str, meta: dict) -> dict | None:
    """Same bytes for the same company, report type, period AND scope: a duplicate."""
    row = db.execute(
        "SELECT fr.report_id FROM financial_reports fr "
        "JOIN source_items si ON si.source_item_id = fr.source_item_id "
        "WHERE si.content_sha256 = ? AND fr.company_id = ? AND fr.doc_type = ? AND fr.period_end = ? "
        "AND fr.scope = ? ORDER BY fr.report_id LIMIT 1",
        (sha, company_id, meta["doc_type"], meta["period_end"], meta["scope"]))
    return dict(row[0]) if row else None


def _revisions(db, company_id: str, meta: dict, sha: str) -> list[dict]:
    rows = db.execute(
        "SELECT fr.report_id, si.content_sha256 FROM financial_reports fr JOIN source_items si "
        "ON si.source_item_id = fr.source_item_id WHERE fr.company_id = ? AND fr.doc_type = ? AND "
        "fr.period_end = ? AND fr.scope = ?",
        (company_id, meta["doc_type"], meta["period_end"], meta["scope"]))
    return [{"report_id": r["report_id"], "sha256": r["content_sha256"]} for r in rows
            if r["content_sha256"] != sha]


def _date_provenance(meta: dict) -> dict:
    download = meta.get("download_at_utc") or "unknown"  # never substituted by the receipt date
    return {"download_at_utc": download, "receipt_at_utc": meta["receipt_at_utc"],
            "filed_at_utc": meta["filed_at_utc"]}


def _statement_lines(doc, st: str, pages: list[int], columns: list[str]) -> tuple[list, list]:
    """Labelled lines plus recognised and unresolved subtotal rows for one statement."""
    labelled = pe.to_statement_lines(doc, st, pages, columns=columns)
    lines = list(labelled["lines"])
    unparsed = list(labelled["unparsed"])
    recognised_text: set[tuple[int, str]] = set()
    for part in doc.pages:
        if part.number not in pages or not part.has_text or part.layout_flag == "uncertain":
            continue
        for res in subtotals.analyse(part.lines, statement=st, columns=columns, page=part.number):
            tag = {"column": part.column} if part.column else {}
            if res["status"] == "recognised":
                label = f"[structural {res['rule']}] {res['text']}"
                conf = 0.9
                recognised_text.add((part.number, res["text"]))
            else:
                label = f"[unlabelled, unresolved] {res['text']}"
                conf = None
                unparsed.append({"page": part.number, "line": res["text"], "reason": res["reason"], **tag})
            for c in columns:
                lines.append({"statement": st, "raw_label": label, "column_period_end": c,
                              "value": res["values"][c], "page": part.number, "confidence": conf,
                              "canonical_code": res["code"] if res["status"] == "recognised" else None,
                              **tag})
    unparsed = [u for u in unparsed if (u.get("page"), u.get("line")) not in recognised_text]
    return lines, unparsed


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
    company_id = _ticker_company(db, meta["company_ticker"])
    prior = _existing_same_document(db, sha, company_id, meta)
    if prior:
        return {"status": "duplicate", "sha256": sha, "report_id": prior["report_id"],
                "stored_as": stored.name, "scope": meta["scope"]}
    revisions = _revisions(db, company_id, meta, sha)
    if revisions:
        return {"status": "possible_revision", "sha256": sha, "stored_as": stored.name,
                "existing_reports": revisions, "scope": meta["scope"],
                "note": "same company, report type, period and scope with different bytes; "
                        "confirm whether this is a restatement before importing"}
    split = list(meta.get("split_pages") or [])
    doc = pdf_reader.read_with_layout(stored, split) if split else pe.extract(stored)
    pages_by_stmt = meta.get("statement_pages") or pe.locate_statements(doc)
    lines, unparsed, used = [], [], {}
    for st in STATEMENTS:
        pages = pages_by_stmt.get(st)
        if not pages:
            continue
        l_, u_ = _statement_lines(doc, st, pages, _columns_for(meta, st))
        lines.extend({**x, "statement": x.get("statement", st)} for x in l_)
        unparsed.extend({**u, "statement": st} for u in u_)
        used[st] = pages
    scanned = [pg.number for pg in doc.pages if not pg.has_text]
    repairs = [r for pg in doc.pages for r in pg.repairs]
    if not lines:  # nothing extracted: store nothing, so no empty report can be mistaken for a real one
        return {"status": "extraction_failed", "sha256": sha, "stored_as": stored.name,
                "pages": len(doc.pages), "statement_pages": used, "scanned_pages": scanned,
                "lines_extracted": 0, "unparsed": unparsed, "text_repairs": repairs}
    rec = {k: meta[k] for k in ("company_ticker", "doc_type", "period_end", "scope", "currency", "unit_scale",
                                "audit_status", "filed_at_utc") if k in meta}
    rec.update({"document_sha256": sha, "source": "manual_pdf", "extraction_method": "pdf_text",
                "original_url": meta.get("original_url"), "source_note": meta.get("source_note"),
                "auditor_opinion": meta.get("auditor_opinion"), "title": meta.get("title"),
                "receipt_at_utc": meta["receipt_at_utc"],
                "provenance_extra": {"dates": _date_provenance(meta), "layout_split_pages": split,
                                     "text_repairs": repairs},
                "lines": lines})
    result = fin.import_report(db, rec, importer=importer, rights_attestation=rights_attestation)
    review = bool(unparsed or scanned or result["status"] != "reconciled")
    return {"status": "needs_review" if review else "reconciled", "sha256": sha, "stored_as": stored.name,
            "pages": len(doc.pages), "statement_pages": used, "scanned_pages": scanned,
            "lines_extracted": len(lines), "unparsed": unparsed, "text_repairs": repairs,
            "dates": _date_provenance(meta), "scope": meta["scope"], "import": result}
