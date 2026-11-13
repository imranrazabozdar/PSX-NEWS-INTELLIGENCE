"""The Investify consent scope: exactly the approved ten; nothing enabled without consent. No network."""

from __future__ import annotations

import json
from pathlib import Path

from collectors import investify_good_citizen as gc

ROOT = Path(__file__).resolve().parents[1]
CONSENT = ROOT / "config" / "investify_consent.json"
POLICY = ROOT / "config" / "investify_good_citizen.json"
FLAGS = ROOT / "config" / "investify_flags.json"
APPROVED = {"Announcements", "Fundamentals", "Profile", "Competitors",
            "Market & Index", "Sectors", "Technicals", "News", "Sentiment", "Rates & Commodities"}


def _consent() -> dict:
    return json.loads(CONSENT.read_text(encoding="utf-8"))


def test_the_consent_record_lists_exactly_the_approved_ten_and_nothing_more():
    assert set(_consent()["categories"]) == APPROVED
    assert len(_consent()["categories"]) == 10


def test_the_consent_record_names_its_source_and_conditions_and_leaves_the_date_for_the_owner():
    data = _consent()
    assert data["source"] == "Investify expanded-scope approval email"
    assert data["approval_date"] == "[APPROVAL DATE]"  # the owner supplies it; not invented here
    joined = " ".join(data["conditions"])
    assert "Private, non-commercial" in joined and "Source: Investify (investify.pk)" in joined
    assert "Revocable" in joined and "one request per 15 minutes" in joined


def test_no_collector_is_enabled_without_a_matching_consent_entry():
    flags = json.loads(POLICY.read_text(encoding="utf-8"))["collectors_enabled"]
    enabled = {k for k, v in flags.items() if v}
    consented_collectors = {c["collector"] for c in _consent()["categories"].values() if c["collector"]}
    assert enabled <= consented_collectors
    assert set(gc.COLLECTORS) <= consented_collectors | {"robots"}


def test_enablement_is_still_off_for_every_category():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert not any(policy["collectors_enabled"].values())
    assert json.loads(FLAGS.read_text(encoding="utf-8"))["news_enabled"] is False


def test_the_five_categories_without_a_collector_have_no_fetch_path():
    no_collector = {k for k, v in _consent()["categories"].items() if v["collector"] is None}
    assert no_collector == {"Market & Index", "Sectors", "Technicals", "Sentiment", "Rates & Commodities"}
    text = (ROOT / "collectors" / "investify_good_citizen.py").read_text(encoding="utf-8")
    assert not any(name.lower().replace(" ", "_") in text.lower() for name in ("market_index", "sentiment"))
