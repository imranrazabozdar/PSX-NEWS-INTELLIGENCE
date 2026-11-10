"""Relevance pre-filter tests (ported under ADR-0001's owner-approved exception). Synthetic headlines
and the company master only: no network, no model."""

from __future__ import annotations

import pytest

from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines.relevance_prefilter import RelevancePrefilter, company_phrase, load_rules


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def test_rules_file_is_versioned_and_complete():
    rules = load_rules()
    assert rules["version"].startswith("relevance@")
    assert rules["threshold"] >= 1
    expected = {"corporate", "regulatory", "markets", "commodities", "geo", "foreign_noise"}
    assert set(rules["groups"]) >= expected


def test_company_phrase_strips_suffixes_and_drops_ambiguous_short_names():
    assert company_phrase("The Hub Power Company Limited") == "hub power"
    assert company_phrase("Engro Limited") is None          # one word: too ambiguous
    assert company_phrase("PSO") is None


def test_ticker_and_corporate_keyword_pass(db):
    pf = RelevancePrefilter.from_db(db)
    result = pf.score("OGDC announces final dividend of Rs 5 per share")
    assert result["pass"] is True
    assert any(r.startswith("ticker:OGDC") for r in result["reasons"])
    assert any(r.startswith("corporate:") for r in result["reasons"])


def test_company_name_match_is_a_whole_phrase(db):
    pf = RelevancePrefilter.from_db(db)
    assert pf.score("Hub Power board meeting called to consider quarterly results")["pass"] is True
    assert pf.score("hubpower is a made-up word")["pass"] is False


def test_ambiguous_ticker_needs_corroboration():
    pf = RelevancePrefilter(tickers={"PPP"}, rules=load_rules())
    alone = pf.score("PPP party rallies in Lahore today")
    assert alone["pass"] is False
    assert any("ignored: no corroboration" in r for r in alone["reasons"])
    corroborated = pf.score("PPP announces final dividend for shareholders")
    assert corroborated["pass"] is True


def test_context_only_signals_never_pass_alone():
    pf = RelevancePrefilter(rules=load_rules())
    result = pf.score("Pakistan and Karachi weather report for the week")
    assert result["pass"] is False and result["score"] == 0
    assert "no substantive signal: context-only" in result["reasons"]


def test_foreign_noise_penalises_otherwise_matching_text():
    rules = load_rules()
    pf = RelevancePrefilter(tickers={"OGDC"}, rules=rules)
    noisy = pf.score("OGDC dividend declared as the indian rupee weakens")
    penalty = rules["groups"]["foreign_noise"]["indian rupee"]
    assert penalty < 0
    assert f"foreign_noise:indian rupee({penalty})" in noisy["reasons"]
    assert "markets:rupee(2)" in noisy["reasons"]                 # the market term still counts
    # ticker 4 + corporate dividend 3 + markets rupee 2 + the penalty, counted exactly once
    assert noisy["score"] == 4 + 3 + 2 + penalty


def test_pbs_source_bonus_counts_as_substantive():
    pf = RelevancePrefilter(rules=load_rules())
    result = pf.score("Monthly statistics bulletin released", source_id="pbs")
    assert result["pass"] is True
    assert "source:pbs(+3)" in result["reasons"]


def test_watchlist_adds_bonus_and_tickers_do_not_stack(db):
    pf = RelevancePrefilter(tickers={"OGDC", "PSO"}, watchlist={"OGDC"}, rules=load_rules())
    result = pf.score("OGDC and PSO both announce dividends")
    assert "watchlist:OGDC" in result["reasons"]
    assert sum(1 for r in result["reasons"] if r.startswith("ticker:")) == 1


def test_result_records_version_and_reasons_for_audit():
    pf = RelevancePrefilter(tickers={"OGDC"}, rules=load_rules())
    result = pf.score("OGDC final dividend")
    assert result["version"] == load_rules()["version"]
    assert result["reasons"]
