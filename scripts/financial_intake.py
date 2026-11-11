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

from engines import audit_extraction as ae
from engines import cash_equivalents as ce
from engines import document_intake as di
from engines import notes_extraction as ne
from engines import page_layout as pl
from engines import pdf_extraction as pe
from engines import pdf_reader as pe_reader
from engines import statement_pipeline as sp
from engines import trade_debts_note as tdn

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
    framework: str = "corporate",
    statement_pages: dict[str, list[int]] | None = None,
    statement_regions: dict[str, tuple[int, str]] | None = None,
    auditor_pages: list[int] | None = None,
    kam_pages: list[int] | None = None,
) -> tuple[dict, dict]:
    doc = pe.extract(path)
    ex = sp.extract(
        doc,
        columns=columns,
        statement_pages=statement_pages,
        statement_regions=statement_regions,
        region_reader=lambda page, side: pe_reader.region_lines(path, page, side),
    )
    ex["audit"] = _audit_layout(path, doc, ex["audit"], auditor_pages, kam_pages)
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
    tagged = sp.tag(
        ex,
        document=document,
        extractor_version=EXTRACTOR_VERSION,
        mapping=sp.load_mappings(framework=framework),
        framework=framework,
    )
    tagged["extraction_methods"] = ex.get("extraction_methods", {})
    tagged["extraction_warnings"] = ex.get("extraction_warnings", [])
    return tagged, ex


STATEMENT_CODES = ("BS", "IS", "OCI", "CF", "EQ")
NOTE_KEYS = (
    "NOTE_TRADE_DEBTS",
    "NOTE_AGEING",
    "NOTE_COUNTERPARTY",
    "NOTE_CASH",
    "NOTE_MATURITY",
    "NOTE_CREDIT_QUALITY",
)
PAGE_MAP_KEYS = ("BS", "IS", "OCI", "CF", "EQ", "AUDITOR", "KAM") + NOTE_KEYS


