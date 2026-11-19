"""Regression benchmark for the council's candidate rules: recall on material events, exclusions for routine
pages and global wires, and the documented known gaps. Uses the real name files; no database, no model."""

import json
from pathlib import Path

import pytest

from engines import news_facts as nf
from engines import news_importance as ni

ROOT = Path(__file__).resolve().parents[1]
BENCH = json.loads((ROOT / "tests/fixtures/council/material_event_benchmark.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def vocab():
    listing = json.loads((ROOT / "docs/research/psx_listed_companies.json").read_text("utf-8"))
    aliases = json.loads((ROOT / "docs/research/arn/entity_aliases.json").read_text("utf-8"))["aliases"]
    return nf.build_vocabulary(dict(listing["companies"]), aliases, [])


def flags(vocab, title, source="profit"):
    h = ni.Headline(source, "u", title, "2026-11-18T05:00:00Z")
    hits, companies, _ = ni.headline_hits(vocab, h)
    return hits, companies


def test_every_material_benchmark_event_is_flagged_and_mapped(vocab):
    missed = []
    for item in BENCH["should_flag"]:
        hits, companies = flags(vocab, item["title"])
        if not hits or not set(item["companies"]) <= set(companies):
            missed.append((item["title"][:70], [h.rule for h in hits], companies))
    assert not missed, f"recall below 100% on the benchmark: {missed}"


def test_routine_pages_global_wires_and_procedural_notices_are_not_flagged(vocab):
    noisy = [
        (t[:60], src, [h.rule for h in flags(vocab, t, src)[0]])
        for key, sources in (
            ("should_not_flag_wires", ("brecorder",)),
            ("should_not_flag_routine", ("profit", "dawn_business")),
        )
        for t in BENCH[key]
        for src in sources
        if flags(vocab, t, src)[0]
    ]
    assert not noisy, f"false positives on the benchmark: {noisy}"


def test_known_gaps_stay_listed_with_a_reason_and_are_not_silently_claimed_as_caught(vocab):
    for item in BENCH["known_gap"]:
        assert item["reason"]
    # The Gatron story needs an owner-confirmed one-word alias; until then it must not be mapped by guess.
    gatron = next(i for i in BENCH["known_gap"] if "Gatron" in i["title"])
    assert flags(vocab, gatron["title"])[1] == []


def test_corporate_action_hits_record_the_stage_and_have_a_weight_below_adverse_developments(vocab):
    proposed, _ = flags(vocab, "Nimir Resins: IGI Investments to evaluate proposed 60pc stake acquisition")
    done, _ = flags(
        vocab, "Mobilink Microfinance Bank signs deal to acquire 82.51% stake in Apna Microfinance Bank"
    )
    assert "proposed or reported" in proposed[0].detail and "announced or done" in done[0].detail
    assert ni.RULE_WEIGHT[7] > ni.RULE_WEIGHT[9] > ni.RULE_WEIGHT[2]


def test_the_same_article_stored_under_two_url_forms_is_one_event_member(vocab):
    title = "Govt to support HBL in expanding trade links with four countries"
    heads = [
        ni.Headline("brecorder", f"https://b/{i}?utm={i}", title, f"2026-11-18T0{i}:00:00Z")
        for i in range(1, 5)
    ] + [ni.Headline("dawn_business", "https://d/1", title, "2026-11-18T06:00:00Z")]
    events = ni.cluster(heads, (), vocab)
    assert len(events) == 1
    assert len(events[0].members) == 2  # one Business Recorder copy and the Dawn article
