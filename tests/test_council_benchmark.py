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
    alias_file = json.loads((ROOT / "docs/research/arn/entity_aliases.json").read_text("utf-8"))
    ctx = {k: v for k, v in alias_file["contextual_aliases"].items() if not k.startswith("_")}
    return nf.build_vocabulary(dict(listing["companies"]), alias_file["aliases"], [], ctx)


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


def test_known_gaps_stay_listed_with_a_reason(vocab):
    for item in BENCH["known_gap"]:
        assert item["reason"]


def test_a_bare_gatron_is_the_listed_company_only_with_a_corporate_context_word(vocab):
    event = "Gatron\u2019s \u2018merger\u2019 moves a third of the company out of two holding companies"
    assert flags(vocab, event)[1] == ["GATI"]
    assert flags(vocab, "Gatron announces share transfer book closure for scheme of arrangement")[1] == [
        "GATI"
    ]
    assert flags(vocab, "Gatron Industries posts quarterly profit")[1] == ["GATI"]
    # a mention with no tie to the listed company's own corporate events is not mapped by guess
    assert flags(vocab, "A Gatron truck overturned near Gadap")[1] == []
    assert flags(vocab, "Gatron wins a cricket tournament sponsorship")[1] == []


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


EXT = json.loads((ROOT / "tests/fixtures/council/benchmark_extended.json").read_text("utf-8"))
HOLD = json.loads((ROOT / "tests/fixtures/council/benchmark_holdout.json").read_text("utf-8"))


def test_extended_cases_company_events_are_flagged_by_rule_9_and_company_chatter_is_not(vocab):
    missed = [
        i["title"][:60]
        for i in EXT["should_flag"]
        if not any(h.rule == 9 for h in flags(vocab, i["title"])[0])
        or not set(i["companies"]) <= set(flags(vocab, i["title"])[1])
    ]
    assert not missed, missed
    chatter = [t[:60] for t in EXT["should_not_flag"] if any(h.rule == 9 for h in flags(vocab, t)[0])]
    assert not chatter, chatter


def test_a_withdrawn_proposal_is_flagged_with_its_stage_recorded(vocab):
    hits, _ = flags(vocab, "Najd Gateway Holding withdraws PAI to acquire 84.5% stake in Samba Bank")
    assert "withdrawn, denied or called off" in next(h.detail for h in hits if h.rule == 9)


def test_the_holdout_is_separate_from_the_tuning_sets_and_empty_until_filled_from_new_headlines():
    tuned = {i["title"] for k in (BENCH, EXT) for i in k.get("should_flag", [])}
    tuned |= {t for k in (BENCH, EXT) for t in k.get("should_not_flag", [])}
    held = {i["title"] if isinstance(i, dict) else i for i in HOLD["should_flag"] + HOLD["should_not_flag"]}
    assert not held & tuned, "the holdout must not overlap the sets the rules were tuned against"
    if not held:
        pytest.skip("holdout is empty: fill it from headlines collected after 19 Nov, labelled first")
