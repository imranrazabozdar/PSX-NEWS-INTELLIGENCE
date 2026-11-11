"""Investify announcement collector: parser, watchlist filter, classifier, dedup, provenance, registration.

Runs entirely against a POINT-IN-TIME fixture captured on 2026-11-11 (not live data). No network is used: the
socket layer is disabled for every test in this module.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path

import pytest

from engines import investify_collector as ic

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "investify" / "announcements_point_in_time_2026-11-11.html"
RETRIEVED = "2026-11-11T12:00:00Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the collector must not open a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _page() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _all_symbols() -> frozenset[str]:
    return frozenset(re.findall(r'href="/announcements/([A-Z0-9&-]+)/', _page()))


# ------------------------------------------------------------------ fixture is marked point-in-time

def test_fixture_is_marked_point_in_time_and_is_not_the_live_page():
    head = _page()[:600]
    assert "POINT-IN-TIME FIXTURE" in head and "Not live data" in head
    assert "2026-11-11" in head and "Original body SHA-256:" in head


# ------------------------------------------------------------------ parser

def test_parser_reads_every_card_with_no_problems():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    assert res.parse_problems == ()
    assert len(res.records) == 25
    assert len({r.symbol for r in res.records}) == 25


def test_fields_are_extracted_from_the_card_not_the_summary():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    pso = next(r for r in res.records if r.symbol == "PSO")
    assert pso.title == "PSO credits final cash dividend of Rs. 10 per share"
    assert pso.company_name == "Pakistan State Oil Company Ltd"  # read from the card's title attribute
    assert pso.investify_label == "Dividend" and pso.sentiment_label == "Positive"
    assert pso.source_url == "https://www.investify.pk/announcements/PSO/dps-pdf-289031"
    assert pso.pdf_url == "https://dps.psx.com.pk/download/document/289031.pdf"


def test_dates_come_from_the_time_element_in_utc_and_are_reported_in_pakistan_time():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    rec = next(r for r in res.records if r.symbol == "PSO")
    assert rec.announced_at_utc == "2026-11-11T10:21:00Z"
    assert rec.announced_on_pkt == "2026-11-11"
    assert all(r.announced_on_pkt == "2026-11-11" for r in res.records)


def test_an_announcement_with_no_psx_pdf_is_kept_with_no_pdf_flag():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    image_only = next(r for r in res.records if r.source_url.endswith("dps-image-289028-1"))
    assert image_only.pdf_url is None and image_only.pdf_access == "none"


def test_pdf_access_is_gated_when_the_pdf_is_on_the_psx_host():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    gated = [r for r in res.records if r.pdf_access == "gated_dps"]
    assert len(gated) == 24
    assert all(r.pdf_url.startswith("https://dps.psx.com.pk/download/") for r in gated)


def test_the_summary_paragraph_is_not_stored():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    fields = " ".join(str(v) for r in res.records for v in vars(r).values())
    assert "are not assessed" not in fields and "has published the Fund Manager" not in fields


# ------------------------------------------------------------------ watchlist filter

def test_only_watchlist_symbols_are_kept_using_the_real_watchlist():
    res = ic.collect(_page(), watchlist=ic.load_watchlist_symbols(), retrieved_at_utc=RETRIEVED)
    assert sorted(r.symbol for r in res.records) == ["FCL", "PSO", "STL", "THCCL", "TOMCL"]
    assert res.skipped_off_watchlist == 20 and res.skipped_duplicates == 0


def test_watchlist_loads_the_108_company_list():
    syms = ic.load_watchlist_symbols()
    assert len(syms) == 108 and "PSO" in syms and "ICIBL" not in syms


# ------------------------------------------------------------------ classifier

EXPECTED_CATEGORY = {
    "ASIC": "bonus_right",  # "announces a 36.97% right issue"
    "UVIC": "bonus_right",  # "book closure for a 100% rights issue"
    "EFUL": "bonus_right",  # "full subscription of 45 million right shares"
    "PSO": "dividend",
    "UDLI": "dividend",
    "SITC": "dividend",
    "ICIBL": "directors_dealing",  # "director reports purchase of 350 shares"
    "MWMP": "board_meeting",
    "THCCL": "merger_acquisition",  # Investify label "Scheme / Arrangement"
    "GLOT": "financial_results",  # "reports a net loss for the period ended"
    "JSMFETF": "fund_report",
    "AGIL": "corporate_briefing",
    "IPAK": "corporate_briefing",
    "FCL": "other",  # annual progress report on IPO proceeds: no keyword match, kept as other
    "PSYL": "other",
}


def test_each_fixture_title_is_classified_as_expected():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    got = {r.symbol: r.category for r in res.records}
    for symbol, expected in EXPECTED_CATEGORY.items():
        assert got[symbol] == expected, symbol


@pytest.mark.parametrize("title,label,expected", [
    ("Company X to hold board meeting on 20 November", "", "board_meeting"),
    ("Material information: sale of subsidiary", "", "material_information"),
    ("Bank announces merger with another bank", "", "merger_acquisition"),
    ("Chief Executive resigns", "", "management_change"),
    ("Net profit for the quarter ended September 30", "", "financial_results"),
    ("Some company update", "Insider Buy", "directors_dealing"),
    ("Some company update", "", "other"),
])
def test_keyword_rules(title, label, expected):
    assert ic.classify(title, label) == expected


def test_material_categories_are_a_subset_of_all_categories():
    assert ic.MATERIAL_CATEGORIES <= set(ic.CATEGORIES)


def test_category_filter_restricts_output():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED, categories={"dividend"})
    assert sorted(r.symbol for r in res.records) == ["PSO", "SITC", "UDLI"]


# ------------------------------------------------------------------ dedup

def test_duplicate_cards_are_collapsed_on_symbol_date_and_title():
    doubled = _page() + _page().split("<main>", 1)[1]  # every card appears twice
    res = ic.collect(doubled, watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    assert len(res.records) == 25 and res.skipped_duplicates == 25


def test_content_hash_is_stable_and_changes_with_the_title():
    a = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    b = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc="2030-01-01T00:00:00Z")
    assert [r.content_sha256 for r in a.records] == [r.content_sha256 for r in b.records]
    assert len({r.content_sha256 for r in a.records}) == 25


# ------------------------------------------------------------------ provenance

def test_every_record_carries_provenance():
    res = ic.collect(_page(), watchlist=_all_symbols(), retrieved_at_utc=RETRIEVED)
    for r in res.records:
        assert r.source == "investify"
        assert r.source_url.startswith("https://www.investify.pk/announcements/")
        assert r.retrieved_at_utc == RETRIEVED
        assert r.pdf_access in {"gated_dps", "downloadable", "none"}
        assert len(r.content_sha256) == 64


# ------------------------------------------------------------------ registration (disabled by default)

def _entry() -> dict:
    data = json.loads((ROOT / "database" / "seed" / "sources.json").read_text(encoding="utf-8"))
    return next(s for s in data["sources"] if s["source_id"] == "investify_announcements")


def test_the_source_is_registered_disabled_and_not_active():
    e = _entry()
    assert e["enabled"] == 0
    assert e["lifecycle_status"] == "RESTRICTED" and e["lifecycle_status"] != "ACTIVE"
    assert e["terms_status"] == "prohibits_automation"
    assert e["access_method"] == "not_permitted"
    assert e["retention_mode"] == "metadata_only"
    assert e["feed_url"] is None and e["adapter"] is None  # no live endpoint is wired up


def test_the_registry_still_validates():
    from database.validation import validate_source_registry

    data = json.loads((ROOT / "database" / "seed" / "sources.json").read_text(encoding="utf-8"))
    assert validate_source_registry(data) == []
