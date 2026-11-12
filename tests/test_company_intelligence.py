"""Company intelligence view: stored data only, descriptive signals, not-yet-collected handling, attribution.

All data is SYNTHETIC (tests/fixtures/investify/*_synthetic.html and invented metric values). The page is
tested through Streamlit's AppTest on a local SQLite file, so nothing here touches the network or a
shared database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors import investify_fundamentals as fund
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import company_intelligence as ci
from engines import investify_extract as x

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "investify"
RULES = ci.load_rules()


def m(label, value, unit="number", period="2026 FY", text=None):
    return {"label": label, "value_text": text or str(value), "value": value, "period_basis": period}


# ------------------------------------------- thresholds: each rule, both sides, and the words

def test_low_pe_fires_below_ten_and_shows_the_criterion():
    s = {r["id"]: r for r in ci.screening_signals([m("P/E Annual", 5.4)], RULES)}["low_pe"]
    assert s["met"] is True and s["criterion"] == "P/E Annual < 10" and s["observed"] == "5.4"
    s = {r["id"]: r for r in ci.screening_signals([m("P/E Annual", 10)], RULES)}["low_pe"]
    assert s["met"] is False  # the boundary is not met


def test_high_net_margin_needs_more_than_twenty_percent():
    above = {r["id"]: r for r in ci.screening_signals([m("Net Margin", 20.5)], RULES)}
    at_limit = {r["id"]: r for r in ci.screening_signals([m("Net Margin", 20)], RULES)}
    assert above["high_net_margin"]["met"] is True and at_limit["high_net_margin"]["met"] is False


def test_strong_roe_and_positive_growth_use_their_labels():
    sig = {r["id"]: r for r in ci.screening_signals(
        [m("Return on Equity", 16.0), m("Growth Expected", 3.1)], RULES)}
    assert sig["strong_roe"]["met"] is True
    assert sig["positive_growth"]["met"] is True
    assert sig["positive_growth"]["criterion"].startswith("Growth Expected")
    assert {r["id"]: r for r in ci.screening_signals([m("Growth Expected", -2.0)], RULES)}[
        "positive_growth"]["met"] is False


def test_comfortable_liquidity_uses_the_ratio_value_not_its_text():
    s = {r["id"]: r for r in ci.screening_signals([m("Current Ratio", 1.62, text="1.62 : 1")], RULES)}
    assert s["comfortable_liquidity"]["met"] is True and s["comfortable_liquidity"]["observed"] == "1.62 : 1"


def test_no_signal_uses_directive_language():
    text = json.dumps(ci.screening_signals([m("P/E Annual", 5.4), m("Net Margin", 30)], RULES)).lower()
    for word in ("buy", "sell", "hot", "recommend", "target", "avoid"):
        assert word not in text


def test_thresholds_are_read_from_the_owner_config():
    rules = json.loads((ROOT / "config" / "screening_thresholds.json").read_text(encoding="utf-8"))["rules"]
    assert {r["id"] for r in rules} == {"low_pe", "high_net_margin", "strong_roe", "positive_growth",
                                        "comfortable_liquidity"}
    assert {r["id"]: r["threshold"] for r in rules}["low_pe"] == 10


# ------------------------------------------------------------------ not yet collected: never a fake number

def test_a_signal_whose_metric_is_not_stored_says_not_yet_collected():
    s = {r["id"]: r for r in ci.screening_signals([m("P/E Annual", 5.4)], RULES)}
    assert s["high_net_margin"]["status"] == ci.NOT_COLLECTED
    assert s["high_net_margin"]["met"] is None and s["high_net_margin"]["observed"] is None


def test_groups_follow_the_source_and_keep_unknown_labels_under_other():
    assert ci.group_for("Annual EPS") == "EPS" and ci.group_for("P/E Annual") == "P/E"
    assert ci.group_for("Forward PEG") == "Growth" and ci.group_for("Price / Book") == "Book & Market Value"
    assert ci.group_for("Net Margin") == "Profitability" and ci.group_for("Quick Ratio") == "Financial Health"
    assert ci.group_for("Something new") == "Other"


# ------------------------------------------- a local database from the synthetic fixtures

def _store(db, endpoint, symbol, fields, fetched="2026-11-12T09:00:00Z", source="investify.pk"):
    fund.store_structured(db, endpoint=endpoint, symbol=symbol, fields=fields,
                          url=f"https://www.investify.pk/company/{symbol}/{endpoint}", fetched_at_utc=fetched,
                          http_status=200)
    if source != "investify.pk":  # the attribution test stores a record that is not Investify's
        db.execute("UPDATE source_items SET source_metadata_json = ? WHERE external_id = ?",
                   (json.dumps({"source": "other", "fields": fields}), f"{symbol}:{endpoint}"))


@pytest.fixture
def local_db(tmp_path):
    path = tmp_path / "local.sqlite"
    db = SQLiteDatabase(str(path))
    migrate(db)
    seed_loader.load(db)
    # the synthetic index is keyed to HUBC, so the profile is parsed under that key and stored for TST
    _store(db, "profile", "TST", x.parse_profile((FIX / "profile_synthetic.html").read_bytes(), "HUBC"))
    fundamentals = x.parse_fundamentals((FIX / "fundamentals_synthetic.html").read_bytes(), "TST")
    _store(db, "fundamentals", "TST", fundamentals)
    competitors = x.parse_competitors((FIX / "competitors_synthetic.html").read_bytes(), "TST")
    _store(db, "competitors", "TST", competitors)
    _store(db, "announcements", "TST",
           x.parse_announcements((FIX / "announcements_synthetic.html").read_bytes(), "TST"))
    db.close()
    return path


def test_company_view_reads_only_the_stored_datasets(local_db):
    data = ci.load_company(_open(local_db), "TST")
    assert set(data) == set(ci.DATASETS)
    assert data["fundamentals"]["fields"]["metric_count"] == 4
    assert data["profile"]["fields"]["sector"] == "Power Generation & Distribution"
    assert data["fundamentals"]["attribution"] == "Source: Investify (investify.pk)"  # as stored


def test_a_company_without_a_dataset_gets_none_for_it(local_db):
    data = ci.load_company(_open(local_db), "NONE")
    assert all(v is None for v in data.values())


def test_a_record_not_attributed_to_investify_is_never_shown(tmp_path):
    path = tmp_path / "other.sqlite"
    db = SQLiteDatabase(str(path))
    migrate(db)
    seed_loader.load(db)
    _store(db, "profile", "ZZZ", {"sector": "X"}, source="someone-else")
    db.close()
    assert ci.load_company(_open(path), "ZZZ")["profile"] is None


def test_the_company_view_refuses_any_statement_that_is_not_a_select(local_db):
    db = _open(local_db)
    with pytest.raises(ValueError):
        ci._select(db, "DELETE FROM source_items")
    with pytest.raises(ValueError):
        ci._select(db, "UPDATE source_items SET source_id = 'x'")
    before = db.execute("SELECT COUNT(*) AS n FROM source_items")[0]["n"]
    ci.load_company(db, "TST")  # reads only
    assert db.execute("SELECT COUNT(*) AS n FROM source_items")[0]["n"] == before


# ------------------------------------------------------------------ the page, through the main app

def _open(path):
    from database.connection import SQLiteDatabase

    return SQLiteDatabase(str(path))


def _app(monkeypatch, url: str | None):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_resource.clear()  # the app caches its database handle; each test uses its own file
    if url is None:
        monkeypatch.delenv("PSXNI_TURSO_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", url)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def _company_page(at):
    at.sidebar.radio[0].set_value("Company intelligence").run()
    return at


def test_the_company_page_shows_attribution_and_not_yet_collected(local_db, monkeypatch):
    at = _company_page(_app(monkeypatch, f"sqlite:///{local_db}"))
    assert not at.exception
    assert ci.ATTRIBUTION in " ".join(w.value for w in at.warning)
    cells = [str(c) for t in at.table for row in t.value.values.tolist() for c in row]
    assert ci.NOT_COLLECTED in cells  # no P/E Annual or Net Margin in the fixture: never a number
    assert "5.4" not in " ".join(cells)  # and no P/E was invented


def test_the_company_picker_lists_stored_symbols(local_db, monkeypatch):
    at = _company_page(_app(monkeypatch, f"sqlite:///{local_db}"))
    assert at.selectbox[0].options == ["TST"]


def test_overview_still_renders_and_the_company_page_says_when_no_database(monkeypatch):
    at = _app(monkeypatch, None)
    assert not at.exception
    assert at.title[0].value == "PSX Fundamental & News Intelligence"  # overview untouched
    at = _company_page(at)
    assert not at.exception
    assert any("No database is configured" in i.value for i in at.info)


def test_navigation_switches_between_the_pages_without_errors(local_db, monkeypatch):
    at = _app(monkeypatch, f"sqlite:///{local_db}")
    assert at.title[0].value == "PSX Fundamental & News Intelligence"
    at = _company_page(at)
    assert not at.exception and at.title[0].value == "Company intelligence"
    at.sidebar.radio[0].set_value("Overview").run()
    assert not at.exception and at.title[0].value == "PSX Fundamental & News Intelligence"
