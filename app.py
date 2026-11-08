"""PSX Fundamental & News Intelligence: Streamlit entry point (Phase 0 skeleton).

This page shows only real, stored data (spec section 12 UI standard). Market bars and news headlines are
read from the configured database. When nothing has been collected, the page says so instead of showing
placeholder numbers. No trading signals or buy/sell instructions.
"""

from __future__ import annotations

import streamlit as st

from config.settings import load_settings

PHASES = [
    ("Phase 0", "Specification and repository bootstrap", "TESTED"),
    ("Phase 1", "Data foundation (Turso, migrations, company master)", "TESTED"),
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

    if not settings.database_configured:
        st.info("No database is configured (set PSXNI_TURSO_DATABASE_URL). Nothing collected can be shown.")
    else:
        _data_views()

    col1, col2, col3 = st.columns(3)
    col1.metric("Environment", settings.env)
    col2.metric("Database", "Configured" if settings.database_configured else "Not connected")
    col3.metric("Kill switch", "ON" if settings.kill_switch else "off")

    st.subheader("Implementation status")
    st.table([{"Phase": p, "Scope": s, "Status": status} for p, s, status in PHASES])


@st.cache_resource
def _db():
    from database.connection import connect

    return connect()


def _data_views() -> None:
    db = _db()
    market, news, health = st.tabs(["PSX market data", "News", "Source health"])
    with market:
        _market_view(db)
    with news:
        _news_view(db)
    with health:
        _health_view(db)


def _market_view(db) -> None:
    from collectors.market_ohlcv import TIMEFRAMES

    cov = db.execute("SELECT * FROM market_coverage ORDER BY symbol, timeframe")
    st.caption(
        "Source: SCS Trade chart datafeed (owner-authorised; honest requests). Bars are stored "
        "as received. Times are UTC; the session date is Pakistan time (UTC+5)."
    )
    available = {r["timeframe"] for r in cov}
    st.table(
        [
            {"Timeframe": tf, "Status": "available" if tf in available else "unavailable: no bars collected"}
            for tf in TIMEFRAMES
        ]
    )
    if not cov:
        st.warning("No market bars have been collected yet.")
        return
    st.dataframe(
        [
            {
                "Symbol": r["symbol"],
                "Timeframe": r["timeframe"],
                "Bars": r["bars"],
                "First bar (UTC)": r["first_bar_utc"],
                "Latest bar (UTC)": r["last_bar_utc"],
                "Last retrieved (UTC)": r["last_retrieved_at_utc"],
                "Sessions": r["sessions"],
            }
            for r in cov
        ],
        use_container_width=True,
    )
    symbols = sorted({r["symbol"] for r in cov})
    c1, c2 = st.columns(2)
    sym = c1.selectbox("Symbol", symbols)
    tf = c2.selectbox("Timeframe", [t for t in TIMEFRAMES if t in available])
    rows = db.execute(
        "SELECT bar_start_utc, open, high, low, close, volume, correction_count FROM "
        "market_bars_current WHERE symbol = ? AND timeframe = ? ORDER BY bar_start_utc DESC LIMIT 500",
        (sym, tf),
    )
    if rows:
        rows = list(reversed(rows))
        st.line_chart({"close": [r["close"] for r in rows]})
        st.dataframe(rows[-50:], use_container_width=True)


def _news_view(db) -> None:
    from engines.news_tagging import NewsTagger, recent_news

    items = recent_news(db, limit=200)
    st.caption(
        "Headlines, links and timestamps only (metadata retention); no article text is stored. "
        "Company, sector and theme tags are deterministic matches shown with their evidence. "
        "'Potentially market-moving' is a keyword match, not a verified impact."
    )
    if not items:
        st.warning("No news has been collected yet.")
        return
    tagger = NewsTagger(db)
    only_flagged = st.checkbox("Only potentially market-moving or company-linked headlines")
    shown = 0
    for it in items:
        tags = tagger.tag(it["title"], as_of=(it["published_at_utc"] or "")[:10] or None)
        if only_flagged and not (tags.companies or tags.potentially_market_moving):
            continue
        shown += 1
        st.markdown(
            f"**[{it['title']}]({it['url']})**  \n{it['publisher']} · published "
            f"{it['published_at_utc'] or 'unknown'} · collected {it['collected_at_utc']}"
        )
        bits = []
        for c in tags.companies:
            review = " (needs review)" if c["needs_review"] else ""
            bits.append(f"{c['ticker']} · {c['sector'] or 'sector unknown'} [{c['evidence']}]{review}")
        bits += [f"theme: {t['theme']} [{', '.join(t['evidence'])}]" for t in tags.themes]
        if tags.potentially_market_moving:
            bits.append(
                "potentially market-moving (keyword match, unverified): " + ", ".join(tags.market_moving)
            )
        if bits:
            st.caption(" | ".join(bits))
    st.caption(f"{shown} headline(s) shown.")


def _health_view(db) -> None:
    rows = db.execute(
        "SELECT source_id, name, lifecycle_status, terms_status, retention_mode, last_success_at_utc, "
        "last_attempt_at_utc, consecutive_failures, last_error FROM sources "
        "WHERE lifecycle_status = 'ACTIVE' ORDER BY source_id"
    )
    st.dataframe(rows, use_container_width=True)
    runs = db.execute(
        "SELECT run_id, job, source_id, started_at_utc, status, items_fetched, items_accepted, "
        "items_rejected, errors FROM collector_runs ORDER BY run_id DESC LIMIT 50"
    )
    st.subheader("Recent collection runs")
    st.dataframe(runs, use_container_width=True)


main()
