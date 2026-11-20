"""PSX Fundamental & News Intelligence: Streamlit entry point (Phase 0 skeleton).

This page shows only real, stored data (spec section 12 UI standard). Market bars and news headlines are
read from the configured database. When nothing has been collected, the page says so instead of showing
placeholder numbers. No trading signals or buy/sell instructions.
"""

from __future__ import annotations

import os

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
PAGE_BRIEF = "Company brief"
PAGE_MARKET = "Market dashboard"
PAGE_TRACKER = "Performance tracker"


def main() -> None:
    st.set_page_config(page_title="PSX News Intelligence", layout="wide")
    settings = load_settings()
    # The older pages need the news database, which is only there when PSXNI_TURSO_DATABASE_URL is set;
    # without it they would only say "nothing to show", so they are not offered.
    pages = [PAGE_MARKET, PAGE_BRIEF]
    from engines import tracker_view

    if os.environ.get(tracker_view.TOKEN_VAR):  # offered only where the read-only token is configured
        pages.append(PAGE_TRACKER)
    if settings.database_configured:
        pages += [PAGE_OVERVIEW, PAGE_COMPANY]
    goto = st.session_state.pop("_goto_page", None)  # set by a button on another page
    if goto in pages:
        st.session_state["app_page"] = goto
    page = st.sidebar.radio("Page", pages, key="app_page")
    if page == PAGE_MARKET:
        _market_dashboard()
        return
    if page == PAGE_TRACKER:
        _tracker_page()
        return
    if page == PAGE_BRIEF:
        _brief_page()
        return
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


def _library():
    """A fresh handle on psx-library. Only SELECT is ever issued; the write cap of 1 is a guard."""
    from engines import library_db

    db = library_db.get_library_readonly_connection().db
    if hasattr(db, "max_rows_read"):  # the Turso client; other backends have no per-process budget
        db.max_rows_read = max(db.max_rows_read, 400_000)
        db.max_rows_written = 1
    return db


@st.cache_data(ttl=900, show_spinner="Reading the tracker...")
def _tracker_data(day_key: str) -> dict:
    from engines import tracker_view

    token = os.environ.get(tracker_view.TOKEN_VAR, "")
    repo = os.environ.get(tracker_view.REPO_VAR, tracker_view.DEFAULT_REPO)
    return tracker_view.fetch(token, repo)


def _tracker_page() -> None:
    """Prospective performance of the setups rankings, read from the data branch. Read only; not advice."""
    from datetime import UTC, datetime

    from engines import tracker_view

    st.title("Performance tracker")
    st.caption(
        "Each weekday the live top 10 of each ranking is recorded, then compared with the whole eligible "
        "group over the next sessions. A reading needs at least 20 snapshots. Scores are not forecasts and "
        "nothing here is advice."
    )
    try:
        p = _tracker_data(datetime.now(UTC).strftime("%Y-%m-%d %H"))
    except tracker_view.TrackerError as exc:
        st.error(str(exc))
        return
    first, last = p.get("first_day"), p.get("last_day")
    st.markdown(
        f"**{p['snapshots']}** snapshots recorded ({first or 'none'} to {last or 'none'}); "
        f"file generated {p['generated_utc']}."
    )
    st.dataframe(tracker_view.table(p), hide_index=True, width="stretch")
    st.caption(p["method"])


@st.cache_data(ttl=900, show_spinner="Reading the brain...")
def _dashboard_data(day_key: str) -> dict:
    from datetime import UTC, datetime

    from engines import market_dashboard

    return market_dashboard.load(_library(), datetime.now(UTC))


def _market_dashboard() -> None:
    """Market view from the library: breadth, companies to look at, notable moves. Read only; no advice."""
    import os

    from engines import library_db

    st.title("Market dashboard")
    st.caption(
        "Evidence on file, ordered for attention. Scores are not forecasts, explanations are candidates "
        "not proof, and nothing here is a buy or sell view."
    )
    if not (os.environ.get(library_db.URL_VAR) and os.environ.get(library_db.TOKEN_VAR)):
        st.info(f"The library is not configured here (set {library_db.URL_VAR} and {library_db.TOKEN_VAR}).")
        return
    _dashboard_body()


