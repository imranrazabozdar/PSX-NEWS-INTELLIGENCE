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
import re
from collections import defaultdict
from pathlib import Path

from engines import audit_extraction as ae
from engines import comparative_reconciliation as cmp_mod
from engines import financials as fin
from engines import institutional_metrics as metrics
from engines import notes_extraction as ne
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


FRAMEWORKS = ("corporate", "bank", "insurer")


def load_mappings(
    path: Path | str = MAPPINGS, *, framework: str = "corporate"
) -> dict[str, dict[str, list[str]]]:
    """One framework's mapping: statement -> canonical code -> labels. Keys are normalised labels. Frameworks
    are kept apart: a bank label is never looked up in the corporate table, or the reverse."""
    if framework not in FRAMEWORKS:
        raise ValueError(f"unknown mapping framework: {framework}")
    table = json.loads(Path(path).read_text(encoding="utf-8"))["mappings"][framework]
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for st, codes in table.items():
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


# Balance sheet components the printed totals are the sum of (SBP format prints totals with no label).
BS_ASSET_CODES = (
    "cash_and_equivalents",
    "balances_with_other_banks",
    "lendings_to_fis",
    "investments",
    "advances_net",
    "fixed_assets",
    "right_of_use_assets",
    "intangible_assets",
    "deferred_tax_assets",
    "other_assets",
)
BS_LIABILITY_CODES = (
    "bills_payable",
    "borrowings",
    "deposits",
    "lease_liabilities",
    "subordinated_debt",
    "deferred_tax_liabilities",
    "other_liabilities",
)
_NUMBER_TOKEN = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")


def _numbers_only_row(text: str, n: int) -> list[float] | None:
    """A row that is nothing but n printed figures (no label). Brackets are negatives, as in the
    statements."""
    s = (text or "").strip()
    toks = _NUMBER_TOKEN.findall(s)
    if len(toks) != n or " ".join(toks) != " ".join(s.split()):
        return None
    out = []
    for t in toks:
        neg = t.startswith("(") and t.endswith(")")
        v = float(t.strip("()").replace(",", "").replace("-", "") or 0)
        out.append(-v if neg or t.startswith("-") else v)
    return out


# (component codes, total code) per framework. The corporate balance sheet prints unlabelled totals for assets
# and for share capital and reserves; its liabilities total is labelled, so it is never inferred.
CORPORATE_ASSET_CODES = (
    "ppe",
    "intangible_assets",
    "development_production_assets",
    "exploration_evaluation_assets",
    "lt_investments_associates",
    "lt_investments",
    "lt_investments_amortised_cost",
    "current_lt_investments",
    "lt_loans",
    "lt_loans_advances_deposits",
    "lt_advances_prepayments",
    "lease_receivables_noncurrent",
    "current_lease_receivables",
    "stores_spares",
    "inventory",
    "trade_receivables",
    "loans_advances_current",
    "deposits_short_term_prepayments",
    "other_receivables",
    "tax_refunds_due",
    "income_tax_advance",
    "other_financial_assets",
    "short_term_investments",
    "cash_and_equivalents",
)
CORPORATE_EQUITY_CODES = ("share_capital", "reserves", "unappropriated_profit")
CORPORATE_LIABILITY_CODES = (
    "lt_deposits_payable",
    "long_term_borrowings",
    "deferred_govt_grant",
    "staff_gratuity",
    "deferred_taxation",
    "decommissioning_provision",
    "lt_lease_liability",
    "st_lease_liability",
    "trade_payables",
    "current_maturity_lt_financing",
    "short_term_borrowings",
    "unpaid_dividend",
    "unclaimed_dividend",
    "accrued_markup",
    "taxation_payable",
)
CORPORATE_CURRENT_ASSET_CODES = (
    "inventory",
    "stores_spares",
    "trade_receivables",
    "loans_advances_current",
    "deposits_short_term_prepayments",
    "other_receivables",
    "tax_refunds_due",
    "income_tax_advance",
    "short_term_investments",
    "current_lt_investments",
    "current_lease_receivables",
    "other_financial_assets",
    "cash_and_equivalents",
)
CORPORATE_CURRENT_LIABILITY_CODES = (
    "trade_payables",
    "current_maturity_lt_financing",
    "short_term_borrowings",
    "unpaid_dividend",
    "unclaimed_dividend",
    "accrued_markup",
    "taxation_payable",
    "st_lease_liability",
)


