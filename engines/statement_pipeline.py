"""Deterministic financial statement pipeline: extraction, evidence tagging, reconciliation, metrics, storage.

Stages (each returns its own result; nothing is accepted silently):
  1. extract      pdfplumber text per page; statements located by heading; lines parsed by the existing
                  deterministic parser. Lines that do not parse are returned as unparsed, never coerced.
  2. tag          every line carries its evidence: document, file hash, symbol, period, statement, label,
  amount,
                  restated flag, currency, unit scale, PDF page, extractor version, confidence.
  3. reconcile    balance sheet identity, cash flow identity, comparative consistency. Statuses are explicit.
  4. metrics      computed only from reported values; a missing input is reported, never zero.
  5. store        (optional) versioned rows in the archive database, through the repository.

OCR is not performed here. A page without a text layer is recorded as needing OCR. An OCR path would need a
separate
flag and approval.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from engines import comparative_reconciliation as cmp_mod
from engines import financials as fin
from engines import institutional_metrics as metrics
from engines import pdf_extraction as pe
from engines import statement_reconciliation as rec

MAPPINGS = fin.MAPPINGS_PATH
STATEMENT_CODES = {"BS": "BS", "IS": "IS", "CF": "CF", "EQ": "EQ"}
AUDITOR_PHRASES = (
    ("adverse", ("adverse opinion", "do not present fairly", "do not give a true and fair")),
    ("disclaimer", ("we do not express an opinion", "disclaimer of opinion", "unable to obtain sufficient")),
    ("qualified", ("qualified opinion", "except for the matter", "except for the effects")),
    ("unmodified_with_emphasis", ("emphasis of matter",)),
    ("unmodified", ("present fairly", "give a true and fair view", "unmodified opinion")),
)
NOTE_HEADINGS = {
    "borrowings": ("borrowings", "long term financing", "short term borrowings"),
    "receivables": ("trade debts", "trade receivables"),
    "receivables_ageing": ("ageing analysis", "aging analysis", "age analysis", "ageing of trade debts"),
    "contingencies": ("contingencies and commitments", "contingent liabilities"),
    "key_audit_matters": ("key audit matters",),
    "segment_reporting": ("segment reporting", "segment information"),
    "related_parties": ("related party transactions", "related parties"),
    "tax": ("taxation", "income tax"),
    "subsequent_events": ("subsequent events", "events after the reporting period"),
}


def load_mappings(path: Path | str = MAPPINGS) -> dict[str, dict[str, list[str]]]:
    """Corporate framework: statement -> canonical code -> labels. Keys are normalised labels."""
    corporate = json.loads(Path(path).read_text(encoding="utf-8"))["mappings"]["corporate"]
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for st, codes in corporate.items():
        for code, labels in codes.items():
            for lab in labels:
                out[st][fin.normalise_label(lab)] = code
    return out


def map_label(statement: str, label: str, mapping) -> tuple[str | None, float | None]:
    """Exact match on the normalised label. Confidence 1.0 for an exact match; unmapped labels stay
    unmapped."""
    code = mapping.get(statement, {}).get(fin.normalise_label(label))
    return (code, 1.0) if code else (None, None)


# ------------------------------------------------------------------ 1. extraction


def extract(path_or_doc, *, columns: list[str], statement_pages: dict[str, list[int]] | None = None) -> dict:
    doc = path_or_doc if isinstance(path_or_doc, pe.DocumentText) else pe.extract(path_or_doc)
    pages = statement_pages or pe.locate_statements(doc)
    lines, unparsed, used = [], [], {}
    for st in ("BS", "IS", "CF", "EQ"):
        if not pages.get(st):
            continue
        used[st] = pages[st]
        r = pe.to_statement_lines(doc, st, pages[st], columns=columns)
        lines.extend({**ln, "statement": st} for ln in r["lines"])
        unparsed.extend({**u, "statement": st} for u in r["unparsed"])
    scanned = [p.number for p in doc.pages if not p.has_text]
    return {
        "lines": lines,
        "unparsed": unparsed,
        "statement_pages": used,
        "scanned_pages": scanned,
        "pages": len(doc.pages),
        "notes": locate_notes(doc),
        "auditor": auditor_opinion(doc),
    }


def locate_notes(doc: pe.DocumentText) -> dict[str, list[int]]:
    """Pages whose text contains a note heading. Locates only: no figures are read from notes here."""
    found: dict[str, list[int]] = defaultdict(list)
    for pg in doc.pages:
        text = " ".join(pg.lines).lower()
        for key, phrases in NOTE_HEADINGS.items():
            if any(ph in text for ph in phrases):
                found[key].append(pg.number)
    return dict(found)


def auditor_opinion(doc: pe.DocumentText) -> dict:
    """Classify the auditor's opinion from explicit wording. If more than one class matches, the result is
    'ambiguous' and no class is chosen. Nothing is assumed clean."""
    hits: dict[str, list[int]] = defaultdict(list)
    kams: list[int] = []
    for pg in doc.pages:
        text = " ".join(pg.lines).lower()
        for cls, phrases in AUDITOR_PHRASES:
            if any(ph in text for ph in phrases):
                hits[cls].append(pg.number)
        if "key audit matters" in text:
            kams.append(pg.number)
    if not hits:
        return {"opinion": "not_found", "pages": [], "kam_pages": kams}
    if len(hits) > 1:
        return {"opinion": "ambiguous", "candidates": {k: v for k, v in hits.items()}, "kam_pages": kams}
    cls = next(iter(hits))
    return {"opinion": cls, "pages": hits[cls], "kam_pages": kams}


# ------------------------------------------------------------------ 2. evidence tagging


def tag(extracted: dict, *, document: dict, extractor_version: str, mapping) -> dict:
    """Attach full evidence to every line. `document` holds: document_id, file_hash, symbol, period_end,
    currency,
    unit_scale, consolidation, restated_flag."""
    need = ("document_id", "file_hash", "symbol", "period_end", "currency", "unit_scale", "consolidation")
    missing = [k for k in need if document.get(k) in (None, "")]
    if missing:
        raise ValueError(f"document evidence missing: {missing}")
    counters: dict[str, int] = defaultdict(int)
    tagged = []
    for ln in extracted["lines"]:
        st = ln["statement"]
        counters[st] += 1
        if ln.get("canonical_code") is not None:  # set by a rule-based extractor (e.g. notes)
            code, conf = ln["canonical_code"], ln.get("confidence")
        else:
            code, conf = map_label(st, ln["raw_label"], mapping)
        value = ln.get("value")
        is_comp = ln["column_period_end"] != document["period_end"]
        tagged.append(
            {
                "document_id": document["document_id"],
                "file_hash": document["file_hash"],
                "symbol": document["symbol"],
                "period_end": document["period_end"],
                "statement_type": st,
                "line_no": counters[st],
                "line_item_name": ln["raw_label"],
                "canonical_code": code,
                "column_period_end": ln["column_period_end"],
                "is_comparative": is_comp,
                "reported_amount": value,
                "value_state": "reported" if value is not None else "not_reported",
                "restated_flag": bool(document.get("restated_flag")),
                "currency": document["currency"],
                "unit_scale": document["unit_scale"],
                "consolidation": document["consolidation"],
                "pdf_page_number": ln.get("page"),
                "note_ref": ln.get("note_ref"),
                "extractor_version": extractor_version,
                "confidence": conf,
                "extraction_method": "pdf_text",
            }
        )
    return {
        "lines": tagged,
        "unparsed": extracted["unparsed"],
        "scanned_pages": extracted["scanned_pages"],
        "statement_pages": extracted["statement_pages"],
        "notes": extracted["notes"],
        "auditor": extracted["auditor"],
    }


def values_for(tagged_lines: list[dict], column: str) -> tuple[dict[str, float | None], list[str]]:
    """Canonical values for one column. A code reported with two different amounts is a conflict: it is
    reported
    and left out, never resolved by picking one."""
    seen: dict[str, set] = defaultdict(set)
    for ln in tagged_lines:
        if ln["canonical_code"] and ln["column_period_end"] == column:
            seen[ln["canonical_code"]].add(ln["reported_amount"])
    values, conflicts = {}, []
    for code, vals in seen.items():
        if len(vals) > 1:
            conflicts.append(code)
            values[code] = None
        else:
            values[code] = next(iter(vals))
    return values, conflicts


COMPARATIVE_CODES = (
    "total_assets",
    "total_liabilities",
    "total_equity",
    "revenue",
    "profit_after_tax",
    "cfo",
    "closing_cash",
    "cash_and_equivalents",
    "trade_receivables",
    "inventory",
)


def comparative_checks(lines: list[dict], prior: dict) -> list[dict]:
    """Compare the prior period as printed in this filing with the prior filing's own values. Findings are
    returned as checks; nothing is overwritten. The printed comparative column is read from this document."""
    prior_own, _ = values_for(prior["lines"], prior["period"])
    printed_cols = sorted({ln["column_period_end"] for ln in lines if ln["is_comparative"]})
    printed = printed_cols[0] if len(printed_cols) == 1 else "+".join(printed_cols) or "none"
    comp_values, _ = values_for(
        [ln for ln in lines if ln["is_comparative"] and ln["column_period_end"] == printed], printed
    )
    keep = set(COMPARATIVE_CODES)
    prior_own = {k: v for k, v in prior_own.items() if k in keep}
    comp_values = {k: v for k, v in comp_values.items() if k in keep}
    cur_unit = lines[0]["unit_scale"] if lines else 1
    prior_unit = prior["lines"][0]["unit_scale"] if prior["lines"] else 1
    findings = cmp_mod.compare(
        prior_own,
        comp_values,
        prior_period=prior["period"],
        printed_period=printed,
        prior_unit=prior_unit,
        current_unit=cur_unit,
    )
    return cmp_mod.to_checks(findings)


# ------------------------------------------------------------------ 3. reconciliation


def reconcile(tagged: dict, *, period_end: str, prior: dict | None = None) -> dict:
    """Balance sheet, cash flow and comparative checks. `prior` is the tagged result of the prior-year
    report."""
    lines = tagged["lines"]
    unit = lines[0]["unit_scale"] if lines else 1
    v, conflicts = values_for(lines, period_end)
    checks = [rec.balance_sheet(period_end, v), rec.cash_flow(period_end, v)]
    comp_checks = []
    if prior is not None:
        comp_checks = comparative_checks(lines, prior)
    all_checks = checks + comp_checks
    overall = rec.overall(all_checks)
    if conflicts:
        overall = rec.UNRECONCILED
    return {
        "checks": [_check_dict(c) if isinstance(c, rec.Check) else c for c in all_checks],
        "overall": overall,
        "conflicts": conflicts,
        "unit_scale": unit,
    }


def _check_dict(c: rec.Check) -> dict:
    return {
        "check": c.name,
        "column_period_end": c.column_period_end,
        "reported": c.reported,
        "expected": c.expected,
        "discrepancy": c.discrepancy,
        "allowance": c.allowance,
        "status": c.status,
        "missing": list(c.missing),
    }


# ------------------------------------------------------------------ 4. metrics


def compute_metrics(tagged: dict, *, period_end: str, prior: dict | None = None) -> list[dict]:
    v, _ = values_for(tagged["lines"], period_end)
    p = None
    if prior is not None:
        p, _ = values_for(prior["lines"], prior["period"])
    return metrics.all_metrics(v, p)


# ------------------------------------------------------------------ 5. store (archive repository only)


def store(
    archive_db,
    *,
    registry_meta: dict,
    file_size_bytes: int,
    tagged: dict,
    reconciliation: dict,
    extractor_version: str,
) -> dict:
    from database import financial_repo as repo

    reg = repo.register_document(archive_db, registry_meta)
    sha = registry_meta["report_sha256"]
    repo.record_document_file(archive_db, report_sha256=sha, file_size_bytes=file_size_bytes)
    run = repo.create_extraction_run(archive_db, report_sha256=sha, extractor_version=extractor_version)
    lines = repo.store_versioned_lines(
        archive_db,
        run["run_id"],
        tagged["lines"],
        extractor_version=extractor_version,
        symbol=registry_meta["psx_symbol"],
        document_id=sha,
    )
    rec_stored = repo.store_versioned_reconciliation(
        archive_db,
        run["run_id"],
        reconciliation["checks"],
        consolidation=tagged["lines"][0]["consolidation"] if tagged["lines"] else "unconsolidated",
    )
    status = "reconciled" if reconciliation["overall"] in (rec.RECONCILED, rec.ROUNDED) else "needs_review"
    repo.record_processing(
        archive_db, sha, status, f"extractor {extractor_version}: {reconciliation['overall']}"
    )
    return {
        "registration": reg["status"],
        "run": run["status"],
        "run_id": run["run_id"],
        "lines": lines,
        "reconciliation": rec_stored,
        "status": status,
    }
