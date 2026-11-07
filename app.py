"""PSX Fundamental & News Intelligence: Streamlit entry point (Phase 0 skeleton).

This page shows real project status only. It shows no market data, scores or
placeholder numbers, because nothing has been collected yet (spec section 12 UI standard).
"""

from __future__ import annotations

import streamlit as st

from config.settings import load_settings

PHASES = [
    ("Phase 0", "Specification and repository bootstrap", "IN PROGRESS"),
    ("Phase 1", "Data foundation (Turso, migrations, company master)", "NOT STARTED"),
    ("Phase 2", "First source collectors", "NOT STARTED"),
    ("Phase 3", "Event extraction and verification", "NOT STARTED"),
    ("Phase 4", "Company exposure graph", "NOT STARTED"),
    ("Phase 5", "Impact analysis and calculations", "NOT STARTED"),
    ("Phase 6", "Streamlit MVP", "NOT STARTED"),
    ("Phase 7", "Scheduling and operations", "NOT STARTED"),
]


def main() -> None:
    st.set_page_config(page_title="PSX News Intelligence", layout="wide")
    settings = load_settings()

    st.title("PSX Fundamental & News Intelligence")
    st.caption(
        "Independent research terminal. Not connected to any other project. "
        "No trading signals or buy/sell instructions."
    )

    st.info(
        "No data source is connected yet. Collection and analysis start in later phases, "
        "after each phase is reviewed and approved."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Environment", settings.env)
    col2.metric("Database", "Configured" if settings.database_configured else "Not connected")
    col3.metric("Kill switch", "ON" if settings.kill_switch else "off")

    st.subheader("Implementation status")
    st.table([{"Phase": p, "Scope": s, "Status": status} for p, s, status in PHASES])


main()
