"""M1: X watchlist completeness, manual X import rules, priority list and liquidity qualification."""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load, load_json
from engines import universe as uv
from engines import x_watchlist as xw

SUPPLIED = """MarioNawfal AJEnglish imemon15 clashreport AlphaWireHQ Conflict_Matrix AlArabiya_Eng CENTCOM CNN
TehranTimes79 ARNOfficiall trtworld RT_com MeherJazibAli Asad_Ashah AsadAToor LodhiMaleeha Portfolio360App
iihtishamm KhaqanNajeeb iabdullah278 4xpakistan KhAneeqIftikhar intelligent_pk SaudSami kschehzad
Muhamma10420762 miandawoodadv toplinesec Nasir_dar101 awais_hameed 81ShahbazRana BullTheoryio""".split()


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    yield d
    d.close()


# ---------------------------------------------------------------- watchlist
def test_all_33_supplied_accounts_present_exactly(db):
    rows = {r["handle"]: r for r in db.execute("SELECT * FROM media_accounts WHERE platform = 'x'")}
    assert len(SUPPLIED) == 33
    for h in SUPPLIED:
        assert h in rows, h
        assert rows[h]["supplied_url"] == f"https://x.com/{h}"
        assert rows[h]["monitoring_status"] == "disabled"
        assert rows[h]["identity_verification"] == "unverified"


def test_owner_groups_match_supplied_order():
    g = xw.owner_groups()
    assert {g[h] for h in SUPPLIED[:13]} == {"international_news_geopolitics_conflict"}
    assert {g[h] for h in SUPPLIED[13:32]} == {"pakistan_policy_economy_politics"}
    assert g["BullTheoryio"] == "market_investment_commentary"


def test_previous_accounts_and_categories_kept(db):
    wl = load_json("media_watchlist.json")["accounts"]
    assert sum(a["platform"] == "youtube" for a in wl) == 7
    assert sum(a["platform"] == "x" and a["handle"] is None for a in wl) == 2  # pending, never guessed
    cats = {a["handle"]: a["category"] for a in wl}
    assert cats["TehranTimes79"] == "pakistan_politics_geopolitics"  # pre-existing value unchanged


def test_status_never_claims_monitoring(db):
    st = xw.status(db)
    assert len([s for s in st if s["handle"]]) == 33
    assert not any(s["monitored"] for s in st)
    assert all(s["last_retrieved_at_utc"] is None for s in st)
    assert all("no authorised automated access" in s["authorisation"] for s in st)


# ---------------------------------------------------------------- manual import
def _rec(handle="KhaqanNajeeb", pid="1", text="OGDC may rally on new gas discovery", **kw):
    return {"handle": handle, "post_url": f"https://x.com/{handle}/status/{pid}",
            "published_at_utc": "2026-11-01T10:00:00Z", "text": text, **kw}


def _imp(db, recs):
    return xw.import_posts(db, recs, importer="owner", rights_attestation="copied by owner from own feed")


def test_import_requires_attestation(db):
    with pytest.raises(ValueError):
        xw.import_posts(db, [_rec()], importer="owner", rights_attestation=" ")


def test_import_rejects_unknown_and_malformed(db):
    r = _imp(db, [
        _rec(handle="SomeoneElse"),
        {**_rec(), "post_url": "https://twitter.com/KhaqanNajeeb/status/1"},
        {**_rec(), "post_url": "https://x.com/CNN/status/1"},
        {**_rec(pid="9"), "published_at_utc": "yesterday"},
    ])
    assert len(r["rejected"]) == 4 and not r["accepted"]
    assert not db.execute("SELECT 1 FROM media_items")
    assert not db.execute("SELECT 1 FROM media_accounts WHERE handle = 'SomeoneElse'")


def test_prediction_is_tracked_and_never_evidence(db):
    r = _imp(db, [_rec()])
    a = r["accepted"][0]
    assert a["claim_type"] == "prediction" and a["companies"] == ["OGDC"]
    p = db.execute("SELECT direction, result, company_id FROM media_predictions")
    assert len(p) == 1 and p[0]["direction"] == "positive" and p[0]["result"] is None
    assert not db.execute("SELECT 1 FROM event_evidence WHERE claim LIKE '%rally%'")
    assert r["needs_verification"]
    last = [s for s in xw.status(db) if s["handle"] == "KhaqanNajeeb"][0]
    assert last["posts"] == 1 and last["last_retrieved_at_utc"] and not last["monitored"]