def parse_page_map(path: Path) -> dict:
    """Owner's page map for one document (JSON). Keys: BS, IS, OCI, CF, EQ (a page, with L or R for the
    half of a
    spread: "45R"), AUDITOR (the auditor's report pages, e.g. "41-42"), KAM (pages holding the KAM table, e.g.
    "42"). Unknown keys and bad values are refused. Returns the same shapes as parse_statement_spec, plus
    auditor_pages and kam_pages. When given, it replaces automatic page detection for the run."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("page map must be a JSON object")
    unknown = sorted(set(raw) - set(PAGE_MAP_KEYS))
    if unknown:
        raise ValueError(f"unknown page-map keys: {unknown}; allowed: {list(PAGE_MAP_KEYS)}")
    stmt_spec = ",".join(f"{k}={v}" for k, v in raw.items() if k in STATEMENT_CODES)
    pages, regions = parse_statement_spec(stmt_spec)
    auditor = _page_list(raw["AUDITOR"], "AUDITOR") if "AUDITOR" in raw else None
    kam = _kam_list(raw["KAM"]) if "KAM" in raw else None
    notes = {k: _ordered_regions(raw[k], k) for k in NOTE_KEYS if k in raw}
    return {
        "statement_pages": pages,
        "statement_regions": regions,
        "auditor_pages": auditor,
        "kam_pages": kam,
        "notes": notes,
    }


def _page_list(value: str, key: str) -> list[int]:
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            if not (a.strip().isdigit() and b.strip().isdigit() and 1 <= int(a) <= int(b)):
                raise ValueError(f"bad page range for {key}: {value!r}")
            out.extend(range(int(a), int(b) + 1))
        elif part.isdigit() and int(part) >= 1:
            out.append(int(part))
        else:
            raise ValueError(f"bad page for {key}: {value!r}")
    return sorted(set(out))


def _ordered_regions(value: str, key: str) -> list[tuple[int, str]]:
    """Note pages in reading order, each optionally a half of a spread: "33R+34R+34L"."""
    out: list[tuple[int, str]] = []
    for part in str(value).split("+"):
        part = part.strip().upper()
        side = part[-1:] if part[-1:] in ("L", "R") else ""
        digits = part[: len(part) - len(side)]
        if not digits.isdigit() or int(digits) < 1:
            raise ValueError(f"bad page for {key}: {value!r}")
        out.append((int(digits), side))
    return out


def _notes_block(path: Path, notes: dict | None, tagged: dict, period_end: str) -> dict:
    """Notes 21 (trade debts, ageing, circular debt, counterparties), 41 (cash) and 26.1 (maturities), read
    from
    the owner's note pages. Without the note keys in the page map nothing is read and nothing is assumed."""
    if not notes:
        return {"status": "not_requested", "reason": "no note pages in the page map"}
    layout = pe_reader.read_layout_pages(path)

    def block(key: str) -> tuple[list[str], list[str]]:
        lines: list[str] = []
        pages: list[str] = []
        for page, side in notes.get(key, []):
            lines += pe_reader.region_lines(path, page, side) if side else layout[page - 1]
            pages.append(f"{page}{side}")
        return lines, pages

    note_lines, note_pages = block("NOTE_TRADE_DEBTS")
    age_lines, age_pages = block("NOTE_AGEING")
    cp_lines, cp_pages = block("NOTE_COUNTERPARTY")
    cash_lines, cash_pages = block("NOTE_CASH")
    mat_lines, mat_pages = block("NOTE_MATURITY")
    cq_lines, cq_pages = block("NOTE_CREDIT_QUALITY")
    trade = tdn.extract_note_21(
        note_lines=note_lines,
        ageing_lines=age_lines,
        counterparty_lines=cp_lines,
        pages={"note": note_pages, "ageing": age_pages, "counterparty": cp_pages},
    )
    n41 = ce.parse_note_41(cash_lines, pages=cash_pages)
    mat = ce.maturity_terms(mat_lines, pages=mat_pages)
    credit = tdn.parse_credit_quality(cq_lines, pages=cq_pages) if cq_lines else None
    values = sp.values_for(tagged["lines"], period_end)[0]
    cash = ce.reconcile_cash(
        bs_cash=values.get("cash_and_equivalents"),
        cf_closing=values.get("closing_cash"),
        note41=n41,
        maturity=mat,
    )
    return {
        "trade_debts_note_21": trade,
        "cash_note_41": n41,
        "maturity_note_26_1": mat,
        "cash_reconciliation": cash,
        "credit_quality": credit,
    }


def _apply_notes_to_receivables(receivables: dict, notes_out: dict) -> dict:
    """Receivables fields come from note 21 when it was read. The ECL field stays None: the doubtful-debt
    provision is not an ECL allowance, and the ECL model is deferred for GoP-linked debts (note 2.1.2)."""
    t = notes_out.get("trade_debts_note_21")
    if not t or t.get("trade_debts", {}).get("status") != "parsed":
        return receivables
    y = t["trade_debts"]["by_year"]["2026"]
    ageing = t.get("ageing", {})
    over_90 = (
        ageing["by_year"]["2026"]["over_90_share_of_gross"] if ageing.get("status") == "parsed" else None
    )
    # the keys match the notes engine's receivables block, which the diagnostic reads
    return {
        **receivables,
        "gross_trade_debts": y["gross_trade_debts"],
        "ecl_coverage_ratio": None,
        "ecl_coverage_reason": (
            "doubtful-debt provision only; ECL model deferred for GoP-linked debts (note 2.1.2)"
        ),
        "overdue_over_90_ratio": over_90,
        "doubtful_debt_provision": y["doubtful_debt_provision"],
        "net_trade_debts": y["net_trade_debts"],
        # the notes engine reads note rows as ageing brackets; note 21 is the source once it has been parsed
        "unclassified_brackets": [],
    }


