"""Financial statements: import, account mapping, reconciliation and promotion (master plan M2).

Flow (MASTER_ARCHITECTURE.md workstream A):
1. A report enters only by owner-attested import (`import_report`): a JSON record of the document's metadata
   and its statement lines. Lines may come from manual entry or from `parse_statement_text`, which reads
   already-extracted statement text. PDF -> text extraction waits for owner decision U3 (no PDF library is
   installed); OCR is not used.
2. Lines map to canonical codes through the versioned `account_mappings` dictionary (exact normalised labels,
   per framework and statement). Unmapped lines stay with canonical_code NULL for review; nothing is guessed.
3. Reconciliation checks accounting identities. A failed check sets the report to `needs_review` and blocks
   promotion. A missing input makes a check `not_checkable`, never a pass.
4. Promotion writes the report's own-period mapped values to `financial_metrics` (basis `reported`, or
   `restated` for a restating report), scaled by the report's unit scale.

Rules: a blank or dash is `not_reported` (NULL), never zero. Share counts are absolute numbers (not scaled
by the report's unit scale). `extracted` (no identity checkable) may be promoted, and its metrics record
`;extracted` in calculation_method so unreconciled values stay identifiable.
Comparative columns are stored but never promoted from a later report; a comparative that differs from the
earlier report's value is flagged as a possible restatement.
Estimates are never substituted for reported values.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

from database import repositories as repo

SOURCE_ID = "company_reports_manual"
MAPPINGS_PATH = Path(__file__).resolve().parents[1] / "config" / "account_mappings.json"
SEED_APPROVER = "seed (pending owner review)"
# synthetic_test: hand-built fixtures only, never real research. Every other source is a real document or
# entry and must carry its source, scope and a page for every line.
SOURCES = ("synthetic_test", "pdf", "manual_pdf", "text_entry")
DOC_MONTHS = {"annual": 12, "half_yearly": 6, "nine_month": 9, "quarterly": 3}
PER_SHARE = {"eps_basic"}
PERCENT = {"car_pct"}
COUNTS = {"shares_outstanding"}
BANK_SECTORS = {"COMMERCIAL BANKS"}
INSURER_SECTORS = {"INSURANCE"}
# A number is an optional sign or bracket pair, digits with EITHER western (1,234,567) or South Asian lakh
# (1,23,45,678) grouping, or no grouping, and an optional decimal part. Irregular grouping such as 12,34 or
# 1,2,3 is refused: silently reading it would change the value by a factor of 100 or more.
_NUM = re.compile(
    r"^(?:\((?P<b>[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]{1,3}(?:,[0-9]{2})*,[0-9]{3}"
    r"(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\)|(?P<p>-?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|"
    r"-?[0-9]{1,3}(?:,[0-9]{2})*,[0-9]{3}(?:\.[0-9]+)?|-?[0-9]+(?:\.[0-9]+)?))$")
_BLANK = {"-", "–", "—", "nil", "n/a"}


class ImportError_(ValueError):  # noqa: N801 - avoid shadowing the builtin
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise_label(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", (label or "").casefold().replace("-", " "))
    return " ".join(s.split())


def framework_for(db, company_id: str) -> str:
    rows = db.execute(
        "SELECT s.name FROM company_classifications cc JOIN sectors s USING(sector_id) "
        "WHERE cc.company_id = ? AND cc.valid_to IS NULL", (company_id,))
    names = {r["name"].upper() for r in rows}
    if names & BANK_SECTORS:
        return "bank"
    if names & INSURER_SECTORS:
        return "insurer"
    return "corporate"


# ---------------------------------------------------------------- mappings
def load_mappings(db, path: Path | str = MAPPINGS_PATH) -> int:
    """Load the seed dictionary as version 1 where absent. Never changes an existing mapping."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    now, n = _now(), 0
    for fw, stmts in raw["mappings"].items():
        for st, codes in stmts.items():
            for code, labels in codes.items():
                for lab in {normalise_label(x) for x in labels}:
                    if not db.execute(
                        "SELECT 1 FROM account_mappings WHERE framework = ? AND statement = ? "
                        "AND raw_label_normalised = ?", (fw, st, lab)):
                        db.execute(
                            "INSERT INTO account_mappings(framework, raw_label_normalised, statement, "
                            "canonical_code, version, approved_by, approved_at_utc) VALUES (?,?,?,?,1,?,?)",
                            (fw, lab, st, code, SEED_APPROVER, now))
                        n += 1
    return n


