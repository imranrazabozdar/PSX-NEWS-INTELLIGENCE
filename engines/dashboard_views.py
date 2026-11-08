"""Streamlit views for the integrated intelligence dashboard (Stage 2, final batch).

Thin presentation over engines.research, engines.review_revalidation, engines.validation and
engines.intel_pipeline. Reads are cached with their timestamp shown. Lists are paginated. A database
failure is shown as an error, never as an empty or successful state. The only writes are explicit human
review decisions, submitted from a form with a named reviewer and notes; viewing never writes.
"""

from __future__ import annotations

import streamlit as st

from database.canonical import now_utc
from database.connection import DatabaseError
from engines import intel_pipeline, research, validation
from engines import review_revalidation as rv

PAGE = 20


def _guard(fn, db, *args):
    try:
        return fn(db, *args)
    except DatabaseError as exc:
        st.error(f"Database unavailable: {str(exc)[:200]}. Nothing below is current.")
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _events(_db, macro: bool, offset: int) -> dict:
    return research.events_page(_db, macro_only=macro, limit=PAGE, offset=offset) | {"as_of": now_utc()}


@st.cache_data(ttl=300, show_spinner=False)
def _company(_db, company_id: str) -> dict | None:
    return research.company_report(_db, company_id)


@st.cache_data(ttl=300, show_spinner=False)
def _sector(_db, sector_id: str) -> dict | None:
    return research.sector_report(_db, sector_id)


def intelligence_view(db) -> None:
    macro = st.toggle("Market and macro events only", value=True)
    page = st.number_input("Page", min_value=1, value=1, step=1)
    data = _guard(lambda d: _events(d, macro, (page - 1) * PAGE), db)
    if data is None:
        return
    st.caption(
        f"{data['total']} event(s); cached as of {data['as_of']} (UTC). 'Not assessed' events have not "
        "been classified yet; they are shown, not hidden."
    )
    if not data["items"]:
        st.info("No events on this page." if data["total"] else "No events have been built yet.")
        return
    st.dataframe(data["items"], use_container_width=True)
    ids = [e["event_id"] for e in data["items"]]
    eid = st.selectbox("Event detail", ids)
    d = _guard(research.event_detail, db, eid)
    if not d:
        return
    imp = d["impact"]
    st.subheader(d["event"]["headline"])
    st.write(
        {
            "type": d["event"]["event_type"],
            "secondary": d["secondary_types"],
            "stage": d["display_stage"],
            "verification": d["event"]["verification_state"],
            "scope": imp["scope"],
            "independent publisher groups (not verification)": d["publisher_groups"],
        }
    )
    if d["conflicts"]:
        st.warning("Conflicting reports: " + "; ".join(d["conflicts"]))
    st.markdown("**Evidence (headline only)**")
    st.dataframe(d["evidence"], use_container_width=True)
    st.markdown("**Development history**")
    st.dataframe(d["revisions"], use_container_width=True)
    st.markdown("**Transmission mechanisms**")
    st.write(imp["mechanisms"] or imp["no_transmission_reason"])
    st.markdown("**Affected companies (exposure → T1–T9 assessment)**")
    st.dataframe(imp["exposure_candidates"], use_container_width=True)
    for cid, items in imp["assessments"].items():
        st.write(cid, items)
    if imp["unresolved_companies"]:
        st.warning(
            "Unresolved or ambiguous companies: " + ", ".join(e["name"] for e in imp["unresolved_companies"])
        )


def company_view(db) -> None:
    rows = _guard(lambda d: d.execute("SELECT company_id, legal_name FROM companies ORDER BY legal_name"), db)
    if not rows:
        return
    cid = st.selectbox(
        "Company",
        [r["company_id"] for r in rows],
        format_func=lambda c: next(r["legal_name"] for r in rows if r["company_id"] == c),
    )
    rep = _guard(lambda d: _company(d, cid), db)
    if not rep:
        return
    st.caption(
        f"Report data as of {rep['generated_at_utc']} (UTC). Assessments marked 'historical' predate a "
        "later event revision."
    )
    st.write(rep["executive_summary"])
    for title, key in (
        ("Latest developments", "latest_developments"),
        ("Sector developments", "sector_developments"),
    ):
        st.markdown(f"**{title}**")
        st.dataframe(rep[key], use_container_width=True)
    st.markdown("**Impact by transmission mechanism**")
    for mech, items in rep["impact_by_mechanism"].items():
        st.write(
            mech,
            [
                {
                    k: a[k]
                    for k in (
                        "headline",
                        "direction",
                        "magnitude_level",
                        "horizon",
                        "assessment_status",
                        "currency",
                    )
                }
                for a in items
            ],
        )
    st.markdown("**Limitations**")
    st.write(rep["limitations"])
    st.download_button(
        "Download report (Markdown)",
        research.report_markdown(rep),
        file_name=f"{cid}-report.md",
        mime="text/markdown",
    )


def sector_view(db) -> None:
    rows = _guard(lambda d: d.execute("SELECT sector_id, name FROM sectors ORDER BY name"), db)
    if not rows:
        return
    sid = st.selectbox(
        "Sector",
        [r["sector_id"] for r in rows],
        format_func=lambda s: next(r["name"] for r in rows if r["sector_id"] == s),
    )
    rep = _guard(lambda d: _sector(d, sid), db)
    if rep:
        st.caption(f"As of {rep['generated_at_utc']} (UTC). {rep['note']}")
        st.write({"differing impacts": rep["differing_impacts"], "conflicts": rep["conflicts"]})
        st.dataframe(rep["direct_exposure"] + rep["indirect_or_contextual"], use_container_width=True)


def review_view(db) -> None:
    queue = _guard(rv.review_queue, db)
    if queue is None:
        return
    st.caption(f"{len(queue)} item(s) await a human decision. Viewing records nothing.")
    st.dataframe(queue, use_container_width=True)
    with st.form("impact_review"):
        aid = st.number_input("Impact assessment id", min_value=1, step=1)
        decision = st.selectbox(
            "Decision", ["needs_more_evidence", "request_revalidation", "reject", "accept"]
        )
        reviewer = st.text_input("Your name (recorded with the decision)")
        notes = st.text_area("Notes (required)")
        if st.form_submit_button("Record decision"):
            try:
                rv.record_impact_review(db, int(aid), decision, reviewer=reviewer, notes=notes)
                st.success("Decision recorded.")
            except (ValueError, DatabaseError) as exc:
                st.error(str(exc)[:300])


def validation_view(_db) -> None:
    try:
        res = validation.evaluate()
    except validation.LabelError as exc:
        st.error(f"Label file invalid: {exc}")
        return
    st.caption(
        "Measured only against human labels (data/validation/labels.json). No score is shown below the "
        "minimum sample size."
    )
    st.write({k: res[k] for k in ("status", "n") if k in res}, res.get("note", ""))
    st.dataframe(res["metrics"], use_container_width=True)
    st.write({"market outcomes": res["market_outcomes"], "calibration": res["calibration"]})
    st.dataframe(res["false_positives"] + res["false_negatives"], use_container_width=True)


def readiness_view(db) -> None:
    r = _guard(intel_pipeline.readiness, db)
    if r:
        st.caption(f"Checked {r['checked_at_utc']} (UTC). Overall: {r['overall']}.")
        st.dataframe(r["checks"], use_container_width=True)
