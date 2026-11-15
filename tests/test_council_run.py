"""The council runner: evidence routing from the brain, and verdict storage. Offline, no network."""

from __future__ import annotations

import json
from pathlib import Path

from database.connection import SQLiteDatabase
from engines import analyst_council as council
from engines import llm
from scripts import apply_library_migration as mig
from scripts import council_run

ROOT = Path(__file__).resolve().parents[1]
INSERT = ("INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name,"
          " source_url, source_date, as_of, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)")
FACTS = [("report.net_revenue", "OGDC revenue PKR 400bn FY26"),
         ("macro.sbp_rate_impact", "Rate cuts lift cyclicals"),
         ("valuation.ev_per_ton", "Cement fair value $45-70 a ton"),
         ("announcements.Other", "OGDC notified a board meeting"),
         ("unmapped.topic", "this must not reach any lens")]


def _db() -> SQLiteDatabase:
    db = SQLiteDatabase()
    for stmt in mig.statements((ROOT / "database" / "library" / "0002_research_fact.sql")
                               .read_text(encoding="utf-8")):
        db.execute(stmt)
    for topic, text in FACTS:
        db.execute(INSERT, ("OGDC", topic, text, None, None, "FY26", "Test source", None,
                            "2026-09-12", "2026-06-30", "fact", "2026-11-14T00:00:00Z"))
    return db


def test_each_stored_topic_reaches_only_the_lens_that_should_weigh_it():
    pack = council_run.build_pack("Oil spikes.", ["OGDC"], _db())
    assert "PKR 400bn" in pack.for_role("financial")
    assert "PKR 400bn" not in pack.for_role("macro")
    assert "Rate cuts lift cyclicals" in pack.for_role("macro")
    assert "fair value" in pack.for_role("macro")  # a learned sector rule is macro's to apply
    assert "board meeting" in pack.for_role("news")


def test_a_topic_with_no_routing_rule_is_shown_to_nobody():
    pack = council_run.build_pack("Oil spikes.", ["OGDC"], _db())
    assert all("must not reach" not in pack.for_role(role) for role in council.ROLES)
    assert council_run.kind_for("unmapped.topic") is None


def test_the_event_text_is_always_in_the_pack_even_with_no_stored_knowledge():
    pack = council_run.build_pack("Oil spikes.", [], _db())
    assert "Oil spikes." in pack.for_role("news")


def _gateway(answer: str):
    return lambda role: llm.LLMGateway(provider=llm.FixtureProvider({"<event>": answer}),
                                       pricing=llm.Pricing(0, 0))


def test_a_dry_run_stores_nothing_and_storing_keeps_one_row_with_its_provenance():
    db = _db()
    answer = json.dumps({"assessments": [{"company": "OGDC", "direction": "benefit",
                                          "magnitude": "high", "timing": "immediate",
                                          "reason": "r", "evidence_ids": ["n1"],
                                          "confidence": "high"}], "unresolved": []})
    assert council_run.run("Oil spikes.", ["OGDC"], store=False, db=db,
                           gateway_for=_gateway(answer)) == 0
    tables = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "council_verdict" not in tables

    assert council_run.run("Oil spikes.", ["OGDC"], store=True, db=db,
                           gateway_for=_gateway(answer)) == 0
    rows = db.execute("SELECT event, lenses_answered, conflict_count, verdict_json FROM council_verdict")
    assert len(rows) == 1 and rows[0]["lenses_answered"] == "news,financial,macro"
    stored = json.loads(rows[0]["verdict_json"])
    assert stored["findings"][0]["prompt_version"] == "1.0.0"


def test_the_runner_refuses_cleanly_when_no_lens_can_answer():
    """Exit 3, no traceback, and nothing stored: an unusable model run must not look like success."""
    db = _db()
    assert council_run.run("Oil spikes.", ["OGDC"], store=True, db=db,
                           gateway_for=_gateway("not json at all")) == 3
    tables = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "council_verdict" not in tables


# ---------- the macro lens needs its sector knowledge or its work is all discarded

def _db_with_sector() -> SQLiteDatabase:
    db = _db()
    db.execute(INSERT, ("LUCK", "profile.cement.status", "Lucky is the largest cement producer",
                        None, None, None, "Capsule", None, "2026-11-01", "2026-11-01",
                        "analyst_view", "2026-11-14T00:00:00Z"))
    db.execute(INSERT, ("SECTOR:CEMENT", "macro.pkr_usd_impact", "A weaker rupee lifts coal costs",
                        None, None, None, "Capsule", None, "2026-11-01", "2026-11-01",
                        "analyst_view", "2026-11-14T00:00:00Z"))
    return db


def test_a_companys_sector_knowledge_is_pulled_in_so_the_macro_lens_has_something_to_cite():
    db = _db_with_sector()
    assert council_run.sectors_for(["LUCK"], db) == ["SECTOR:CEMENT"]
    pack = council_run.build_pack("Rupee weakens.", ["LUCK"], db)
    assert "weaker rupee lifts coal costs" in pack.for_role("macro")


def test_a_sector_name_hidden_inside_a_longer_word_does_not_drag_the_sector_in():
    """"announcements" contains "cement": a substring test would give every filer cement knowledge."""
    db = _db_with_sector()
    assert any("announcements" in r["topic"]
               for r in db.execute("SELECT topic FROM research_fact WHERE company = 'OGDC'"))
    assert council_run.sectors_for(["OGDC"], db) == []