def test_idempotent_and_copy_detection(db):
    _imp(db, [_rec()])
    r = _imp(db, [_rec(), _rec(handle="SaudSami", pid="2")])
    assert r["duplicates"] == ["https://x.com/KhaqanNajeeb/status/1"]
    assert r["accepted"][0]["copy_of"] == "https://x.com/KhaqanNajeeb/status/1"


def test_claim_types_are_not_facts():
    assert xw.claim_type("OGDC looks bullish, breakout above resistance") == "analyst_interpretation"
    assert xw.claim_type("Sources say SBP could cut rates") in ("rumour", "prediction")
    assert xw.claim_type("hello") == "unclear"
    assert xw.claim_type("anything", official=True) == "official_statement"
    assert "verified_fact" not in {xw.claim_type(t) for t in ("SBP raises policy rate", "hello")}


def test_deleted_post_recorded_without_text(db):
    r = _imp(db, [{**_rec(pid="5", text=""), "availability": "deleted"}])
    assert r["accepted"][0]["availability"] == "deleted"
    assert db.execute("SELECT rejection_reason FROM media_items")[0]["rejection_reason"] == "deleted"


# ---------------------------------------------------------------- X claims and events
def _event(db):
    db.execute(
        "INSERT INTO events(event_type, headline, status_stage, first_seen_at_utc, created_at_utc, "
        "updated_at_utc) VALUES ('other','Gas discovery reported','rumour','2026-11-01T00:00:00Z',"
        "'2026-11-01T00:00:00Z','2026-11-01T00:00:00Z')")
    return db.execute("SELECT MAX(event_id) AS e FROM events")[0]["e"]


def test_link_to_event_is_unverified_and_not_independent(db):
    _imp(db, [_rec(), _rec(handle="SaudSami", pid="2")])
    eid = _event(db)
    before = db.execute("SELECT * FROM events WHERE event_id = ?", (eid,))[0]
    a = xw.link_to_event(db, "https://x.com/KhaqanNajeeb/status/1", eid)
    b = xw.link_to_event(db, "https://x.com/SaudSami/status/2", eid, role="context")
    xw.link_to_event(db, "https://x.com/KhaqanNajeeb/status/1", eid)  # idempotent
    assert (a["independence"], b["independence"]) == ("same_source", "repost")
    links = db.execute("SELECT independence FROM media_event_links")
    assert len(links) == 2 and "independent" not in {r["independence"] for r in links}
    assert not db.execute("SELECT 1 FROM event_evidence WHERE event_id = ?", (eid,))
    assert db.execute("SELECT * FROM events WHERE event_id = ?", (eid,))[0] == before
    with pytest.raises(ValueError):
        xw.link_to_event(db, "https://x.com/KhaqanNajeeb/status/1", eid, role="confirmation")


def test_post_write_is_atomic_and_run_closed_on_failure(db):
    class Bad:
        def tag(self, text, as_of=None):
            from engines.news_tagging import Tagging
            return Tagging(companies=[{"company_id": "NO_SUCH", "ticker": "X", "evidence": "x"}])

    with pytest.raises(Exception):  # noqa: B017 - foreign-key failure from the database driver
        xw.import_posts(db, [_rec()], importer="owner", rights_attestation="ok", tagger=Bad())
    assert not db.execute("SELECT 1 FROM media_items")
    run = db.execute("SELECT status FROM collector_runs WHERE job = 'x_manual_import'")[0]
    assert run["status"] == "failed"


def test_non_object_and_same_batch_duplicate(db):
    r = _imp(db, ["junk", _rec(), _rec()])
    assert len(r["rejected"]) == 1 and len(r["accepted"]) == 1 and len(r["duplicates"]) == 1


# ---------------------------------------------------------------- universe / liquidity
def _days(n, end="2026-10-30"):
    from datetime import date, timedelta

    from engines.market_calendar import load_calendar
    cal, d, out = load_calendar(), date.fromisoformat(end), []
    while len(out) < n:
        if cal.is_trading_day(d.isoformat()):
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out


