"""PSX Fundamental & News Intelligence: Streamlit entry point (Phase 0 skeleton).

This page shows only real, stored data (spec section 12 UI standard). Market bars and news headlines are
read from the configured database. When nothing has been collected, the page says so instead of showing
placeholder numbers. No trading signals or buy/sell instructions.
"""

from __future__ import annotations

import streamlit as st

from config.settings import load_settings

PHASES = [  # master programme (docs/PROJECT_ROADMAP.md); code status only, nothing implies production use
    ("Stage 1", "Data architecture, SCS market data, RSS collection", "TESTED; operational acceptance "
        "pending"),
    ("Stage 2", "News, event, exposure and impact intelligence", "TESTED offline; not activated"),
    ("M1", "X watchlist, priority list, liquidity qualification", "TESTED offline"),
    ("M2-M5", "Financial statements, fundamentals, market behaviour, valuation", "TESTED offline "
        "(synthetic)"),
    ("M6-M9", "Macro vintages, validation, portfolio engine, integrated reports", "TESTED offline "
        "(synthetic)"),
    ("M10", "Activation runbook; migrations 0011-0014 rehearsed on disposable Turso", "NOT ACTIVATED"),
]


PAGE_OVERVIEW = "Overview"
PAGE_COMPANY = "Company intelligence"


def main() -> None:
    st.set_page_config(page_title="PSX News Intelligence", layout="wide")
    settings = load_settings()
    page = st.sidebar.radio("Page", [PAGE_OVERVIEW, PAGE_COMPANY], key="app_page")
    if page == PAGE_COMPANY:
        _company_page(settings)
        return

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


def _company_page(settings) -> None:
    """Local, private company view on the same database handle as the other pages. Read-only (SELECT only)."""
    st.title("Company intelligence")
    if not settings.database_configured:
        st.info("No database is configured (set PSXNI_TURSO_DATABASE_URL). Nothing collected can be shown.")
        return
    from database.connection import connect
    from engines.company_intelligence_view import company_intelligence_view

    # A fresh handle per render, from the same configured connect(): Streamlit reruns on other threads, and a
    # SQLite handle cannot be shared across them. Read-only: the view issues SELECT statements only.
    db = connect()
    try:
        company_intelligence_view(db)
    finally:
        db.close()


@st.cache_resource
def _db():
    from database.connection import connect

    return connect()


def _data_views() -> None:
    db = _db()
    (market, intel, company, sector, review, valid, ready, ops, news, health, fin_t, fund_t, val_t, mkt_t,
     macro_t, report_t) = st.tabs(
        ["PSX market data", "Intelligence", "Company report", "Sector report", "Review queue", "Validation",
         "Readiness", "Collection operations", "News", "Source health", "Financial statements",
         "Fundamentals", "Valuation", "Market behaviour", "Macro", "Integrated report"])
    from engines import dashboard_views as dv
    from engines import research_views as rv

    for tab, view in ((fin_t, rv.financials_view), (fund_t, rv.fundamentals_view), (val_t, rv.valuation_view),
                      (mkt_t, rv.market_behaviour_view), (macro_t, rv.macro_view),
                      (report_t, rv.integrated_report_view)):
        with tab:
            view(db)

    with intel:
        dv.intelligence_view(db)
    with company:
        dv.company_view(db)
    with sector:
        dv.sector_view(db)
    with review:
        dv.review_view(db)
    with valid:
        dv.validation_view(db)
    with ready:
        dv.readiness_view(db)
    with market:
        _market_view(db)
    with ops:
        _ops_view(db)
    with news:
        _news_view(db)
    with health:
        _health_view(db)


def _market_symbols() -> list[str]:
    import os

    from collectors.market_ohlcv import DEFAULT_SYMBOLS

    raw = os.environ.get("PSXNI_MARKET_SYMBOLS", ",".join(DEFAULT_SYMBOLS))
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@st.cache_data(ttl=600, show_spinner=False)
def _cached_coverage(_db, symbols: tuple[str, ...]) -> list[dict]:
    from collectors.market_ohlcv import SOURCE_ID, TIMEFRAMES
    from engines.market_quality import coverage_summary

    return coverage_summary(_db, SOURCE_ID, symbols, list(TIMEFRAMES))


@st.cache_data(ttl=900, show_spinner=False)
def _cached_ops(_db, symbols: tuple[str, ...]) -> dict:
    from datetime import UTC, datetime

    from engines import collection_ops as ops

    now = datetime.now(UTC)
    return {
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
        "latest": ops.latest_success(_db),
        "current": ops.current_market_runs(_db),
        "triggers": ops.trigger_status(_db, now),
        "progress": ops.backfill_progress(_db, list(symbols), now),
        "quality": ops.completeness(_db, list(symbols), now),
        "runs": ops.recent_runs(_db),
        "sources": ops.source_health(_db),
    }


def _ops_view(db) -> None:
    d = _cached_ops(db, tuple(_market_symbols()))
    st.caption(
        f"As of {d['as_of']} (refreshed at most every 15 minutes). Read-only; every value is from the run "
        "log, source health, the trigger heartbeat and indexed bar lookups. 'Not recorded' means the value "
        "was never stored."
    )
    c1, c2, c3 = st.columns(3)
    for col, job, label in ((c1, "news", "Last successful news collection"),
                            (c2, "market_ohlcv", "Last successful market collection")):
        rec = d["latest"].get(job)
        col.metric(label, rec["finished_utc"] if rec else "none recorded", rec["outcome"] if rec else None)
    c3.metric("Market run now", ", ".join(f"#{r['run_id']} {r['outcome']}" for r in d["current"]) or "idle")
    st.subheader("Triggers")
    st.table(d["triggers"])
    st.subheader("Backfill progress (share of each target window covered)")
    st.dataframe(d["progress"], use_container_width=True)
    st.subheader("Session completeness")
    st.caption(
        "COMPLETE / INCOMPLETE / ANOMALY / MISSING / PROVIDER_UNAVAILABLE are graded against the bars the "
        "market actually traded that session; weekends, recorded holidays and closures are never counted "
        "as missing. Volume is not used."
    )
    st.dataframe(d["quality"]["summary"], use_container_width=True)
    st.subheader("Remaining gaps and provider-unavailable history")
    st.dataframe(d["quality"]["gaps"][:200], use_container_width=True)
    st.subheader("Recent runs (outcome, trigger, continuation pass, rows written)")
    st.dataframe(d["runs"], use_container_width=True)
    st.subheader("Source health (retries and failures)")
    st.dataframe(d["sources"], use_container_width=True)


def _market_view(db) -> None:
    from collectors.market_ohlcv import TIMEFRAMES

    # indexed first/latest-bar lookups (a few rows read), cached; the market_coverage view scans every bar
    cov = [r for r in _cached_coverage(db, tuple(_market_symbols())) if r["first_bar_utc"]]
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
                "First bar (UTC)": r["first_bar_utc"],
                "Latest bar (UTC)": r["last_bar_utc"],
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
