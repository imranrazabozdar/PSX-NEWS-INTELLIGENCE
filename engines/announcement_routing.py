"""Announcement routing: metadata to the operational database, parsed structure to the archive.

What this module does NOT do: it does not fetch anything. The PSX announcements portal is RESTRICTED in
docs/SOURCE_ACCESS_REGISTER.md (automated retrieval prohibited without written permission), so no collector
for it exists here. Records arrive from a PERMITTED route the owner has named, by `source_id`.

Routing rules (fail closed):
* No record is routed unless its source_id is in `permitted_sources`. An empty set routes nothing.
* A record carrying binary content (pdf, pdf_bytes, content, body, file) is refused. Only the PDF's
  SHA-256 may be referenced. Raw PDF bytes never reach either database.
* Every record writes lightweight metadata to the operational database (deduplicated by the source
  item store).
* Parsed structure goes to the archive only: a reconciled financial summary as tuples, or a material
  disclosure as bounded JSON. A financial summary that fails the identity gate is not archived, and the
  reason is returned.
* When the archive is supplied, the company's multi-period history is attached to the result, so the alert
  carries its depth. The source of that history is stated (see engines/history.py).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from database import financial_repo as repo
from database import repositories as reps
from engines import history as hist

KINDS = ("financial_statement", "material_disclosure", "other")
FORBIDDEN_KEYS = {"pdf", "pdf_bytes", "content", "body", "file", "file_bytes", "raw", "html"}
REQUIRED = ("source_id", "external_id", "ticker", "title", "published_at_utc")
FINANCIAL_WORDS = (
    "financial statement",
    "annual report",
    "half yearly",
    "half-yearly",
    "quarterly",
    "interim",
    "financial results",
    "accounts",
)
MATERIAL_WORDS = (
    "material information",
    "board meeting",
    "dividend",
    "right issue",
    "bonus",
    "acquisition",
    "merger",
    "suspension",
    "auditor",
    "circular",
    "notice of meeting",
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(title: str, declared: str | None = None) -> str:
    if declared in KINDS:
        return declared
    t = title.lower()
    if any(w in t for w in FINANCIAL_WORDS):
        return "financial_statement"
    if any(w in t for w in MATERIAL_WORDS):
        return "material_disclosure"
    return "other"


def route(ann: dict, *, main_db, archive_db=None, permitted_sources: frozenset[str] | set[str]) -> dict:
    if not permitted_sources:
        return {"status": "refused", "reason": "no permitted source configured; nothing is routed"}
    if ann.get("source_id") not in permitted_sources:
        return {"status": "refused", "reason": f"source {ann.get('source_id')!r} is not a permitted route"}
    bad = sorted(FORBIDDEN_KEYS & set(ann))
    if bad:
        return {"status": "refused", "reason": f"binary or body content is not accepted: {bad}"}
    missing = [k for k in REQUIRED if not ann.get(k)]
    if missing:
        return {"status": "refused", "reason": f"missing fields: {missing}"}
    pdf_sha = ann.get("pdf_sha256")
    if pdf_sha is not None and (not isinstance(pdf_sha, str) or len(pdf_sha) != 64):
        return {"status": "refused", "reason": "pdf_sha256 must be the 64-character hash of the vault file"}

    kind = classify(ann["title"], ann.get("kind"))
    meta_hash = hashlib.sha256(
        json.dumps(
            {
                k: ann.get(k)
                for k in ("source_id", "external_id", "ticker", "title", "published_at_utc", "pdf_sha256")
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    main = reps.record_source_item(
        main_db,
        source_id=ann["source_id"],
        collected_at_utc=_now(),
        url=ann.get("url"),
        external_id=ann["external_id"],
        content_hash=meta_hash,
        title=ann["title"],
        published_at_utc=ann["published_at_utc"],
        access_status="permitted",
        provenance={"router": "announcement_routing", "kind": kind, "pdf_sha256": pdf_sha},
    )
    result = {
        "status": "routed",
        "kind": kind,
        "main": {"outcome": main.outcome},
        "archive": {"status": "not_configured"},
    }

    company = reps.company_by_ticker(main_db, ann["ticker"])
    if company is None:
        result["archive"] = {"status": "skipped", "reason": f"ticker {ann['ticker']!r} is not in the master"}
        return result
    company_id = company["company_id"]
    if archive_db is not None:
        result["archive"] = _archive(archive_db, ann, kind, company_id, pdf_sha)
        result["history"] = hist.load_history(main_db, archive_db, company_id, scope="unconsolidated")
    return result


def _archive(archive_db, ann: dict, kind: str, company_id: str, pdf_sha: str | None) -> dict:
    parsed = ann.get("parsed") or {}
    if kind == "financial_statement" and parsed.get("summary"):
        out = repo.archive_summary(archive_db, parsed["summary"], company_id=company_id)
        return {**out, "status": "archived" if out.get("archived") else "refused"}
    if kind in ("financial_statement", "material_disclosure"):
        out = repo.archive_disclosure(
            archive_db,
            company_id=company_id,
            kind=kind,
            published_at_utc=ann["published_at_utc"],
            title=ann["title"],
            payload={"fields": parsed.get("fields", {})},
            pdf_sha256=pdf_sha,
        )
        return {**out, "status": "archived" if out.get("archived") else "refused"}
    return {"status": "not_archived", "reason": "kind 'other' is kept as metadata only"}
