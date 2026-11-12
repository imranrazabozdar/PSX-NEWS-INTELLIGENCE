"""Company intelligence view for the main app. LOCAL and PRIVATE: reads stored Investify data only.

Takes the app's database handle (the same one the other pages use). Every query is a SELECT, enforced in
engines/company_intelligence.py. Nothing here fetches, writes, or publishes. Investify's data is shown for
private research use: do not publish, share, or expose this view's content.
"""

from __future__ import annotations

import streamlit as st

from engines import company_intelligence as ci

PICKER_LABEL = "Company (symbol)"


def _not_collected(name: str) -> None:
    st.info(f"{name}: {ci.NOT_COLLECTED}")


def _fetched(record: dict | None) -> None:
    if record and record.get("fetched_at_utc"):
        st.caption(f"Source: {ci.SOURCE} · fetched {record['fetched_at_utc']} UTC")


def _profile(record: dict | None) -> None:
    st.subheader("Profile")
    if record is None:
        return _not_collected("Profile")
    f = record["fields"]
    st.markdown(f"**Sector (industry):** {f.get('sector') or ci.NOT_COLLECTED}")
    lead = f.get("leadership")
    if lead:
        st.markdown(f"**Chairperson:** {lead.get('chairperson')} · **CEO:** {lead.get('ceo')} · "
                    f"**Company secretary:** {lead.get('company_secretary')}")
    ms = f.get("market_structure")
    if ms:
        st.table([{"Market cap": ms["market_cap"]["text"], "Price": ms["price"]["text"],
                   "Total shares": ms["total_shares"]["text"],
                   "Free float shares": ms["free_float_shares"]["text"]}])
    if f.get("description"):
        st.write(f["description"])
    _fetched(record)


def _met(signal: dict) -> str:
    if signal["status"] != "evaluated":
        return ci.NOT_COLLECTED
    return "yes" if signal["met"] else "no"


def _metrics_flat(metrics_raw: list[dict]) -> list[dict]:
    return [{"label": m["label"], "value_text": m["value"]["text"], "value": m["value"].get("value"),
             "period_basis": m["period_basis"]} for m in metrics_raw]


def _fundamentals(record: dict | None, rules: list[dict]) -> None:
    st.subheader("Fundamentals (as grouped by Investify)")
    if record is None:
        _not_collected("Fundamentals")
        st.subheader("Screening signals")
        _not_collected("Screening signals (needs fundamentals)")
        return
    metrics_raw = record["fields"].get("metrics", [])
    for group, rows in ci.grouped_metrics(record["fields"]).items():
        expanded = group in ("EPS", "P/E", "Profitability")
        with st.expander(f"{group} ({len(rows)})", expanded=expanded):
            st.table([{"Metric": r["label"], "Value": r["value_text"], "Period basis": r["period_basis"],
                       "Investify sentiment": r["sentiment"] or "n/a"} for r in rows])
    _fetched(record)
    st.subheader("Screening signals")
    st.caption("Descriptive only: each line states a criterion and the company's observed value. "
               "No action is implied. Thresholds are in config/screening_thresholds.json.")
    signals = ci.screening_signals(_metrics_flat(metrics_raw), rules)
    st.table([{"Signal": s["label"], "Criterion": s["criterion"], "Observed": s["observed"] or "-",
               "Period basis": s["period_basis"] or "-", "Criterion met": _met(s)} for s in signals])


def _peers(record: dict | None) -> None:
    st.subheader("Peers")
    if record is None:
        return _not_collected("Competitors")
    f = record["fields"]
    st.markdown(f"**Peer source:** {f.get('peer_source')} · **peers:** {f.get('peer_count')}")
    if f.get("note"):
        st.caption(f["note"])
    st.table([{"Ticker": p["ticker"], "Name": p["name"], "Sector": p["sector"]} for p in f.get("peers", [])])
    _fetched(record)


def _announcements(record: dict | None) -> None:
    st.subheader("Recent announcements")
    if record is None:
        return _not_collected("Announcements")
    items = record["fields"].get("items", [])[:25]
    st.table([{"Date (UTC)": i["announced_at_utc"][:10], "Type": i["sub_type"], "Title (PSX)": i["title"],
               "Investify sentiment": i.get("sentiment") or "n/a"} for i in items])
    _fetched(record)


def company_intelligence_view(db, rules: list[dict] | None = None) -> None:
    """Render the company view on the app's database handle. Read-only."""
    st.warning(f"{ci.ATTRIBUTION}. Local view only: do not publish, share, or expose this page's content.")
    try:
        symbols = ci.company_symbols(db)
    except ValueError as exc:
        st.error(str(exc))
        return
    if not symbols:
        st.info("No Investify company data is stored yet.")
        return
    symbol = st.selectbox(PICKER_LABEL, symbols, key="ci_symbol")
    data = ci.load_company(db, symbol)
    st.header(symbol)
    _profile(data["profile"])
    _fundamentals(data["fundamentals"], rules if rules is not None else ci.load_rules())
    _peers(data["competitors"])
    _announcements(data["announcements"])