def total_groups(framework: str) -> list[tuple[tuple[str, ...], str, str, str, str]]:
    """(component codes, total code, section the components are in, statement the printed total is read from,
    stored statement type) per framework. The OCI group reads OCI rows (stored as IS) and their printed
    subtotal."""
    if framework == "bank":
        return [
            (BS_ASSET_CODES, "total_assets", "BS", "BS", "BS"),
            (BS_LIABILITY_CODES, "total_liabilities", "BS", "BS", "BS"),
        ]
    return [
        (CORPORATE_ASSET_CODES, "total_assets", "BS", "BS", "BS"),
        (CORPORATE_EQUITY_CODES, "total_equity", "BS", "BS", "BS"),
        (CORPORATE_LIABILITY_CODES, "total_liabilities", "BS", "BS", "BS"),
        (CORPORATE_CURRENT_ASSET_CODES, "total_current_assets", "BS", "BS", "BS"),
        (CORPORATE_CURRENT_LIABILITY_CODES, "total_current_liabilities", "BS", "BS", "BS"),
        (OCI_COMPONENT_CODES, "other_comprehensive_income", "OCI", "OCI", "IS"),
    ]


def infer_unlabelled_totals(
    tagged: list[dict], unparsed: list[dict], *, columns: list[str], framework: str = "bank"
) -> list[dict]:
    """Printed totals that carry no label (balance sheet totals, current subtotals, the OCI subtotal).

    A label-less figure row becomes a total only when, for a column, it equals the sum of the mapped
    components of
    the same section, within one printed unit per component (the reconciliation's allowance). Ambiguous
    rows (two
    different values) and unmatched rows are left unparsed. The same printed row on both halves of a spread
    is one
    value. The returned record says it was inferred. Partial records; the caller fills the document fields."""
    out: list[dict] = []
    n = len(columns)
    for code_group, total_code, section, cand_stmt, stored_type in total_groups(framework):
        candidates = [u for u in unparsed if u.get("statement") == cand_stmt and u.get("line")]
        for i, col in enumerate(columns):
            present = [
                ln
                for ln in tagged
                if (ln.get("statement_section") or ln.get("statement_type")) == section
                and ln.get("canonical_code") in code_group
                and ln.get("column_period_end") == col
                and ln.get("reported_amount") is not None
            ]
            if not present or any(
                ln.get("canonical_code") == total_code and ln.get("column_period_end") == col for ln in tagged
            ):
                continue
            total = sum(ln["reported_amount"] for ln in present)
            allow = len(present) * 1.0
            matches = []
            for u in candidates:
                vals = _numbers_only_row(u["line"], n)
                if vals is not None and abs(vals[i] - total) <= allow:
                    matches.append((u, vals[i]))
            if not matches or len({round(v, 2) for _, v in matches}) != 1:
                continue
            u, value = matches[0]
            rec = {
                "statement_type": stored_type,
                "line_item_name": (
                    f"[unlabelled printed total: equals the sum of {len(present)} mapped components]"
                ),
                "column_period_end": col,
                "reported_amount": value,
                "pdf_page_number": u.get("page"),
                "canonical_code": total_code,
                "confidence": 0.9,
                "extraction_engine": u.get("extraction_engine"),
            }
            if section == "OCI":
                rec["statement_section"] = "OCI"
            out.append(rec)
    return out


