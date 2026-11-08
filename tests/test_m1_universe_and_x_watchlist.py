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


# ---------------------------------------------------------------- universe / liquidity
def _bars(db, sym, n, vol):
    for i in range(n):
        d = f"2026-10-{i + 1:02d}"
        db.execute(
            "INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
            "open, high, low, close, volume, retrieved_at_utc) "
            "VALUES ('scs_chart',?,'1d',?,?,10,11,9,10,?,?)",
            (sym, f"{d}T00:00:00Z", d, vol, f"{d}T12:00:00Z"),
        )


def test_liquidity_policy(db):
    _bars(db, "OGDC", 20, 150_000)
    _bars(db, "HBL", 20, 50_000)
    _bars(db, "LUCK", 12, 900_000)
    assert uv.liquidity(db, "OGDC").state == "qualified"
    assert uv.liquidity(db, "OGDC").avg_traded_value_pkr_approx == 1_500_000
    assert uv.liquidity(db, "HBL").state == "below_threshold"
    luck = uv.liquidity(db, "LUCK")
    assert luck.state == "insufficient_data" and luck.adv_shares is None
    assert uv.liquidity(db, "PSO").state == "no_market_data"


def test_priority_never_removed_by_liquidity(db):
    _bars(db, "HBL", 20, 10)
    uv.add_priority(db, ["HBL", "ZZZ"])
    uv.add_priority(db, ["HBL"])
    rows = {r["ticker"]: r for r in uv.universe(db)}
    assert uv.priority_list(db) == ["HBL", "ZZZ"]
    assert rows["HBL"]["priority"] and rows["HBL"]["liquidity_state"] == "below_threshold"
    assert rows["HBL"]["market_analytics_eligible"]
    assert rows["ZZZ"]["priority"] and not rows["ZZZ"]["in_company_master"]
    assert all(r["broad_monitoring"] for r in rows.values())
    assert not rows["OGDC"]["market_analytics_eligible"]
