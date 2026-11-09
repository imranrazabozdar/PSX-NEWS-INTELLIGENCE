"""Streamlit pages for the M2-M9 research modules. Read-only: viewing never writes.

Each page first checks that its tables exist. Migrations 0011-0014 are not applied to production until the
owner approves (docs/OPERATIONS_RUNBOOK.md), so a missing table is shown as "awaiting migration", never as an
empty result. Missing inputs are shown with their state (insufficient_data / not_applicable /
needs_assumptions); nothing is filled in. Market behaviour is labelled as such and kept apart from
fundamentals. There are no buy/sell labels or price targets.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import streamlit as st

from database.connection import DatabaseError

AWAIT = ("Awaiting migration {m}: these tables are not in this database. Production migrations need the "
         "owner's separate approval (docs/OPERATIONS_RUNBOOK.md).")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _ready(db, tables: tuple[str, ...], migration: str) -> bool:
    try:
        have = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except DatabaseError as exc:
        st.error(f"Database unavailable: {str(exc)[:200]}. Nothing below is current.")
        return False
    if not set(tables) <= have:
        st.warning(AWAIT.format(m=migration))
        return False
    return True


def _run(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except DatabaseError as exc:
        st.error(f"Database error: {str(exc)[:200]}")
        return None


def _company_picker(db, key: str) -> str | None:
    rows = _run(db.execute, "SELECT c.company_id, c.legal_name, ci.value AS ticker FROM companies c "
                "LEFT JOIN company_identifiers ci ON ci.company_id = c.company_id AND ci.id_type = "
                "'psx_ticker' "
                "AND ci.valid_to IS NULL ORDER BY ci.value")
    if not rows:
        st.info("The company master is empty.")
        return None
    labels = {r["company_id"]: f"{r['ticker'] or '?'} — {r['legal_name']}" for r in rows}
    return st.selectbox("Company", list(labels), format_func=labels.get, key=key)


def _states(items: dict) -> list[dict]:
    return [{"measure": k, "state": v.get("state"), "value": v.get("value"), "formula": v.get("formula", ""),
             "missing": ", ".join(v.get("missing", []) or [])} for k, v in items.items()]


# ---------------------------------------------------------------- M2
def financials_view(db) -> None:
    if not _ready(db, ("financial_reports", "financial_line_items"), "0011"):
        return
    cid = _company_picker(db, "fin_company")
    if not cid:
        return
    reps = _run(db.execute, "SELECT report_id, doc_type, period_end, scope, currency, unit_scale, "
                            "audit_status, "
                "auditor_opinion, filed_at_utc, extraction_status, extraction_method FROM financial_reports "
                "WHERE company_id = ? ORDER BY period_end DESC, scope", (cid,))
    if not reps:
        st.info("No financial report has been imported for this company. Reports enter only by "
                "owner-attested "
                "import (engines/financials.py); PDF extraction awaits decision U3.")
        return
    st.dataframe(reps, use_container_width=True)
    rid = st.selectbox("Report", [r["report_id"] for r in reps], key="fin_report")
    rec = _run(_reconcile_readonly, db, rid)
    if rec:
        st.markdown(f"**Reconciliation:** `{rec['status']}` (computed for display; nothing is written)")
        st.dataframe(rec["checks"], use_container_width=True)
    lines = _run(db.execute, "SELECT statement, line_no, raw_label, canonical_code, column_period_end, "
                 "is_comparative, value, value_state, page, review_status FROM financial_line_items "
                 "WHERE report_id = ? ORDER BY statement, column_period_end DESC, line_no", (rid,))
    st.caption("Values are in the report's unit scale. `not_reported` means blank or dash, never zero. "
               "A blank canonical code is an unmapped line awaiting review.")
    st.dataframe(lines or [], use_container_width=True)


def _reconcile_readonly(db, report_id: int) -> dict:
    """The reconciliation checks without the status write (viewing never writes)."""
    from engines import financials as fin

    rep = db.execute("SELECT period_end FROM financial_reports WHERE report_id = ?", (report_id,))[0]
    conflicts: list = []
    v = fin._values(db, report_id, rep["period_end"], conflicts)
    checks = [{"check": "single_value_per_code", "result": "fail", **c} for c in conflicts]
    for name, total, (a, b), f in fin.IDENTITIES:
        if total not in v and a not in v:
            continue
        vals = [v.get(total), v.get(a), v.get(b)]
        if any(x is None for x in vals):
            checks.append({"check": name, "result": "not_checkable"})
            continue
        exp = f(vals[1], vals[2])
        checks.append({"check": name, "result": "pass" if abs(vals[0] - exp) <= fin._tol(vals[0], exp)
                       else "fail", "reported": vals[0], "expected": exp})
    status = ("needs_review" if any(c["result"] == "fail" for c in checks) else
              "reconciled" if any(c["result"] == "pass" for c in checks) else "extracted")
    return {"status": status, "checks": checks}


# ---------------------------------------------------------------- M3
def fundamentals_view(db) -> None:
    """Fundamentals as known on a chosen date. Only reports FILED by then are used. The page says how many
    fiscal years were filed, how many later years are hidden, and which reports had no filing date."""
    if not _ready(db, ("financial_reports",), "0011"):
        return
    cid = _company_picker(db, "fu_company")
    if not cid:
        return
    as_of = st.text_input("As of (YYYY-MM-DD): only reports filed by then are used", _today(), key="fu_asof")
    strict = st.toggle("Exclude reports with no recorded filing date", value=True, key="fu_strict")
    filed = _run(db.execute, "SELECT m.period_end, COUNT(*) AS n FROM financial_metrics m "
                 "LEFT JOIN financial_reports r USING(report_id) WHERE m.company_id = ? AND "
                 "m.period_type = 'FY' AND m.period_end <= ? AND "
                 "((r.filed_at_utc IS NULL AND ? = 0) OR (r.filed_at_utc IS NOT NULL AND "
                 "substr(r.filed_at_utc, 1, 10) <= ?)) GROUP BY m.period_end ORDER BY m.period_end DESC",
                 (cid, as_of, int(strict), as_of))
    if not filed:
        st.info("No fiscal-year figures are available on this date" + (
            " (reports with no recorded filing date are excluded)." if strict else "."))
        return
    later = _run(db.execute, "SELECT COUNT(DISTINCT m.period_end) AS n FROM financial_metrics m "
                 "LEFT JOIN financial_reports r USING(report_id) WHERE m.company_id = ? AND "
                 "m.period_type = 'FY' AND m.period_end > ? AND r.filed_at_utc IS NOT NULL", (cid, as_of))
    st.caption(f"{len(filed)} fiscal year(s) filed by {as_of}."
               + (f" {later[0]['n']} later-filed year(s) are hidden, so they cannot influence this view."
                  if later and later[0]["n"] else ""))
    pe = st.selectbox("Fiscal year end", [p["period_end"] for p in filed], key="fu_period")
    from engines import fundamentals as fu

    a = _run(fu.analyse, db, cid, period_end=pe, as_of=as_of, strict=strict)
    if not a or a.get("state") == "insufficient_data":
        st.info("Insufficient reported data for this period.")
        return
    if a.get("filing_dates_unknown"):
        st.warning("Reports with no recorded filing date were used (their period end is not a publication "
                   "date, so this may look ahead): " + ", ".join(str(x) for x in a["filing_dates_unknown"]))
    prior = a["prior_period_end"] or "none"
    st.caption(f"Framework: {a['framework']} · scope: {a['scope']} · prior year: {prior}. No bands are "
               "shown (thresholds are an owner decision, U9). `roe` uses closing equity; "
               "`roe_average_equity` uses opening and closing equity and needs the prior year.")
    st.markdown("**Ratios**")
    st.dataframe(_states(a["ratios"]), use_container_width=True)
    st.markdown("**Growth (year on year, same period type)**")
    st.dataframe(_states(a["growth"]), use_container_width=True)
    st.write({"free_cash_flow": a["fcf"]})


# ---------------------------------------------------------------- M5
def valuation_view(db) -> None:
    if not _ready(db, ("valuations", "financial_reports", "corporate_actions"), "0011-0012"):
        return
    cid = _company_picker(db, "va_company")
    if not cid:
        return
    as_of = st.text_input("As of (YYYY-MM-DD)", _today(), key="va_asof")
    from engines import valuation as va

    out = _run(va.value, db, cid, as_of=as_of, store=False)
    if not out:
        return
    i = out["inputs"]
    st.caption(f"Price {i['price']} on {i['price_date']} (SCS, unadjusted) · FY {i['fy_period_end']} "
               f"({i['scope']}) · share factor x{i['share_factor']:g}. {out['disclaimer']}")
    for n in i.get("notes") or []:
        st.warning(n)
    st.dataframe([{k: r[k] for k in ("method", "state", "conservative", "base", "optimistic", "note")}
                  | {"missing": ", ".join(r["missing"])} for r in out["results"]], use_container_width=True)
    st.info("DCF, DDM and justified P/B need owner assumptions (low, base, high); the DCF also needs an "
            "explicit FCFF or FCFE basis. Forward P/E needs consensus estimates, which have no approved "
            "source "
            "(U6).")


# ---------------------------------------------------------------- M6
def macro_view(db) -> None:
    if not _ready(db, ("macro_series", "macro_observations"), "0013"):
        return
    series = _run(db.execute, "SELECT s.series_code, s.name, s.unit, s.frequency, s.source_id, s.mechanisms, "
                  "s.access_state, COUNT(o.obs_id) AS observations, MAX(o.release_date) AS last_release "
                  "FROM macro_series s LEFT JOIN macro_observations o USING(series_code) GROUP BY "
                  "s.series_code "
                  "ORDER BY s.series_code")
    if not series:
        st.info("No series registered. The registry (config/macro_series.json) loads with "
                "engines.macro.load_registry; values enter only by manual import of official releases.")
        return
    st.caption("Automated EIA / World Bank collection is blocked (U2); SBP automation is blocked (HTTP 403). "
               "A revised figure is a new vintage, never an overwrite.")
    st.dataframe(series, use_container_width=True)
    code = st.selectbox("Series", [s["series_code"] for s in series], key="mac_series")
    obs = _run(db.execute, "SELECT reference_period, value, release_date, vintage, source_item_id FROM "
               "macro_observations WHERE series_code = ? ORDER BY reference_period DESC, vintage DESC LIMIT "
               "200",
               (code,))
    if not obs:
        st.info("No observations imported for this series.")
    else:
        st.dataframe(obs, use_container_width=True)


# ---------------------------------------------------------------- M4
def market_behaviour_view(db) -> None:
    if not _ready(db, ("corporate_actions",), "0011"):
        return
    cid = _company_picker(db, "mi_company")
    if not cid:
        return
    t = _run(db.execute, "SELECT value FROM company_identifiers WHERE company_id = ? AND id_type = "
                         "'psx_ticker' "
             "AND valid_to IS NULL", (cid,))
    if not t:
        return
    as_of = st.text_input("As of (YYYY-MM-DD)", _today(), key="mi_asof")
    from engines import market_intel as mi

    m = _run(mi.measures, db, t[0]["value"], as_of=as_of)
    if not m:
        return
    st.caption("Descriptive market behaviour from stored SCS daily bars. It is not evidence about "
               "fundamentals. Benchmark-relative returns need an approved benchmark (U5).")
    if m["series_state"] == "unadjusted":
        st.warning("Series not fully adjusted for corporate actions: " + "; ".join(m["adjustment_problems"]))
    rows = {k: m[k] for k in ("return_1d", "return_20s", "return_60s", "volatility_60s_annualised",
                              "max_drawdown", "relative_to_benchmark")}
    st.dataframe(_states(rows), use_container_width=True)
    st.write({"liquidity (20 sessions; traded value approximate)": m["liquidity"],
              "consecutive_sessions": m["consecutive_sessions"]})


# ---------------------------------------------------------------- M9
def integrated_report_view(db) -> None:
    if not _ready(db, ("financial_reports", "valuations", "macro_series", "report_snapshots"), "0011-0014"):
        return
    cid = _company_picker(db, "rep_company")
    if not cid:
        return
    as_of = st.text_input("As of (YYYY-MM-DD)", _today(), key="rep_asof")
    from engines import reports

    body = _run(reports.company_report, db, cid, as_of=as_of)
    if not body:
        return
    st.caption(body["disclaimer"])
    miss = body["confidence_and_missing_data"]["missing"]
    if miss:
        st.warning("Missing or limited data: " + "; ".join(miss))
    for s in reports.SECTIONS:
        with st.expander(s.replace("_", " ").capitalize(), expanded=s == "executive_summary"):
            st.json(json.loads(json.dumps(body[s], default=str)), expanded=False)
    snap = _run(db.execute, "SELECT content_sha256, generated_at_utc FROM report_snapshots WHERE kind = "
                            "'company' "
                "AND subject = ? AND as_of_date = ? ORDER BY snapshot_id DESC LIMIT 1", (cid, as_of))
    if snap:
        v = _run(reports.verify_snapshot, db, cid, as_of=as_of)
        st.caption(f"Stored snapshot {snap[0]['content_sha256'][:12]}… ({snap[0]['generated_at_utc']}): "
                   f"{v and v['state']}")
    st.download_button("Download report (Markdown)", reports.report_markdown(body),
                       file_name=f"{cid}-{as_of}.md", mime="text/markdown")