@st.fragment(run_every=600)
def _dashboard_body() -> None:
    """Re-runs by itself every 10 minutes (an open page does not otherwise update), reading the 15-minute
    cache, so a new trading day appears without anyone pressing anything."""
    from datetime import UTC, datetime

    from engines import market_dashboard

    if st.button("Refresh now", key="dash_refresh"):
        _dashboard_data.clear()
        st.rerun()
    try:
        d = _dashboard_data(datetime.now(UTC).strftime("%Y-%m-%d %H"))
    except Exception as exc:  # noqa: BLE001 - show the reason, never a half page
        st.error(f"Could not read the library: {exc}")
        return
    from engines import company_names
    from engines import dashboard_html as ui

    st.markdown(ui.CSS, unsafe_allow_html=True)
    st.markdown(ui.status_bar(d["price_day"], d["news_day"], d["universe"]), unsafe_allow_html=True)
    tech_tab, fund_tab, both_tab, market_tab, radar_tab, moves_tab = st.tabs(
        [
            "Technical setups",
            "Fundamental setups",
            "Fund + Tech setups",
            "Market",
            "Watch list",
            "Why it moved",
        ]
    )
    note = (
        "Top 10 by measured evidence on file: equal-weight, uncalibrated scores, not forecasts and not "
        "advice. Stocks must trade at least Rs 25m a day. Tap one for the evidence and what is not on file."
    )
    for tab, mode, heading in (
        (tech_tab, "technical", "Technical setups"),
        (fund_tab, "fundamental", "Fundamental setups"),
        (both_tab, "combined", "Fundamental + technical setups"),
    ):
        with tab:
            st.markdown(f"**{heading} · top 10** ({d['setups']['eligible']} stocks assessed)")
            st.caption(note)
            st.markdown(ui.setup_cards_html(d["setups"][mode], mode), unsafe_allow_html=True)
    with both_tab:
        from engines import setups

        typed = st.text_input("Check a stock (symbol)", "", key="setup_check").strip().upper()
        if typed:
            st.markdown(ui.lookup_html(setups.lookup(d["setups"], typed)), unsafe_allow_html=True)
            if st.button(f"Open the {typed} company page", key="open_company"):
                st.session_state["_goto_page"] = PAGE_BRIEF
                st.session_state["brief_symbol"] = typed
                st.rerun()
    with market_tab:
        st.markdown(ui.breadth_card(d["breadth"]), unsafe_allow_html=True)
        mode = st.segmented_control(
            "Top movers", ["Most active", "Gainers", "Losers"], default="Most active", key="mover_mode"
        )
        shown = market_dashboard.order_movers(d["movers"], mode or "Most active")
        st.markdown(ui.mover_rows(shown), unsafe_allow_html=True)
    with radar_tab:
        st.caption(
            "Companies with the most evidence on file in the last 7 days, with the 30-day context. "
            "Attention list for research, not a recommendation. Tap one for the detail."
        )
        names = {r["symbol"]: company_names.official_name(r["symbol"]) for r in d["radar"]}
        st.markdown(ui.radar_cards_html(d["radar"], names, d.get("radar_ctx")), unsafe_allow_html=True)
    with moves_tab:
        st.caption(
            "Notable moves by day, newest first, and what the evidence on file may explain. "
            "Candidates, not proof. A day's moves appear once its prices are in (about an hour after "
            "the close)."
        )
        st.markdown(ui.moves_by_day_html(d["moves"]), unsafe_allow_html=True)
    st.caption(
        f"Prices to {d['price_day'] or 'unknown'}, news to {d['news_day'] or 'unknown'}. "
        f"Read {d['built_utc']} UTC; this page re-reads every 10 minutes. A trading day's prices arrive "
        "after the market closes and the technical engine has updated (about an hour after the close)."
    )


@st.cache_data(ttl=1800, show_spinner="Reading the brain (cached for 30 minutes)...")
def _brief_context(today_iso: str) -> dict:
    from datetime import date

    from engines import company_brief

    return company_brief.market_context(_library(), date.fromisoformat(today_iso))


@st.cache_data(ttl=1800, show_spinner="Loading this company...")
def _brief_company(symbol: str, today_iso: str) -> dict:
    from datetime import date

    from engines import company_brief

    ctx = _brief_context(today_iso)
    return company_brief.load(_library(), symbol, date.fromisoformat(today_iso), ctx)