def _kam_list(value: str) -> list[tuple[int, str]]:
    """KAM table pages, each optionally a half of a spread: "5,6L,6R" -> [(5, ""), (6, "L"), (6, "R")]."""
    out: list[tuple[int, str]] = []
    for part in str(value).split(","):
        part = part.strip().upper()
        side = part[-1:] if part[-1:] in ("L", "R") else ""
        digits = part[: len(part) - len(side)]
        if not digits.isdigit() or int(digits) < 1:
            raise ValueError(f"bad KAM page: {value!r}")
        out.append((int(digits), side))
    return sorted(set(out))


def _audit_layout(path: Path, doc, ex_audit: dict, auditor_pages, kam_pages) -> dict:
    """The auditor section. With owner auditor pages, the opinion and emphasis are read only from those pages.
    KAMs come from the KAM table read by word coordinates (column-aware) on the owner's KAM pages, or on every
    page whose text carries the KAM table header. Falls back to the text-based reading, and says so."""
    audit = ex_audit
    if auditor_pages:
        layout_pages = pe_reader.read_layout_pages(path)
        audit_doc = pe.DocumentText(
            [
                pe.Page(
                    number=n,
                    lines=layout_pages[n - 1],
                    has_text=bool(layout_pages[n - 1]),
                    extraction_method="pdftotext_layout",
                )
                for n in auditor_pages
            ]
        )
        audit = ae.audit_summary(audit_doc)
    candidates = kam_pages or [
        (p.number, "")
        for p in doc.pages
        if any("how the matter was addressed" in ln.lower() for ln in p.lines)
    ]
    kams: list[dict] = []
    for n, side in candidates:
        words = pe_reader.page_words(path, n)
        if side:  # one half of a spread: keep only the words whose left edge lies in that half
            half = pe_reader.page_size(path, n)[0] / 2.0
            words = [w for w in words if (w["x0"] < half) == (side == "L")]
        found = pl.parse_kam_table(words, n)
        if found:
            for k in found["kams"]:
                k["half"] = side or "full"
            kams.extend(found["kams"])
    if kams:
        audit = {**audit, "kams": kams, "kam_source": "word_coordinates", "kam_pages_read": candidates}
    else:
        audit = {**audit, "kam_source": "text_structural", "kam_pages_read": candidates}
    return audit


