"""Deterministic news tagging and the activated source registry (offline; company master from the seed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load, validate_all
from engines.news_tagging import NewsTagger

ROOT = Path(__file__).resolve().parents[1]
REG = {s["source_id"]: s for s in json.loads((ROOT / "database/seed/sources.json").read_text())["sources"]}


@pytest.fixture(scope="module")
def tagger():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    yield NewsTagger(d)
    d.close()


def test_capital_ticker_resolves_with_sector_and_evidence(tagger):
    t = tagger.tag("OGDC posts higher quarterly profit", as_of="2026-11-06")
    assert [c["ticker"] for c in t.companies] == ["OGDC"]
    assert t.companies[0]["evidence"] == "ticker 'OGDC'" and t.companies[0]["sector"]


def test_exact_name_resolves_but_is_flagged_for_review(tagger):
    t = tagger.tag("Bank Alfalah quits Kabul after 20 years", as_of="2026-11-06")
    assert [c["ticker"] for c in t.companies] == ["BAFL"]
    assert t.companies[0]["needs_review"] is True and "bank alfalah" in t.companies[0]["evidence"]


def test_lowercase_words_and_partial_names_are_never_assigned(tagger):
    assert tagger.tag("Good luck to the systems team", as_of="2026-11-06").companies == []
    assert tagger.tag("Engro announces expansion", as_of="2026-11-06").companies == []


def test_themes_and_market_moving_flags_carry_evidence(tagger):
    t = tagger.tag("SBP keeps policy rate unchanged as inflation eases; IMF review next week")
    themes = {x["theme"]: x["evidence"] for x in t.themes}
    assert "policy rate" in themes["monetary_policy"] and "imf" in themes["fiscal_and_tax"]
    assert t.potentially_market_moving and "policy rate" in t.market_moving
    assert tagger.tag("Weather to stay pleasant in Lahore").themes == []


def test_registry_is_valid_and_activation_matches_the_owner_decision():
    assert validate_all() == []
    active = {sid for sid, s in REG.items() if s["lifecycle_status"] == "ACTIVE"}
    assert {"dawn", "brecorder", "tribune", "pbs", "scs_chart"} <= active
    for sid in active:
        s = REG[sid]
        assert s["terms_status"] == "approved" and s["access_status"] == "verified_permitted"
        assert "OWNER DECISION 2026-11-08" in s["review_notes"]
        if s["adapter"] == "rss":
            assert s["retention_mode"] == "metadata_only"
    assert REG["scs_chart"]["access_method"] == "authorised_provider"
    assert REG["thenews"]["lifecycle_status"] != "ACTIVE"  # stale feed is not activated
    assert REG["eia"]["lifecycle_status"] == "RESTRICTED"  # restricted sources unchanged