def _brief_page() -> None:
    """Everything the brain holds on one company. Read only. Not advice: no buy, sell or price view."""
    import os
    from datetime import UTC, datetime

    st.title("Company brief")
    st.caption(
        "What the brain holds on one company: price, moves and what may explain them, results, "
        "corporate actions, news and the technical engine's heuristics. Evidence on file only; "
        "not proof of cause, no buy or sell view."
    )
    from engines import library_db

    if not (os.environ.get(library_db.URL_VAR) and os.environ.get(library_db.TOKEN_VAR)):
        st.info(f"The library is not configured here (set {library_db.URL_VAR} and {library_db.TOKEN_VAR}).")
        return
    today = datetime.now(UTC).date().isoformat()
    try:
        ctx = _brief_context(today)
    except Exception as exc:  # noqa: BLE001 - show the reason, never a half page
        st.error(f"Could not read the library: {exc}")
        return
    tracked = sorted(ctx["bars"])
    choice = st.selectbox(
        "Company (symbols with a price series)", tracked, index=None, placeholder="Pick a symbol"
    )
    typed = st.text_input("...or type any symbol the brain tracks", "", key="brief_symbol").strip().upper()
    symbol = typed or choice
    if not symbol:
        st.write(f"{len(tracked)} symbols have a price series. Pick one above.")
        return
    brief = _brief_company(symbol, today)
    standing = None
    try:  # where the company stands in the setups rankings (uses the dashboard's 15-minute cache)
        from engines import setups

        standing = setups.lookup(_dashboard_data(datetime.now(UTC).strftime("%Y-%m-%d %H"))["setups"], symbol)
    except Exception:  # noqa: BLE001 - the brief stands without it
        standing = None
    _render_brief(brief, standing)


def _render_brief(b: dict, standing: dict | None = None) -> None:
    from engines import brief_html as bh
    from engines import company_names
    from engines import dashboard_html as ui

    st.markdown(ui.CSS, unsafe_allow_html=True)
    st.markdown(bh.header(b, company_names.official_name(b["symbol"])), unsafe_allow_html=True)
    p = b["price"]
    if p:
        st.line_chart({d: c for d, c in p["series"]}, height=200)
    st.markdown(bh.standing(standing), unsafe_allow_html=True)
    names = ["Results", "News and filings", "Moves", "Technical", "Fundamentals"]
    overview, filings, moves_tab, tech, fund = st.tabs(names)
    with overview:
        c = b["eps_change"]
        if c and c.get("pct") is not None:
            st.markdown(
                f"**Like-for-like EPS, {c['label']}:** {c['prev']:g} to {c['cur']:g} ({c['pct']:+.0f}%)"
            )
        st.markdown("**Results**")
        st.markdown(bh.facts(b["results"], "No results on file."), unsafe_allow_html=True)
        st.markdown("**Corporate actions (last 12 months)**")
        st.markdown(bh.facts(b["actions"], "No corporate actions on file."), unsafe_allow_html=True)
    with filings:
        st.markdown("**Announcements (last month)**")
        st.markdown(bh.announcements(b["announcements"]), unsafe_allow_html=True)
        st.markdown("**News (last month)**")
        st.markdown(bh.news(b["news"]), unsafe_allow_html=True)
    with moves_tab:
        st.caption("Notable moves and what the evidence on file may explain: candidates, not proof.")
        st.markdown(bh.moves(b["moves"]), unsafe_allow_html=True)
    with tech:
        st.caption("The technical engine's heuristics, not probabilities.")
        st.markdown(bh.facts(b["technical"], "No technical-engine signals on file."), unsafe_allow_html=True)
    with fund:
        rows = bh.facts(b["fundamentals"], "No fundamentals snapshot on file.", "as_of")
        st.markdown(rows, unsafe_allow_html=True)
    with st.expander("What we do not know"):
        for u in b["unknown"] or ["Nothing flagged."]:
            st.write(f"- {u}")


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
    st.dataframe(d["progress"], width="stretch")
    st.subheader("Session completeness")
    st.caption(
        "COMPLETE / INCOMPLETE / ANOMALY / MISSING / PROVIDER_UNAVAILABLE are graded against the bars the "
        "market actually traded that session; weekends, recorded holidays and closures are never counted "
        "as missing. Volume is not used."
    )
    st.dataframe(d["quality"]["summary"], width="stretch")
    st.subheader("Remaining gaps and provider-unavailable history")
    st.dataframe(d["quality"]["gaps"][:200], width="stretch")
    st.subheader("Recent runs (outcome, trigger, continuation pass, rows written)")
    st.dataframe(d["runs"], width="stretch")
    st.subheader("Source health (retries and failures)")
    st.dataframe(d["sources"], width="stretch")


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
        width="stretch",
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
        st.dataframe(rows[-50:], width="stretch")


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
    st.dataframe(rows, width="stretch")
    runs = db.execute(
        "SELECT run_id, job, source_id, started_at_utc, status, items_fetched, items_accepted, "
        "items_rejected, errors FROM collector_runs ORDER BY run_id DESC LIMIT 50"
    )
    st.subheader("Recent collection runs")
    st.dataframe(runs, width="stretch")


main()