def parse_statement_spec(spec: str) -> tuple[dict[str, list[int]] | None, dict[str, tuple[int, str]] | None]:
    """Parse the owner's statement map. "BS=43R,IS=44L,CF=45R,EQ=45L": a page, and for two-page spreads the
    half
    that holds the statement (L or R). A page without a side is the whole page. Returns (pages, regions); both
    None when the spec is empty (automatic detection). Unknown codes, bad pages or sides are refused."""
    if not spec.strip():
        return None, None
    pages: dict[str, list[int]] = {}
    regions: dict[str, list[tuple[int, str]]] = {}
    for part in spec.split(","):
        code, sep, ref = part.strip().partition("=")
        code = code.strip().upper()
        if not sep or code not in STATEMENT_CODES:
            raise ValueError(
                f"bad --statement-pages entry {part!r}: expected one of {STATEMENT_CODES}=<page>[L|R][+...]"
            )
        # one page, or several regions of a spread separated by "+" (e.g. BS=8L+8R)
        for piece in ref.split("+"):
            ref_part = piece.strip().upper()
            side = ref_part[-1:] if ref_part[-1:] in ("L", "R") else ""
            digits = ref_part[: len(ref_part) - len(side)]
            if not digits.isdigit() or int(digits) < 1:
                raise ValueError(f"bad page for {code}: {ref_part!r}")
            if side:
                regions.setdefault(code, []).append((int(digits), side))
            if int(digits) not in pages.get(code, []):
                pages.setdefault(code, []).append(int(digits))
    # a single region stays a (page, side) pair; several regions stay a list, in the order given
    shaped = {k: (v[0] if len(v) == 1 else v) for k, v in regions.items()}
    return pages, (shaped or None)


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
    framework: str = "corporate",
    statement_pages: dict[str, list[int]] | None = None,
    statement_regions: dict[str, tuple[int, str]] | None = None,
    auditor_pages: list[int] | None = None,
    kam_pages: list[int] | None = None,
    notes: dict | None = None,
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
        framework=framework,
        statement_pages=statement_pages,
        statement_regions=statement_regions,
        auditor_pages=auditor_pages,
        kam_pages=kam_pages,
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
            framework=framework,
            statement_pages=statement_pages,
            statement_regions=statement_regions,
        )
        prior = {**p_tagged, "period": prior_spec["period"]}
        prior_report = {"vault": p_stored["status"], "report_sha256": p_sha, "period": prior_spec["period"]}
    recon = sp.reconcile(tagged, period_end=period_end, prior=prior)
    metrics = sp.compute_metrics(tagged, period_end=period_end, prior=prior)
    notes_view = {"lines": ex["note_lines"], "notes": ex["note_index"]}
    receivables = ne.receivables_quality(notes_view, period_end)
    contingencies = ne.contingency_summary(notes_view, period_end)
    notes_out = _notes_block(path, notes, tagged, period_end)
    receivables = _apply_notes_to_receivables(receivables, notes_out)
    diagnostic = build_diagnostic(tagged, recon, ex["audit"], receivables, contingencies)
    diagnostic["reconciliation"]["cash_equivalents"] = notes_out.get("cash_reconciliation", {}).get(
        "status", "not_requested"
    )
    diagnostic["notes"] = notes_out
    diagnostic["framework"] = framework
    not_run = sorted(c["check"] for c in recon["checks"] if c["status"] == "INSUFFICIENT_DATA")
    diagnostic["checks_not_run"] = not_run
    diagnostic["statement_pages"] = {
        "source": "owner" if (statement_pages or auditor_pages or kam_pages) else "detected",
        "auditor_pages": auditor_pages,
        "kam_pages": [f"{n}{s}" for n, s in kam_pages] if kam_pages else None,
        "kam_source": ex["audit"].get("kam_source"),
        "pages": tagged.get("statement_pages", {}),
    }
    diagnostic["extraction"] = {
        "methods": tagged["extraction_methods"],
        "warnings": tagged["extraction_warnings"],
    }
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
            "comprehensive_income": status.get("comprehensive_income", "not_run"),
            "income_statement": status.get("income_statement", "not_run"),
            "oci_components": status.get("oci_components", "not_run"),
            "overall": recon["overall"],
        },
        "auditor_opinion": audit["opinion"].get("opinion"),
        "key_audit_matters": [
            {
                "heading": k["heading"],
                "page": k["page"],
                "excerpt": k["excerpt"][:160],
                "note_references": k.get("note_references", []),
                "text_quality": k.get("text_quality"),
            }
            for k in audit["kams"]
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


def _notes_text(notes: dict) -> list[str]:
    if not notes or notes.get("status") == "not_requested":
        return ["Notes: not requested (no note pages in the page map)"]
    out = []
    t = notes.get("trade_debts_note_21", {})
    td = t.get("trade_debts", {})
    if td.get("status") == "parsed":
        y = td["by_year"]["2026"]
        out.append(
            f"Trade debts (note 21, PKR '000): gross {y['gross_trade_debts']:,.0f}, doubtful-debt provision "
            f"{y['doubtful_debt_provision']:,.0f} (not ECL), net {y['net_trade_debts']:,.0f}"
        )
    a = t.get("ageing", {})
    if a.get("status") == "parsed":
        b = a["by_year"]["2026"]
        g = b["gross_by_bucket"]
        out.append(
            f"  ageing 2026: not past due {g['not_past_due']:,.0f}; 0-30 {g['past_due_0_30']:,.0f}; "
            f"31-60 {g['past_due_31_60']:,.0f}; 61-90 {g['past_due_61_90']:,.0f}; "
            f"over 90 {g['over_90']:,.0f}; "
            f"over 365 {'disclosed' if b['over_365_disclosed'] else 'not disclosed'}"
        )
    c = t.get("circular_debt", {})
    if c.get("overdue_total"):
        out.append(
            f"  circular debt overdue (PKR million): total {c['overdue_total']['2026']:,.0f}; SNGPL "
            f"{c['overdue_from_sngpl']['2026']:,.0f}; SSGC {c['overdue_from_ssgc']['2026']:,.0f}"
        )
    cp = t.get("counterparty_exposures", {})
    if cp.get("status") == "parsed":
        names = ", ".join(r["key"].upper() for r in cp["rows"])
        out.append(
            f"  counterparty exposures (kept separate from trade debts): {names}; total "
            f"{cp['printed_total_2026']:,.0f}"
        )
    cr = notes.get("cash_reconciliation", {})
    if cr.get("status") in ("EXPLAINED", "NOT_EXPLAINED"):
        out.append(
            f"Cash (note 41): BS {cr['balance_sheet_cash_and_bank']:,.0f} + term deposits "
            f"{cr['explained_by_note41_short_term']:,.0f} = CF closing {cr['cash_flow_closing']:,.0f}: "
            f"{cr['status']}"
        )
        out.append(f"  IAS 7 test: {cr['ias7_cash_equivalent_test']}")
    return out


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
        f"comprehensive income {rec['comprehensive_income']}, "
        f"income statement {rec['income_statement']}, "
        f"OCI components {rec['oci_components']}, "
        f"overall {rec['overall']}"
        + (f" (PARTIAL: not run: {', '.join(d['checks_not_run'])})" if d["checks_not_run"] else ""),
        f"Framework: {d['framework']}",
        f"Extraction: {d['extraction']['methods'] or 'n/a'}",
        f"Auditor opinion: {d['auditor_opinion']}",
    ]
    lines += [f"  warning: {w}" for w in d["extraction"]["warnings"]]
    lines += [f"  KAM p.{k['page']}: {k['heading']} - {k['excerpt']}" for k in d["key_audit_matters"]]
    lines.append(
        f"Receivables: gross {r['gross']}, ECL coverage {r['ecl_coverage']}, "
        f"overdue {r['overdue_percentage']}, over 90 days {r['overdue_over_90']}"
    )
    if r["unclassified_brackets"]:
        lines.append(f"  unclassified ageing rows (kept, not bucketed): {r['unclassified_brackets']}")
    lines += _notes_text(d.get("notes", {}))
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
    ap.add_argument(
        "--framework",
        default="corporate",
        choices=("corporate", "bank", "insurer"),
        help="account mapping framework (kept apart: corporate, bank SBP taxonomy, insurer)",
    )
    ap.add_argument(
        "--statement-pages",
        default="",
        help="owner-confirmed statement pages, e.g. BS=43R,IS=44L,CF=45R,EQ=45L (PDF page numbers; "
        "L/R = the half of a two-page spread). Without it, pages are detected automatically "
        "and the source is recorded as detected.",
    )
    ap.add_argument(
        "--page-map",
        type=Path,
        default=None,
        help='owner page map (JSON) for this document: BS, IS, OCI, CF, EQ (e.g. "45R"), AUDITOR (e.g. '
        '"41-42"), KAM (e.g. "42"). Overrides automatic page detection for this run. Use instead of '
        "--statement-pages.",
    )
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
        if args.page_map and args.statement_pages:
            raise IntakeRefused("use --page-map or --statement-pages, not both")
        if args.page_map:
            pm = parse_page_map(args.page_map)
            stmt_pages, stmt_regions = pm["statement_pages"], pm["statement_regions"]
            auditor_pages, kam_pages = pm["auditor_pages"], pm["kam_pages"]
            notes_spec = pm["notes"]
        else:
            stmt_pages, stmt_regions = parse_statement_spec(args.statement_pages)
            auditor_pages, kam_pages = None, None
            notes_spec = None
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
            framework=args.framework,
            statement_pages=stmt_pages,
            statement_regions=stmt_regions,
            auditor_pages=auditor_pages,
            kam_pages=kam_pages,
            notes=notes_spec,
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
