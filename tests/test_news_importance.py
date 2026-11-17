"""News importance: the seven rules, de-duplication, event versions, reliability and priority. All offline."""

from __future__ import annotations

from datetime import UTC, datetime

from engines import news_facts as nf
from engines import news_importance as ni

LISTING = {
    "HUBC": "The Hub Power Company Limited",
    "NBP": "National Bank of Pakistan",
    "HBL": "Habib Bank Limited",
    "MCB": "MCB Bank Limited",
    "POML": "Punjab Oil Mills Limited",
    "ATRL": "Attock Refinery Limited",
    "LUCK": "Lucky Cement Limited",
}
ALIASES = {"Hub Power": "HUBC", "Hubco": "HUBC", "HUBCO": "HUBC", "Attock Refinery": "ATRL"}
VOCAB = nf.build_vocabulary(LISTING, ALIASES, ["CEMENT", "BANKS", "OIL_GAS"])
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def hl(title, source="profit", at="2026-11-17T03:00:00Z", url=None, snippet=None):
    return ni.Headline(source, url or f"https://x.pk/{abs(hash((title, source, at)))}", title, at, snippet)


def events_for(*headlines):
    evs = ni.cluster(list(headlines), (), VOCAB)
    ni.classify(VOCAB, evs)
    return evs


def rules_of(*headlines):
    return sorted({h.rule for e in events_for(*headlines) for h in e.hits})


# --- rule 1: results, earnings, payouts ------------------------------------------------------------


def test_rule1_company_results_earnings_and_payouts():
    assert 1 in rules_of(hl("NBP's profit falls 29% in the third quarter"))
    assert 1 in rules_of(hl("Hub Power announces final cash dividend of Rs5 per share"))
    assert 1 in rules_of(hl("Lucky Cement posts record earnings for the year"))


def test_rule1_needs_a_company_and_real_results_words():
    assert 1 not in rules_of(hl("Profit-taking drags the index lower"))  # no company
    assert 1 not in rules_of(
        hl("Supreme Court rules for Attock Refinery in sales tax dispute")
    )  # "sales tax"


# --- rule 2: SBP, FX, fiscal, inflation, energy, major index moves ---------------------------------


def test_rule2_macro_topics_and_major_index_moves():
    assert 2 in rules_of(hl("SBP holds policy rate at 11% in Pakistan"))
    assert 2 in rules_of(hl("Rupee weakens against the dollar in Pakistan interbank"))
    assert 2 in rules_of(hl("Pakistan inflation eases to 4% in October"))
    assert 2 in rules_of(hl("Govt cuts petrol, diesel price by Rs2 in Pakistan"))
    assert 2 in rules_of(hl("KSE-100 gains 1,200 points on IMF optimism"))


def test_rule2_small_or_unsized_index_moves_are_not_major():
    assert 2 not in rules_of(hl("KSE-100 gains 120 points in a quiet session"))
    assert 2 not in rules_of(hl("KSE-100 closes higher"))  # size not stated: unknown, not flagged


def test_company_names_do_not_trigger_macro_rules():
    # 'Oil' is in the company's name; 'taxes' is the company's own tax bill, not tax policy
    assert rules_of(hl("Punjab Oil Mills cut its costs. Its taxes ate the profit")) == [1]


# --- rules 3 and 6: unusual concentration against the baseline -------------------------------------


def signal(entity, text="x"):
    return {"company": entity, "fact_text": text, "source_url": "https://x/1", "value": "5"}


def test_rules3_and_6_come_from_baseline_signals_and_skip_macro_and_all():
    evs = ni.signal_events(
        [signal("HUBC"), signal("SECTOR:CEMENT"), signal("MACRO:PAKISTAN"), signal("ALL")], "2026-11-17"
    )
    by = {e.event_id: sorted(h.rule for h in e.hits) for e in evs}
    assert by == {"sig-HUBC-2026-11-17": [3], "sig-SECTOR:CEMENT-2026-11-17": [6]}


# --- rule 4: three distinct events about one company in one Pakistan-local day ---------------------


def test_rule4_counts_distinct_events_not_repeats_of_one_story():
    story = [
        hl("Hub Power signs smelter study deal", "mettis"),
        hl("HUBCO signs smelter study deal", "brecorder"),  # same story, other outlets
        hl("Hub Power signs smelter study agreement", "dawn_business"),
    ]
    evs = events_for(*story)
    assert len(evs) == 1 and ni.concentration_events(evs) == []
    others = [
        hl("Hub Power board meeting on December 5", "mettis"),
        hl("Hub Power eyes BYD assembly plant", "profit"),
    ]
    conc = ni.concentration_events(events_for(*story, *others))
    assert len(conc) == 1 and conc[0].hits[0].rule == 4 and conc[0].companies == ["HUBC"]