def add_mapping(db, *, framework: str, statement: str, label: str, canonical_code: str,
                approved_by: str) -> int:
    """Add a new mapping version (an owner-approved correction or extension)."""
    lab = normalise_label(label)
    v = db.execute("SELECT COALESCE(MAX(version), 0) AS v FROM account_mappings WHERE framework = ? AND "
                   "statement = ? AND raw_label_normalised = ?", (framework, statement, lab))[0]["v"] + 1
    db.execute("INSERT INTO account_mappings(framework, raw_label_normalised, statement, canonical_code, "
               "version, approved_by, approved_at_utc) VALUES (?,?,?,?,?,?,?)",
               (framework, lab, statement, canonical_code, v, approved_by, _now()))
    return v


COMPANY_MAPPINGS_DIR = Path(__file__).resolve().parents[1] / "config" / "company_mappings"
CANONICAL_CODES_PATH = Path(__file__).resolve().parents[1] / "config" / "canonical_codes.json"
CONTEXT_BY_DOC = {"annual": "annual", "half_yearly": "half_yearly", "quarterly": "quarterly",
                  "nine_month": "nine_month"}


def known_canonical_codes(db=None) -> set[str]:
    """Every code that may be stored: the standard seed codes plus the owner-approved definitions."""
    seed = json.loads(MAPPINGS_PATH.read_text(encoding="utf-8"))["mappings"]
    codes = {c for stmts in seed.values() for codes_ in stmts.values() for c in codes_}
    codes |= set(json.loads(CANONICAL_CODES_PATH.read_text(encoding="utf-8"))["codes"])
    return codes


def company_overlay(ticker: str, doc_type: str) -> tuple[dict[tuple[str, str], str], dict | None]:
    """Owner-approved, company-specific mappings for this report context. Never applied to another company."""
    path = COMPANY_MAPPINGS_DIR / f"{ticker.lower()}.json"
    if not path.exists():
        return {}, None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("company_ticker") != ticker:
        raise ImportError_("company mapping file does not match the ticker it was loaded for")
    known = known_canonical_codes()
    ctx = CONTEXT_BY_DOC.get(doc_type)
    out: dict[tuple[str, str], str] = {}
    for m in raw["mappings"]:
        if m["canonical_code"] not in known:
            raise ImportError_(f"unknown canonical code in company mapping: {m['canonical_code']}")
        if m["context"] not in ("any", ctx):
            continue  # a quarterly label is not applied to annual statements, or the reverse
        out[(m["statement"], normalise_label(m["raw_label"]))] = m["canonical_code"]
    return out, {"file": path.name, "version": raw["version"], "approved_by": raw["approved_by"],
                 "approved_on": raw["approved_on"], "applied_count": len(out)}


def _mapping(db, framework: str) -> dict[tuple[str, str], str]:
    rows = db.execute(
        "SELECT m.statement, m.raw_label_normalised, m.canonical_code FROM account_mappings m "
        "WHERE m.framework = ? AND m.version = (SELECT MAX(version) FROM account_mappings x WHERE "
        "x.framework = m.framework AND x.statement = m.statement "
        "AND x.raw_label_normalised = m.raw_label_normalised)", (framework,))
    return {(r["statement"], r["raw_label_normalised"]): r["canonical_code"] for r in rows}


# ---------------------------------------------------------------- text parsing (no PDF dependency)
def parse_number(tok: str) -> float | None:
    """'1,234' -> 1234; '(1,234)' -> -1234; '-' or blank -> None (not reported, never zero)."""
    t = tok.strip()
    if not t or t.casefold() in _BLANK:
        return None
    m = _NUM.match(t)
    if not m:
        raise ValueError(f"not a number: {tok!r}")  # includes unpaired brackets and irregular grouping
    if m.group("b") is not None:  # (1,234) reads as negative; a bare sign inside brackets is refused above
        return -float(m.group("b").replace(",", ""))
    return float(m.group("p").replace(",", ""))