def extract(
    path_or_doc,
    *,
    columns: list[str],
    statement_pages: dict[str, list[int]] | None = None,
    statement_regions: dict[str, tuple[int, str]] | None = None,
    region_reader=None,
) -> dict:
    """Parse the statements. `statement_regions` (owner-confirmed) gives, per statement, (page, side): the
    page
    half that holds it, read through `region_reader(page, side) -> lines`. A region is parsed as its own page
    so the other statement on a spread is never mixed in."""
    doc = path_or_doc if isinstance(path_or_doc, pe.DocumentText) else pe.extract(path_or_doc)
    regions = statement_regions or {}
    pages = statement_pages or pe.locate_statements(doc)
    lines, unparsed, used = [], [], {}
    raw_lines: dict[str, list[str]] = {}  # text of statements whose figures are read by a dedicated parser
    for st in ("BS", "IS", "OCI", "CF", "EQ"):
        if st in regions:
            if region_reader is None:
                raise ValueError("statement_regions need a region_reader")
            spec = regions[st]
            # one (page, side) pair, or a list of them for a statement printed across the halves of a spread
            specs = [spec] if isinstance(spec, tuple) else list(spec)
            used[st] = sorted({page for page, _ in specs})
            for page, side in specs:
                region_lines = region_reader(page, side)
                rdoc = pe.DocumentText(
                    [
                        pe.Page(
                            number=page,
                            lines=region_lines,
                            has_text=sum(len(x) for x in region_lines) >= 20,
                            extraction_method="pdftotext_layout_region",
                        )
                    ]
                )
                r = pe.to_statement_lines(rdoc, st, [page], columns=columns)
                if st == "EQ":
                    raw_lines.setdefault("EQ", []).extend(region_lines)
                lines.extend({**ln, "statement": st} for ln in r["lines"])
                unparsed.extend({**u, "statement": st} for u in r["unparsed"])
            continue
        if not pages.get(st):
            continue
        used[st] = pages[st]
        r = pe.to_statement_lines(doc, st, pages[st], columns=columns)
        if st == "EQ":
            raw_lines["EQ"] = [ln for pg in doc.pages if pg.number in pages[st] for ln in pg.lines]
        lines.extend({**ln, "statement": st} for ln in r["lines"])
        unparsed.extend({**u, "statement": st} for u in r["unparsed"])
    scanned = [p.number for p in doc.pages if not p.has_text]
    nx = ne.extract_notes(doc, columns=columns)
    return {
        "lines": lines,
        "raw_lines": raw_lines,
        "unparsed": unparsed,
        "statement_pages": used,
        "scanned_pages": scanned,
        "pages": len(doc.pages),
        "extraction_methods": doc.method_counts(),
        "extraction_warnings": list(doc.warnings),
        "notes": locate_notes(doc),
        "auditor": auditor_opinion(doc),
        "note_lines": nx["lines"],
        "note_index": nx["notes"],
        "note_unparsed": nx["unparsed"],
        "audit": ae.audit_summary(doc),
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


def tag(extracted: dict, *, document: dict, extractor_version: str, mapping, framework: str = "bank") -> dict:
    """Attach full evidence to every line. `document` holds: document_id, file_hash, symbol, period_end,
    currency,
    unit_scale, consolidation, restated_flag."""
    need = ("document_id", "file_hash", "symbol", "period_end", "currency", "unit_scale", "consolidation")
    missing = [k for k in need if document.get(k) in (None, "")]
    if missing:
        raise ValueError(f"document evidence missing: {missing}")
    counters: dict[str, int] = defaultdict(int)
    tagged = []
    for ln in list(extracted["lines"]) + list(extracted.get("note_lines", [])):
        st = ln["statement"]
        # OCI is printed in the statement of profit or loss and other comprehensive income. The database's
        # statement CHECK (migration 0001, immutable) allows IS, BS, CF, EQ and note only, so OCI rows
        # are stored as IS and keep their section in statement_section.
        db_st = "IS" if st == "OCI" else st
        counters[db_st] += 1
        if ln.get("canonical_code") is not None:  # set by a rule-based extractor (e.g. notes)
            code, conf = ln["canonical_code"], ln.get("confidence")
        else:
            # the context (parent component + tax effect) decides first; the plain label is the fallback
            code, conf = (None, None)
            if ln.get("context_label"):
                code, conf = map_label(db_st, ln["context_label"], mapping)
            if code is None:
                code, conf = map_label(db_st, ln["raw_label"], mapping)
        value = ln.get("value")
        is_comp = ln["column_period_end"] != document["period_end"]
        tagged.append(
            {
                "document_id": document["document_id"],
                "file_hash": document["file_hash"],
                "symbol": document["symbol"],
                "period_end": document["period_end"],
                "statement_type": db_st,
                "statement_section": st,
                "line_no": counters[db_st],
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
                "extraction_method": "pdf_text",  # database category (migrations 0001-0005 are immutable)
                "extraction_engine": ln.get("extraction_engine") or "unknown",
                "parent_context": ln.get("parent_label"),
            }
        )
    columns = list(dict.fromkeys(ln["column_period_end"] for ln in extracted["lines"]))
    for rec_ in infer_unlabelled_totals(tagged, extracted["unparsed"], columns=columns, framework=framework):
        st_type = rec_["statement_type"]
        counters[st_type] += 1
        tagged.append(
            {
                "document_id": document["document_id"],
                "file_hash": document["file_hash"],
                "symbol": document["symbol"],
                "period_end": document["period_end"],
                "statement_type": st_type,
                "statement_section": rec_.get("statement_section", st_type),
                "line_no": counters[st_type],
                "line_item_name": rec_["line_item_name"],
                "canonical_code": rec_["canonical_code"],
                "column_period_end": rec_["column_period_end"],
                "is_comparative": rec_["column_period_end"] != document["period_end"],
                "reported_amount": rec_["reported_amount"],
                "value_state": "reported",
                "restated_flag": bool(document.get("restated_flag")),
                "currency": document["currency"],
                "unit_scale": document["unit_scale"],
                "consolidation": document["consolidation"],
                "pdf_page_number": rec_["pdf_page_number"],
                "note_ref": None,
                "extractor_version": extractor_version,
                "confidence": rec_["confidence"],
                "extraction_method": "pdf_text",
                "extraction_engine": rec_["extraction_engine"] or "unknown",
            }
        )
    return {
        "lines": tagged,
        "raw_lines": extracted.get("raw_lines", {}),
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
            # a figure printed as a dash is nil: it neither conflicts with a printed amount nor counts as one
            if ln["reported_amount"] is None:
                seen.setdefault(ln["canonical_code"], set())
                continue
            seen[ln["canonical_code"]].add(ln["reported_amount"])
    values, conflicts = {}, []
    for code, vals in seen.items():
        if not vals:  # only dashes: not reported
            values[code] = None
        elif len(vals) > 1:
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


def _oci_total(lines: list[dict], column: str) -> float | None:
    """Other comprehensive income for a column: the sum of the mapped OCI components. None when no OCI
    component
    was mapped (the check then does not run). A component printed as a dash counts as nil."""
    parts = [
        ln["reported_amount"] or 0.0
        for ln in lines
        if ln.get("canonical_code") in OCI_COMPONENT_CODES and ln["column_period_end"] == column
    ]
    return sum(parts) if parts else None


OCI_COMPONENT_CODES = (
    # bank layout (OCI printed in the bank's own statement)
    "oci_translation",
    "oci_debt_fvoci",
    "oci_equity_fvoci",
    "oci_remeasurement_defined_benefit",
    "oci_ppe_revaluation",
    "oci_non_banking_assets",
    # corporate layout (OGDC): remeasurement, its tax, associates and translation
    "oci_remeasurement_employee_benefits",
    "oci_tax_on_remeasurement",
    "oci_associates_remeasurement",
    "oci_translation_associate",
    "oci_associates_translation",
    "oci_fvoci_equity",
    "oci_tax_on_fvoci_equity",
)


def reconcile(tagged: dict, *, period_end: str, prior: dict | None = None) -> dict:
    """Balance sheet, cash flow and comparative checks. `prior` is the tagged result of the prior-year
    report."""
    lines = tagged["lines"]
    unit = lines[0]["unit_scale"] if lines else 1
    v, conflicts = values_for(lines, period_end)
    printed_oci = v.get("other_comprehensive_income")  # the printed OCI total, when the statement prints one
    comp_oci = _oci_total(lines, period_end)  # the sum of the mapped OCI components
    if comp_oci is not None:
        v["oci_components_total"] = comp_oci
        if printed_oci is None:  # bank layout: no printed total, so the components give the OCI
            v["other_comprehensive_income"] = comp_oci
    checks = [rec.balance_sheet(period_end, v), rec.cash_flow(period_end, v)]
    eq_lines = tagged.get("raw_lines", {}).get("EQ")
    if eq_lines:  # the statement of changes in equity closes at the balance sheet's total equity
        from engines import equity_statement as eqs

        closing = eqs.closing_total(eq_lines, period_end)
        checks.append(rec.equity_statement(
            period_end, closing["total"] if closing else None, v.get("total_equity")))
    if v.get("other_comprehensive_income") is not None:  # printed total or summed components
        checks.append(rec.comprehensive_income(period_end, v))
    if printed_oci is not None and comp_oci is not None:  # the printed total must equal its components
        checks.append(rec.oci_components(period_end, v))
    checks.append(rec.income_statement(period_end, v))
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


def audit_payload(audit: dict) -> dict:
    """The audit trail kept in the archive: the opinion class, exact excerpts and pages, and KAM headings with
    their excerpts. No full text of the report is stored."""
    op = audit["opinion"]
    return {
        "opinion": op.get("opinion"),
        "opinion_evidence": op.get("evidence", []),
        "opinion_candidates": op.get("candidates", {}),
        "emphasis_of_matter": audit["emphasis_of_matter"],
        "going_concern_material_uncertainty": audit["going_concern_material_uncertainty"],
        "key_audit_matters": [
            {
                "heading": k["heading"],
                "page": k["page"],
                "excerpt": k["excerpt"],
                "confidence": k["confidence"],
            }
            for k in audit["kams"]
        ],
    }


_CHECK_STATEMENT = {
    "equity_statement": "EQ",
    "balance_sheet": "BS",
    "income_statement": "IS",
    "comprehensive_income": "OCI",
    "oci_components": "OCI",
    "cash_flow": "CF",
}


_CHECK_IDENTITY = {
    "balance_sheet": "assets_equal_liabilities_plus_equity",
    "income_statement": "pbt_less_tax_equals_pat",
    "comprehensive_income": "pat_plus_oci_equals_total_comprehensive_income",
    "cash_flow": "opening_cash_plus_movement_equals_closing_cash",
    "equity_statement": "equity_closing_equals_balance_sheet_equity",
    "oci_components": "oci_components_equal_printed_total",
}


def identity_rows(reconciliation: dict, *, consolidation: str) -> list[dict]:
    """One identity result per reconciliation check, with its delta. An identity whose inputs are not
    extracted is insufficient_data with no delta: it is never shown as reconciled."""
    from engines import status_vocabulary as sv

    rows = []
    for c in reconciliation["checks"]:
        identity = _CHECK_IDENTITY.get(c["check"])
        if identity is None:
            continue
        if c["status"] == "INSUFFICIENT_DATA":
            status = "insufficient_data"
            reason = "inputs not extracted: " + ", ".join(c.get("missing") or ["unknown"])
            rows.append({"identity": identity, "consolidation": consolidation,
                         "column_period_end": c["column_period_end"], "left_value": None,
                         "right_value": None, "delta": None, "tolerance": c.get("allowance") or 0.0,
                         "status": status, "reason": reason})
            continue
        status = sv.from_check_status(c["status"])
        rows.append({"identity": identity, "consolidation": consolidation,
                     "column_period_end": c["column_period_end"], "left_value": c["reported"],
                     "right_value": c["expected"], "delta": c["discrepancy"],
                     "tolerance": c["allowance"], "status": status,
                     "reason": f"reported {c['reported']} vs expected {c['expected']}"})
    return rows


def statuses_for(tagged: dict, reconciliation: dict, *, ias7_status: str | None = None) -> tuple[list, list]:
    """Statement and fact status rows for one run, from the identity checks, the mapping and the IAS 7
    result. A fact takes its statement's status; an unmapped line is unmapped; cash equivalents are not
    verifiable when IAS 7 says the maturity cannot be shown from the disclosure."""
    from engines import status_vocabulary as sv

    lines = tagged["lines"]
    consolidation = lines[0]["consolidation"] if lines else "unconsolidated"
    statements: list[dict] = []
    stmt_status: dict[tuple[str, str], str] = {}
    for stmt in ("BS", "IS", "OCI", "CF", "EQ"):
        columns = sorted({c["column_period_end"] for c in reconciliation["checks"]
                          if _CHECK_STATEMENT.get(c["check"]) == stmt} |
                         {ln["column_period_end"] for ln in lines if ln["statement_type"] == stmt})
        for col in columns:
            checks = [c["status"] for c in reconciliation["checks"]
                      if _CHECK_STATEMENT.get(c["check"]) == stmt and c["column_period_end"] == col]
            unmapped = sum(1 for ln in lines if ln["statement_type"] == stmt
                           and ln["column_period_end"] == col and not ln.get("canonical_code"))
            # IAS 7 does not change a statement's arithmetic; its effect is on the cash-equivalent fact only.
            status, reason = sv.statement_status(checks, unmapped=unmapped)
            stmt_status[(stmt, col)] = status
            statements.append({"statement_type": stmt, "consolidation": consolidation,
                               "column_period_end": col, "status": status, "reason": reason})
    facts: list[dict] = []
    for ln in lines:
        if ln["statement_type"] not in ("BS", "IS", "OCI", "CF", "EQ"):
            continue
        status, reason = sv.fact_status(ln.get("canonical_code"), ln["statement_type"], ias7=ias7_status)
        if status == "reconciled":
            status = stmt_status.get((ln["statement_type"], ln["column_period_end"]), "insufficient_data")
            reason = f"statement {ln['statement_type']} is {status}"
        facts.append({"statement_type": ln["statement_type"], "line_no": ln["line_no"],
                      "column_period_end": ln["column_period_end"], "consolidation": ln["consolidation"],
                      "status": status, "reason": reason})
    return statements, facts


def store(
    archive_db,
    *,
    registry_meta: dict,
    file_size_bytes: int,
    tagged: dict,
    reconciliation: dict,
    extractor_version: str,
    audit: dict | None = None,
    ias7_status: str | None = None,
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
    statements, facts = statuses_for(tagged, reconciliation, ias7_status=ias7_status)
    status_stored = repo.store_statement_statuses(archive_db, run["run_id"], statements)
    fact_stored = repo.store_fact_statuses(archive_db, run["run_id"], facts)
    consolidation = tagged["lines"][0]["consolidation"] if tagged["lines"] else "unconsolidated"
    identity_stored = repo.store_identity_checks(
        archive_db, run["run_id"], identity_rows(reconciliation, consolidation=consolidation)
    )
    audit_stored = None
    if audit is not None:
        audit_stored = repo.archive_disclosure(
            archive_db,
            company_id=registry_meta["company_id"],
            kind="financial_statement",
            published_at_utc=registry_meta.get("publication_date") or registry_meta["retrieved_at_utc"],
            title=f"Auditor's report {registry_meta['period_end']} ({registry_meta['psx_symbol']})",
            payload=audit_payload(audit),
            pdf_sha256=sha,
        )
    status = "reconciled" if reconciliation["overall"] in (rec.RECONCILED, rec.ROUNDED) else "needs_review"
    repo.record_processing(
        archive_db, sha, status, f"extractor {extractor_version}: {reconciliation['overall']}"
    )
    return {
        "audit_disclosure": audit_stored,
        "registration": reg["status"],
        "run": run["status"],
        "run_id": run["run_id"],
        "statement_statuses": status_stored["recorded"],
        "identity_checks": identity_stored["recorded"],
        "fact_statuses": fact_stored["recorded"],
        "lines": lines,
        "reconciliation": rec_stored,
        "status": status,
    }