def _bars(db, sym, days, vol, close=10):
    for d in days:
        db.execute(
            "INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
            "open, high, low, close, volume, retrieved_at_utc) "
            "VALUES ('scs_chart',?,'1d',?,?,?,?,?,?,?,?)",
            (sym, f"{d}T00:00:00Z", d, close, close, close, close, vol, f"{d}T12:00:00Z"),
        )


AS_OF = "2026-10-30"


def test_liquidity_policy(db):
    days = _days(20)
    _bars(db, "OGDC", days, 150_000)
    _bars(db, "HBL", days, 50_000)
    _bars(db, "LUCK", days[:12], 900_000)  # missing 8 of the 20 market sessions
    ogdc = uv.liquidity(db, "OGDC", as_of=AS_OF)
    assert ogdc.state == "qualified" and ogdc.adv_shares == 150_000
    assert ogdc.avg_traded_value_pkr_approx == 1_500_000 and "approximation" in ogdc.reasons[0]
    assert uv.liquidity(db, "HBL", as_of=AS_OF).state == "below_threshold"
    luck = uv.liquidity(db, "LUCK", as_of=AS_OF)
    assert luck.state == "insufficient_data" and luck.adv_shares is None
    assert "not treated as zero" in luck.reasons[0]
    assert uv.liquidity(db, "PSO", as_of=AS_OF).state == "no_market_data"


def test_threshold_boundary_and_window_end(db):
    days = _days(25)
    _bars(db, "OGDC", days[:20], 100_000)
    _bars(db, "OGDC", days[20:], 1)  # older than the window: ignored
    assert uv.liquidity(db, "OGDC", as_of=AS_OF).state == "qualified"
    # one session earlier: the window now includes one 1-share session, so ADV falls just below 100,000
    assert uv.liquidity(db, "OGDC", as_of=days[1]).state == "below_threshold"


def test_unlisted_market_holiday_not_counted_as_missing(db):
    days = _days(21)
    holiday = days[5]  # market traded on no symbol that day (e.g. a moon-dependent holiday)
    _bars(db, "OGDC", [d for d in days if d != holiday], 200_000)
    assert uv.liquidity(db, "OGDC", as_of=AS_OF).state == "qualified"


def test_stale_data_states_no_adv(db):
    _bars(db, "OGDC", _days(20), 500_000)
    st = uv.liquidity(db, "OGDC", as_of="2026-11-30")
    assert st.state == "insufficient_data" and "stale" in st.reasons[0]


def test_priority_never_removed_by_liquidity(db):
    _bars(db, "HBL", _days(20), 10)
    uv.add_priority(db, ["HBL", "ZZZ"])
    uv.add_priority(db, ["HBL"])
    rows = {r["ticker"]: r for r in uv.universe(db, as_of=AS_OF)}
    assert uv.priority_list(db) == ["HBL", "ZZZ"]
    assert rows["HBL"]["priority"] and rows["HBL"]["liquidity_state"] == "below_threshold"
    assert rows["HBL"]["market_analytics_eligible"]
    assert rows["ZZZ"]["priority"] and not rows["ZZZ"]["in_company_master"]
    assert all(r["broad_monitoring"] for r in rows.values())
    assert not rows["OGDC"]["market_analytics_eligible"]
    master = db.execute("SELECT COUNT(*) AS n FROM company_identifiers WHERE id_type = 'psx_ticker' "
                        "AND valid_to IS NULL")[0]["n"]
    assert len(rows) == master + 1  # the whole current-ticker master plus the priority-only ticker


def test_zero_volume_session_counts_as_a_traded_session_not_a_missing_one(db):
    """A thin stock can trade a day with zero volume. That is a real observation: it counts as one of the
    20 sessions and lowers ADV. It must never be treated as a missing session, which would stop the stock from
    qualifying at all. ADV here is (19 x 200,000 + 0) / 20 = 190,000."""
    days = sorted(_days(20))
    _bars(db, "THIN", days[:19], 200_000)
    _bars(db, "THIN", [days[19]], 0)
    liq = uv.liquidity(db, "THIN", as_of=days[19])
    assert liq.state == "qualified" and liq.sessions == 20
    assert liq.adv_shares == 190_000.0