def parse_statement_text(text: str, *, statement: str, columns: list[str], page: int | None = None) -> dict:
    """Parse lines of already-extracted statement text into line records.

    Each line is `label  [note]  value_1 ... value_n` for the given column period ends. A leading small
    integer before the expected value count is treated as a note reference. Lines whose trailing tokens
    are not exactly the expected values are returned in `unparsed` for review, never guessed.
    """
    lines, unparsed = [], []
    n = len(columns)
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        toks = s.split()
        vals: list[str] = []
        while toks and (_NUM.match(toks[-1]) or toks[-1].casefold() in _BLANK):
            vals.insert(0, toks.pop())
        if len(vals) == n + 1 and re.fullmatch(r"[0-9]{1,2}(\.[0-9]{1,2})?", vals[0]):
            vals = vals[1:]  # note reference
        label = " ".join(toks)
        if any(re.search(r"\d", t) for t in toks):  # figure inside a label: side-by-side, never guessed
            unparsed.append({"line": s, "reason": "numbers inside the label: possible side-by-side layout"})
            continue
        if re.search(r"\b[A-Z]{3,} [A-Z]{3,}\b.*\b[a-z]", label):  # section heading from the other column
            unparsed.append({"line": s,
                             "reason": "section heading inside the label: possible side-by-side layout"})
            continue
        if not label or len(vals) != n:
            if vals or label:
                unparsed.append({"line": s, "reason": f"expected {n} values, found {len(vals)}"})
            continue
        for col, tok in zip(columns, vals, strict=True):
            v = parse_number(tok)
            lines.append({"statement": statement, "raw_label": label, "column_period_end": col, "value": v,
                          "page": page})
    return {"lines": lines, "unparsed": unparsed}


# ---------------------------------------------------------------- import
def _validate(rec: dict) -> None:
    need = ("company_ticker", "doc_type", "period_end", "scope", "currency", "unit_scale", "audit_status",
            "document_sha256", "lines")
    miss = [k for k in need if rec.get(k) in (None, "", [])]
    if miss:
        raise ImportError_(f"missing fields: {miss}")
    if rec["doc_type"] not in DOC_MONTHS:
        raise ImportError_(f"doc_type must be one of {sorted(DOC_MONTHS)}")
    date.fromisoformat(rec["period_end"])
    if not re.fullmatch(r"[0-9a-f]{64}", rec["document_sha256"]):
        raise ImportError_("document_sha256 must be the SHA-256 of the original file")
    source = rec.get("source")
    if source not in SOURCES:  # no implicit default: omitting `source` must not bypass the document rules
        raise ImportError_(f"source must be one of {sorted(SOURCES)}")
    pdf_sourced = source != "synthetic_test"  # real imports: page, source and scope are required
    if pdf_sourced:  # real documents: every value must trace to a page of the original file
        if not rec.get("original_url") and not rec.get("source_note"):
            raise ImportError_("a document import needs its source: original_url or source_note")
        if rec.get("scope") not in ("consolidated", "unconsolidated"):
            raise ImportError_("scope must be stated for a document import")
    for ln in rec["lines"]:
        if ln.get("statement") not in ("IS", "BS", "CF", "EQ", "note") or not ln.get("raw_label"):
            raise ImportError_(f"bad line: {ln}")
        if pdf_sourced and not isinstance(ln.get("page"), int):
            raise ImportError_(f"document line without a page reference: {ln.get('raw_label')!r}")
        date.fromisoformat(ln.get("column_period_end") or "")
        if ln.get("canonical_code") and ln["canonical_code"] not in known_canonical_codes():
            raise ImportError_(f"unknown canonical code: {ln['canonical_code']}")  # refused before any write
        if ln.get("value") is not None and not isinstance(ln["value"], (int, float)):
            raise ImportError_(f"value must be a number or null: {ln}")


