"""Announcements in the tick: one sourced, dated row each; no Investify judgement labels. No network."""

from __future__ import annotations

import json
from pathlib import Path

from engines import autonomous_tick as at
from engines import investify_extract as x
from engines import research_facts as rf

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "investify" / "announcements_synthetic.html"
URL = "https://www.investify.pk/company/FCL/announcements"


def _rows():
    fields = x.parse_announcements(FIX.read_bytes(), "FCL")
    return rf.rows_from_fields(company="FCL", endpoint="announcements", fields=fields, url=URL,
                               fetched_at_utc="2026-11-16T05:00:00Z")


def test_each_announcement_becomes_one_sourced_dated_row():
    rows = _rows()
    assert len(rows) == 2
    first = rows[0]
    assert first["topic"] == "announcements.Financials"
    assert first["fact_text"] == "2026-10-20: Financial Result For The Quarter Ended Synthetic 30, 2026"
    assert first["as_of"] == "2026-10-20" and first["source_date"] == "2026-11-16"
    assert first["source_url"] == "https://dps.psx.com.pk/download/document/900001.pdf"
    assert rows[1]["topic"] == "announcements.Meetings" and rows[1]["source_url"] == URL  # no PDF: page URL


def test_investify_materiality_and_sentiment_labels_are_not_stored():
    text = json.dumps(_rows())
    assert "positive" not in text and "neutral" not in text and "high" not in text


def test_the_tick_fetches_announcements_second_for_every_company():
    watchlist = json.loads((ROOT / "config" / "coverage_watchlist.json").read_text())
    symbols = [c["symbol"] for c in watchlist["companies"]]
    resources = at.resources_for(symbols)
    assert len(resources) == 108 * 4
    endpoints = [ep for _, ep in resources]
    assert endpoints[:108] == ["fundamentals"] * 108 and endpoints[108:216] == ["announcements"] * 108