def test_rule4_uses_the_pakistan_local_day():
    # 19:30 UTC on the 16th is 00:30 on the 17th in Pakistan: a different day from 17:00 UTC on the 16th
    late = [
        hl(f"Hub Power story number {w}", at="2026-11-16T19:30:00Z") for w in ("alpha beta", "gamma delta")
    ]
    early = [hl("Hub Power story epsilon zeta", at="2026-11-16T17:00:00Z")]
    assert ni.concentration_events(events_for(*late, *early)) == []
    assert {e.day for e in events_for(*late)} == {"2026-11-17"} and events_for(*early)[0].day == "2026-11-16"


# --- rule 5: policy, IMF, regulatory, geopolitical -------------------------------------------------


def test_rule5_policy_imf_regulatory_and_geopolitical():
    assert 5 in rules_of(hl("IMF review mission arrives in Pakistan"))
    assert 5 in rules_of(hl("OGRA approves new gas tariff for Pakistan"))
    assert 5 in rules_of(hl("Govt imposes duty on imported steel in Pakistan"))
    assert 5 in rules_of(hl("Ceasefire talks lift oil prices"))
    assert 5 not in rules_of(hl("Company picks new chief financial officer"))


# --- rule 7: material adverse developments ---------------------------------------------------------


def test_rule7_adverse_company_developments_need_a_named_company_or_sector():
    assert 7 in rules_of(hl("Court orders Attock Refinery to pay fine"))
    assert 7 in rules_of(hl("Hub Power plant shutdown after fire at unit"))
    assert 7 in rules_of(hl("Lucky Cement cancels the contract with supplier"))
    assert 7 in rules_of(hl("Cement sector faces default risk as lenders raid books"))  # a sector counts
    assert 7 not in rules_of(hl("Fraud case widens in a neighbouring country"))  # nobody named


# --- de-duplication and versions -------------------------------------------------------------------


def test_related_headlines_become_one_event_and_different_companies_stay_apart():
    one = events_for(
        hl("Govt cuts petrol, high-speed diesel price by Rs2", "tribune_business"),
        hl("Govt reduces petrol, diesel prices by Rs2 per litre", "mettis"),
    )
    assert len(one) == 1 and one[0].sources == ["mettis", "tribune_business"]
    two = events_for(hl("HBL profit rises 20%"), hl("MCB profit rises 20%"))
    assert len(two) == 2


def test_event_id_is_stable_across_executions_and_a_seen_headline_is_not_counted_twice():
    first = hl("Hub Power signs smelter study deal", "mettis", url="https://m/1")
    ev = ni.cluster([first], (), VOCAB)[0]
    known = [
        {"event_id": ev.event_id, "anchor": sorted(ev.anchor), "urls": ["https://m/1"], "companies": ["HUBC"]}
    ]
    again = ni.cluster(
        [first, hl("HUBCO signs smelter study deal", "brecorder", url="https://b/1")], known, VOCAB
    )
    assert len(again) == 1 and again[0].event_id == ev.event_id and len(again[0].members) == 2


def test_version_changes_with_a_new_figure_not_with_another_outlet():
    base = events_for(hl("Hub Power profit rises 20% to Rs10 billion", "mettis"))[0]
    same_story = events_for(
        hl("Hub Power profit rises 20% to Rs10 billion", "mettis"),
        hl("HUBCO profit rises 20% to Rs10 billion", "brecorder"),
    )[0]
    revised = events_for(
        hl("Hub Power profit rises 20% to Rs10 billion", "mettis"),
        hl("Hub Power profit rises 20% to Rs12 billion", "brecorder"),
    )[0]
    assert base.version == same_story.version
    assert revised.version != base.version


# --- reliability, provenance, priority -------------------------------------------------------------


def test_unknown_source_reliability_is_none_and_provenance_lists_every_outlet():
    e = events_for(hl("Hub Power profit rises 20%", "mettis"), hl("HUBCO profit rises 20%", "mystery_wire"))[
        0
    ]
    prov = {p["source"]: p["reliability"] for p in ni.provenance(e)}
    assert prov == {"mettis": 0.80, "mystery_wire": None}
    assert all(p["url"] and p["published_at"] for p in ni.provenance(e))


def test_priority_orders_adverse_then_results_then_macro_and_corroboration_helps():
    adverse = events_for(hl("Hub Power plant shutdown after fire at unit"))[0]
    results = events_for(hl("NBP profit falls 29% in the third quarter"))[0]
    macro = events_for(hl("SBP holds policy rate at 11% in Pakistan"))[0]
    order = [e.title for e in ni.prioritised([macro, results, adverse], NOW)]
    assert order == [adverse.title, results.title, macro.title]
    solo = events_for(hl("NBP profit falls 29% in the third quarter", "mettis"))[0]
    many = events_for(
        hl("NBP profit falls 29% in the third quarter", "mettis"),
        hl("NBP profit falls 29% in third quarter", "dawn_business"),
    )[0]
    assert ni.priority(many, NOW) > ni.priority(solo, NOW)


def test_unflagged_events_have_zero_priority_and_are_not_returned():
    evs = events_for(hl("Company picks new chief financial officer"))
    assert ni.priority(evs[0], NOW) == 0.0 and ni.prioritised(evs, NOW) == []