def import_report(db, rec: dict, *, importer: str, rights_attestation: str) -> dict:
    """Store one report and its lines atomically, then map and reconcile it. Idempotent on the document."""
    if not importer.strip() or not rights_attestation.strip():
        raise ImportError_("importer and rights_attestation are required")
    _validate(rec)
    comp = db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                      "AND valid_to IS NULL", (rec["company_ticker"],))
    if not comp:
        raise ImportError_(f"ticker {rec['company_ticker']!r} is not in the company master (U4: not added)")
    company_id = comp[0]["company_id"]
    framework = framework_for(db, company_id)
    overlay, overlay_info = company_overlay(rec["company_ticker"], rec["doc_type"])
    item = repo.record_source_item(
        db, source_id=SOURCE_ID, collected_at_utc=rec.get("receipt_at_utc") or _now(),
        url=rec.get("original_url"),
        external_id=f"doc:{rec['document_sha256']}:{rec['scope']}", content_hash=rec["document_sha256"],
        title=rec.get("title") or f"{rec['company_ticker']} {rec['doc_type']} {rec['period_end']}",
        published_at_utc=rec.get("filed_at_utc"),
        provenance={"retrieval_method": "manual", "document_type": rec["doc_type"],
                    "source_metadata_json": json.dumps({
                        "importer": importer, "rights_attestation": rights_attestation,
                        "extraction_method": rec.get("extraction_method", "manual"),
                        "company_mapping": overlay_info,
                        **(rec.get("provenance_extra") or {})})})
    sid = item.source_item_id
    existing = db.execute("SELECT report_id FROM financial_reports WHERE company_id = ? AND doc_type = ? AND "
                          "period_end = ? AND scope = ? AND source_item_id = ?",
                          (company_id, rec["doc_type"], rec["period_end"], rec["scope"], sid))
    if existing:
        rr = reconcile(db, existing[0]["report_id"])  # recompute: a crash may have left it unreconciled
        return {"report_id": existing[0]["report_id"], "status": "duplicate", "reconciliation": rr["status"]}
    restates = None
    if rec.get("restates_period_end"):
        r = db.execute("SELECT report_id FROM financial_reports WHERE company_id = ? AND period_end = ? AND "
                       "scope = ? ORDER BY report_id LIMIT 1", (company_id, rec["restates_period_end"],
                                                                rec["scope"]))
        restates = r[0]["report_id"] if r else None
    method = rec.get("extraction_method", "manual")
    mapping = _mapping(db, framework)
    mapping = {**mapping, **overlay}  # owner-approved company mapping takes precedence for its labels
    stmts = [(
        "INSERT INTO financial_reports(company_id, source_item_id, doc_type, period_end, period_months, "
        "scope, currency, unit_scale, audit_status, auditor_opinion, filed_at_utc, restates_report_id, "
        "framework, extraction_method, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (company_id, sid, rec["doc_type"], rec["period_end"], DOC_MONTHS[rec["doc_type"]], rec["scope"],
         rec["currency"], int(rec["unit_scale"]), rec["audit_status"], rec.get("auditor_opinion"),
         rec.get("filed_at_utc"), restates, framework, method, _now()),
    )]
    rid_sql = ("(SELECT report_id FROM financial_reports WHERE company_id = ? AND doc_type = ? AND "
               "period_end = ? AND scope = ? AND source_item_id = ?)")
    rkey = (company_id, rec["doc_type"], rec["period_end"], rec["scope"], sid)
    unmapped = []
    line_no: dict[tuple[str, str], int] = {}
    for ln in rec["lines"]:
        k = (ln["statement"], ln["column_period_end"])
        line_no[k] = line_no.get(k, 0) + 1
        # a structurally recognised total carries its code from its rule; an explicit label is mapped by name
        if ln.get("canonical_code") and ln["canonical_code"] not in known_canonical_codes():
            raise ImportError_(f"unknown canonical code: {ln['canonical_code']}")
        code = ln.get("canonical_code") or mapping.get((ln["statement"], normalise_label(ln["raw_label"])))
        if code is None:
            unmapped.append(ln["raw_label"])
        v = ln.get("value")
        state = "reported" if v is not None else ln.get("value_state", "not_reported")
        stmts.append((
            "INSERT INTO financial_line_items(report_id, statement, line_no, raw_label, canonical_code, "
            "column_period_end, is_comparative, value, value_state, page, extraction_method, confidence) "
            "VALUES (" + rid_sql + ",?,?,?,?,?,?,?,?,?,?,?)",
            (*rkey, ln["statement"], line_no[k], ln["raw_label"], code, ln["column_period_end"],
             int(ln["column_period_end"] != rec["period_end"]), v, state, ln.get("page"), method,
             ln.get("confidence")),
        ))
    stmts.append((rid_sql[1:-1], rkey))
    report_id = db.batch(stmts, transactional=True)[-1][0]["report_id"]
    rec_result = reconcile(db, report_id)
    restatements = comparative_changes(db, report_id)
    return {"report_id": report_id, "status": rec_result["status"], "framework": framework,
            "checks": rec_result["checks"], "unmapped": sorted(set(unmapped)),
            "comparative_changes": restatements}