def test_a_sector_can_be_asked_for_explicitly():
    db = _db_with_sector()
    assert council_run.sectors_for(["OGDC"], db, ["cement"]) == ["SECTOR:CEMENT"]


# ---------- every topic family we ingest must actually reach a lens

def test_company_commentary_reaches_the_financial_lens():
    """commentary.* routed nowhere once, so a whole archive of company analysis was invisible."""
    for topic in ("commentary.thesis", "commentary.risk", "risk.leverage", "thesis.core",
                  "catalyst.expansion", "method.oil_gas_valuation", "profile.business"):
        assert council_run.kind_for(topic) == "note", topic


def test_sector_and_macro_families_still_route_to_the_macro_lens():
    for topic in ("cost.energy_share", "cycle.utilisation", "capacity.installed",
                  "operations.kiln", "valuation.ev_per_ton", "strategy.pairing",
                  "signal.rate_cut", "returns.20yr"):
        assert council_run.kind_for(topic) == "sector_rule", topic
    assert council_run.kind_for("macro.rate_cut_transmission") == "macro"


def test_a_topic_family_nobody_routes_is_still_shown_to_nobody():
    assert council_run.kind_for("random.unmapped") is None


def test_macro_backdrop_is_included_and_newest_dated_facts_come_first():
    db = _db()
    for name in ("0005_video_source.sql", "0006_video_dating.sql"):
        for stmt in mig.statements((ROOT / "database" / "library" / name).read_text(encoding="utf-8")):
            db.execute(stmt)
    db.execute(INSERT, ("MACRO:PAKISTAN", "macro.policy_rate", "Policy rate backdrop", None, None, "", "ARN",
                        "u-old", "2026-11-14", "", "analyst_view", "2026-11-14T00:00:00Z"))
    db.execute(INSERT, ("MACRO:PAKISTAN", "macro.policy_rate", "Newer rate view", None, None, "", "ARN",
                        "u-new", "2026-11-14", "", "analyst_view", "2026-11-14T00:00:00Z"))
    for vid, url, day in (("old", "u-old", "2024-06-01"), ("new", "u-new", "2026-10-01")):
        db.execute("INSERT INTO video_source (video_id, title, channel, archive_position, url, "
                   "speaker_may_differ, status) VALUES (?,?,?,?,?,?,?)",
                   (vid, "t", "c", 0, url, 0, "extracted"))
        db.execute("INSERT INTO video_dating (video_id, date_from, date_to, basis, note) VALUES (?,?,?,?,?)",
                   (vid, day, day, "verified", ""))
    pack = council_run.build_pack("Rates move.", ["OGDC"], db)
    macro = [i for i in pack.items if i.company == "MACRO:PAKISTAN"]
    assert [i.source_date for i in macro] == ["2026-10-01 [current]", "2024-06-01 [old]"]


def test_freshness_bands_and_factor_tags():
    from datetime import date

    from engines import freshness

    today = date(2026, 11, 15)
    assert freshness.label("2026-10-01", today) == "current"
    assert freshness.label("2026-01-01", today) == "recent"
    assert freshness.label("2025-03-01", today) == "dated"
    assert freshness.label("2024-06-01", today) == "old"
    assert freshness.label("", today) == "undated"
    tags = freshness.factors_in("SBP cuts the policy rate; rupee steady")
    assert tags == {"interest_rate", "exchange_rate"}


def test_event_factor_ranks_matching_facts_first_and_a_brief_is_added():
    pack = council_run.build_pack("SBP cut the policy rate.", ["OGDC"], _db(), limit_per_company=2)
    texts = [i.text for i in pack.items if i.company == "OGDC"]
    assert any("Rate cuts" in t for t in texts)
    assert any("stored fact(s)" in t for t in texts)


def test_brief_warns_when_knowledge_comes_from_one_source():
    pack = council_run.build_pack("Oil spikes.", ["OGDC"], _db())
    brief = next(i.text for i in pack.items if "stored fact(s)" in i.text)
    assert "1 distinct source" in brief and "Single-source" in brief


def test_stored_links_reach_the_macro_lens_with_their_date():
    db = _db()
    for name in ("0005_video_source.sql", "0006_video_dating.sql", "0007_company_link.sql"):
        for stmt in mig.statements((ROOT / "database" / "library" / name).read_text(encoding="utf-8")):
            db.execute(stmt)
    db.execute("INSERT INTO company_link (driver, affected, direction, fact_id, quote, created_at) "
               "VALUES ('policy rate', 'OGDC', 'up', 2, 'Rate cuts lift cyclicals', 'x')")
    pack = council_run.build_pack("SBP cut the policy rate.", ["OGDC"], db)
    assert "policy rate affects OGDC (up)" in pack.for_role("macro")


def test_brief_flags_a_delisted_ticker():
    db = _db()
    db.execute(INSERT, ("PSMC", "profile.x", "Pak Suzuki assembled cars", None, None, "", "Test", None,
                        "2026-09-12", "", "fact", "2026-11-14T00:00:00Z"))
    pack = council_run.build_pack("Autos news.", ["PSMC"], db)
    assert "DELISTED on PSX" in next(i.text for i in pack.items if "stored fact(s)" in i.text)