# ---------------------------------------------------------------- reconciliation
def _values(db, report_id: int, period_end: str, conflicts: list | None = None) -> dict[str, float | None]:
    """Canonical values for one column. A code mapped from two lines with different values is a conflict:
    it is reported and left out (never resolved by picking one)."""
    rows = db.execute("SELECT canonical_code, value, raw_label FROM financial_line_items WHERE report_id = ? "
                      "AND column_period_end = ? AND canonical_code IS NOT NULL ORDER BY statement, line_no",
                      (report_id, period_end))
    seen: dict[str, list] = {}
    for r in rows:
        seen.setdefault(r["canonical_code"], []).append(r)
    out: dict[str, float | None] = {}
    for code, rs in seen.items():
        vals = {x["value"] for x in rs}
        if len(vals) > 1:
            if conflicts is not None:
                conflicts.append({"canonical_code": code, "lines": [x["raw_label"] for x in rs],
                                  "values": sorted(vals, key=lambda v: (v is None, v))})
            continue
        out[code] = rs[0]["value"]
    return out


def _tol(*vals: float) -> float:
    return max(2.0, 0.001 * max(abs(v) for v in vals))


IDENTITIES = (
    ("balance_sheet", "total_assets", ("total_liabilities", "total_equity"), lambda a, b: a + b),
    ("gross_profit", "gross_profit", ("revenue", "cost_of_sales"), lambda a, b: a - abs(b)),
    ("profit_after_tax", "profit_after_tax", ("profit_before_tax", "taxation"), lambda a, b: a - abs(b)),
    ("net_interest_income", "net_interest_income", ("interest_earned", "interest_expensed"),
     lambda a, b: a - abs(b)),
)


def _cash_movement_check(v: dict) -> dict:
    """Operating + investing + financing = net change in cash (signed; outflows negative)."""
    need = ("cfo", "cfi", "cff", "net_change_in_cash")
    missing = [k for k in need if v.get(k) is None]
    if missing:
        return {"check": "cash_movement", "result": "not_checkable", "missing": missing}
    total = v["cfo"] + v["cfi"] + v["cff"]
    ok = abs(total - v["net_change_in_cash"]) <= _tol(v["net_change_in_cash"], total)
    return {"check": "cash_movement", "result": "pass" if ok else "fail", "reported": v["net_change_in_cash"],
            "expected": total}


def reconcile(db, report_id: int) -> dict:
    rep = db.execute("SELECT period_end FROM financial_reports WHERE report_id = ?", (report_id,))[0]
    conflicts: list = []
    v = _values(db, report_id, rep["period_end"], conflicts)
    checks = [{"check": "single_value_per_code", "result": "fail", **c} for c in conflicts]
    checks.append(_cash_movement_check(v))
    for name, total, (a, b), f in IDENTITIES:
        if total not in v and a not in v:
            continue  # identity not relevant to this report's lines
        vals = [v.get(total), v.get(a), v.get(b)]
        if any(x is None for x in vals):
            missing = [k for k, x in zip((total, a, b), vals, strict=True) if x is None]
            checks.append({"check": name, "result": "not_checkable", "missing": missing})
            continue
        expected = f(vals[1], vals[2])
        ok = abs(vals[0] - expected) <= _tol(vals[0], expected)
        checks.append({"check": name, "result": "pass" if ok else "fail", "reported": vals[0],
                       "expected": expected})
    if any(c["result"] == "fail" for c in checks):
        status = "needs_review"
    elif any(c["result"] == "pass" for c in checks):
        status = "reconciled"
    else:
        status = "extracted"
    db.execute("UPDATE financial_reports SET extraction_status = ? WHERE report_id = ?", (status, report_id))
    return {"status": status, "checks": checks}


def comparative_changes(db, report_id: int) -> list[dict]:
    """Comparative figures that differ from the value an earlier report stated for that period."""
    rep = db.execute("SELECT company_id, scope, period_months FROM financial_reports WHERE report_id = ?",
                     (report_id,))[0]
    out = []
    for r in db.execute(
        "SELECT l.canonical_code, l.column_period_end, l.value, e.value AS earlier, "
        "e.report_id AS earlier_report FROM financial_line_items l "
        "JOIN financial_reports er ON er.company_id = ? AND er.scope = ? "
        "AND er.period_end = l.column_period_end AND er.report_id <> l.report_id "
        "JOIN financial_line_items e ON e.report_id = er.report_id AND e.canonical_code = l.canonical_code "
        "AND e.column_period_end = l.column_period_end "
        "WHERE l.report_id = ? AND l.is_comparative = 1 AND l.canonical_code IS NOT NULL "
        "AND (l.statement = 'BS' OR er.period_months = ?)",  # flows compare only like-for-like periods
        (rep["company_id"], rep["scope"], report_id, rep["period_months"]),
    ):
        if r["value"] is not None and r["earlier"] is not None and abs(r["value"] - r["earlier"]) > _tol(
                r["value"], r["earlier"]):
            out.append(dict(r))
    return out


# ---------------------------------------------------------------- promotion
def _period_type(db, company_id: str, period_end: str, months: int) -> str:
    if months == 12:
        return "FY"
    if months == 9:
        return "9M"
    fye = db.execute("SELECT fiscal_year_end_month AS m FROM companies WHERE company_id = ?",
                     (company_id,))[0]["m"]
    if fye is None:
        raise ImportError_("fiscal year end unknown: cannot label an interim period")
    k = (date.fromisoformat(period_end).month - fye) % 12  # months after fiscal year end
    if months == 6:
        return {6: "H1", 0: "H2"}.get(k) or _bad(k)
    return {3: "Q1", 6: "Q2", 9: "Q3", 0: "Q4"}.get(k) or _bad(k)


def _bad(k: int) -> str:
    raise ImportError_(f"period end is {k} months after fiscal year end: not a standard interim period")


def promote(db, report_id: int) -> dict:
    """Write own-period mapped values to financial_metrics. Refused for reports needing review."""
    rec_status = reconcile(db, report_id)["status"]  # never trust a stored status
    rep = db.execute("SELECT * FROM financial_reports WHERE report_id = ?", (report_id,))[0]
    if rec_status in ("needs_review", "failed"):
        return {"promoted": 0, "refused": f"report is {rep['extraction_status']}"}
    ptype = _period_type(db, rep["company_id"], rep["period_end"], rep["period_months"])
    basis = "restated" if rep["restates_report_id"] else "reported"
    stmts = []
    for code, v in _values(db, report_id, rep["period_end"]).items():
        if v is None:
            continue  # not reported: no metric row (never zero)
        if code in PER_SHARE:
            val, unit = v, f"{rep['currency']}/share"
        elif code in PERCENT:
            val, unit = v, "%"
        elif code in COUNTS:
            val, unit = v, "shares"  # share counts are entered as absolute numbers, never scaled
        else:
            val, unit = v * rep["unit_scale"], rep["currency"]
        stmts.append((
            "INSERT INTO financial_metrics(company_id, period_end, period_type, metric, value, unit, "
            "currency, basis, calculation_method, source_item_id, recorded_at_utc, report_id, scope) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rep["company_id"], rep["period_end"], ptype, code, val, unit, rep["currency"], basis,
             f"line_item:{rep['extraction_method']};{rec_status}", rep["source_item_id"], _now(), report_id,
             rep["scope"]),
        ))
    done = {r["metric"] for r in db.execute("SELECT metric FROM financial_metrics WHERE report_id = ?",
                                             (report_id,))}
    stmts = [st for st in stmts if st[1][3] not in done]  # re-promotion is a no-op, never a silent drop
    if stmts:
        db.batch(stmts, transactional=True)
    return {"promoted": len(stmts), "already_promoted": len(done), "period_type": ptype, "basis": basis,
            "reconciliation": rec_status}


BALANCE_CODES = ("total_assets", "total_liabilities", "total_equity", "current_assets", "current_liabilities",
                 "cash_and_equivalents", "inventory", "trade_receivables", "share_capital")


def promote_balance_comparative(db, report_id: int, column_period_end: str) -> dict:
    """Promote verified balance-sheet COMPARATIVES as point-in-time balances (owner-approved rule).

    Only balance-sheet lines with a balance code, only from the named comparative column, only at a fiscal
    year-end date (the metrics table accepts period type FY there), and only for the report's own company and
    scope. Nothing is overwritten: an existing different value at the same date and metric refuses the whole
    promotion. Income-statement and cash-flow comparatives are never promoted by this rule."""
    rep = db.execute("SELECT * FROM financial_reports WHERE report_id = ?", (report_id,))
    if not rep:
        raise ImportError_("unknown report")
    rep = rep[0]
    if column_period_end == rep["period_end"]:
        return {"promoted": 0, "refused": "current period balances are promoted by promote(), not this rule"}
    if rep["extraction_status"] not in ("reconciled", "extracted"):
        return {"promoted": 0, "refused": f"report is {rep['extraction_status']}"}
    fye = db.execute("SELECT fiscal_year_end_month AS m FROM companies WHERE company_id = ?",
                     (rep["company_id"],))[0]["m"]
    d = date.fromisoformat(column_period_end)
    if fye is None or d.month != fye or d.day != _month_end_day(d.year, fye):
        return {"promoted": 0, "refused": "comparative date is not a fiscal year-end: point balances refused"}
    rows = db.execute(
        "SELECT canonical_code, value, raw_label, page FROM financial_line_items WHERE report_id = ? "
        "AND statement = 'BS' AND column_period_end = ? AND is_comparative = 1 AND value IS NOT NULL "
        "AND canonical_code IS NOT NULL", (report_id, column_period_end))
    rows = [r for r in rows if r["canonical_code"] in BALANCE_CODES]
    if not rows:
        return {"promoted": 0, "refused": "no balance-sheet comparative lines with balance codes"}
    basis = "restated" if rep["restates_report_id"] else "reported"
    conflicts, stmts = [], []
    for r in rows:
        v = r["value"] * rep["unit_scale"]
        same = db.execute(
            "SELECT value, source_item_id FROM financial_metrics WHERE company_id = ? AND period_end = ? "
            "AND period_type = 'FY' AND metric = ? AND scope = ?",
            (rep["company_id"], column_period_end, r["canonical_code"], rep["scope"]))
        if same and any(abs(x["value"] - v) > 0.5 for x in same):
            conflicts.append({"metric": r["canonical_code"], "stored": same[0]["value"], "new": v,
                              "reason": "a different value already exists for this date: not overwritten"})
            continue
        if same:
            continue  # already promoted with the same value
        method = (f"balance_point_comparative; source_label={r['raw_label']}; page={r['page']}; "
                  f"restates={'yes' if rep['restates_report_id'] else 'no'}")
        stmts.append((
            "INSERT INTO financial_metrics(company_id, period_end, period_type, metric, value, unit, "
            "currency, basis, calculation_method, source_item_id, recorded_at_utc, report_id, scope) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rep["company_id"], column_period_end, "FY", r["canonical_code"], v, rep["currency"],
             rep["currency"], basis, method, rep["source_item_id"], _now(), report_id, rep["scope"])))
    if conflicts:
        return {"promoted": 0, "refused": "conflicting existing values", "conflicts": conflicts}
    if stmts:
        db.batch(stmts, transactional=True)
    return {"promoted": len(stmts), "period_end": column_period_end, "basis": basis, "scope": rep["scope"],
            "period_type": "FY (balance point, fiscal year end)"}


def _month_end_day(year: int, month: int) -> int:
    from calendar import monthrange

    return monthrange(year, month)[1]


def cash_definition_check(cash_and_bank: float | None, term_deposits: float | None,
                          cash_closing: float | None) -> dict:
    """Note 23 definition: cash and cash equivalents = cash and bank balances + short-term highly liquid
    investments (term deposits). Checks the disclosed components against the cash-flow closing balance.
    The two canonical measures are NOT merged: this only tests whether the disclosed definition explains
    the difference."""
    if cash_and_bank is None or term_deposits is None or cash_closing is None:
        return {"check": "cash_definition", "result": "not_checkable"}
    expected = cash_and_bank + term_deposits
    ok = abs(expected - cash_closing) <= 0.5
    return {"check": "cash_definition", "result": "pass" if ok else "fail", "expected": expected,
            "reported": cash_closing}


def document_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
