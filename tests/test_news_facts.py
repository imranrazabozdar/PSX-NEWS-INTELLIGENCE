"""News headlines to fact rows: company matching, sectors, macro topics, dates and the false positives."""

from __future__ import annotations

from datetime import date

from engines import freshness
from engines import news_facts as nf

LISTING = {
    "HUBC": "The Hub Power Company Limited",
    "LUCK": "Lucky Cement Limited",
    "HBL": "Habib Bank Limited",
    "NBP": "National Bank of Pakistan",
    "PSX": "Pakistan Stock Exchange Limited",
    "PMI": "Pak Mercantile Industries Limited",
    "HALEON": "Haleon Pakistan Limited",
}
ALIASES = {"Hub Power": "HUBC", "Hubco": "HUBC", "Glass Industry": "SECTOR:GLASS", "Hafco": "HUBC"}
VOCAB = nf.build_vocabulary(LISTING, ALIASES, ["CEMENT", "BANKS", "SUGAR", "GLASS"])


def item(title, snippet=None, source="profit", published="2026-11-16T09:00:00Z", section=None):
    return {
        "source": source,
        "url": "https://x.pk/a",
        "title": title,
        "snippet": snippet,
        "published_at": published,
        "section": section,
    }


def rows(title, snippet=None, **kw):
    kw.setdefault("macro_copy", False)
    mc = kw.pop("macro_copy")
    return nf.rows_for_item(
        VOCAB, item(title, snippet, **kw), created_at="2026-11-16T10:00:00Z", macro_copy=mc
    )


def test_company_by_name_alias_and_ticker():
    assert [r["company"] for r in rows("Hub Power posts record profit in 2026")] == ["HUBC"]
    assert [r["company"] for r in rows("Hubco board approves dividend")] == ["HUBC"]
    assert [r["company"] for r in rows("LUCK shares rise after results")] == ["LUCK"]
    assert [r["company"] for r in rows("Haleon Pakistan expands plant")] == ["HALEON"]


def test_the_exchange_and_index_acronyms_are_not_companies():
    out = rows("PSX Closing Bell: KSE-100 settles 300 points higher")
    assert [r["company"] for r in out] == ["MACRO:PAKISTAN"] and out[0]["topic"] == "market.index"
    assert rows("Manufacturing PMI back to growth in Pakistan") == []  # PMI the index is not the company PMI
    assert "PSX" not in {r["company"] for r in rows("Tariq Nisar crosses 10% stake in Hub Power on PSX")}


def test_all_capitals_headline_does_not_turn_every_word_into_a_ticker():
    assert rows("HBL AND LUCK ANNOUNCE NEW PLANS FOR PAKISTAN MARKET") == []


def test_topics_for_company_rows():
    assert rows("Hub Power net profit rises 20% in nine months")[0]["topic"] == "news.results"
    assert rows("Lucky Cement announces interim cash dividend")[0]["topic"] == "news.dividend"
    assert rows("Habib Bank opens new branch in Gwadar")[0]["topic"] == "news.company"


def test_at_most_three_companies_else_the_item_is_a_roundup_not_company_rows():
    out = rows("Hub Power, Lucky Cement, Habib Bank and National Bank of Pakistan lead the rally")
    assert not [r for r in out if ":" not in r["company"]]


def test_today_and_yesterday_become_dates():
    out = rows("Hub Power shares jump today", "The company reported results yesterday.")
    assert "on 16 Nov 2026" in out[0]["fact_text"] and "on 15 Nov 2026" in out[0]["fact_text"]
    assert "today" not in out[0]["fact_text"].lower() and out[0]["source_date"] == "2026-11-16"


def test_row_shape_is_valid_for_the_loader():
    from engines import research_facts as rf

    for r in rows(
        "Lucky Cement announces interim cash dividend", "Payout is Rs5 per share.", source="dawn_business"
    ):
        rf.validate_fact(r)
        assert r["source_name"] == "Dawn Business news, 2026-11-16" and r["confidence"] == "fact"
        assert len(r["fact_text"]) <= nf.MAX_FACT_CHARS and "<" not in r["source_name"]


def test_sector_rows_only_for_sectors_the_library_has():
    assert [r["company"] for r in rows("CCP issues show-cause notices to sugar mills in Pakistan")] == [
        "SECTOR:SUGAR"
    ]
    out = rows("Pakistan textile exports rise")  # TEXTILE is not in this vocabulary
    assert not [r for r in out if r["company"].startswith("SECTOR:")]


def test_macro_needs_a_pakistan_context_and_a_headline_factor():
    assert rows("SBP keeps policy rate unchanged")[0]["topic"] == "market.rates"
    assert rows("Rupee ends flat against dollar in Karachi interbank")[0]["topic"] == "market.fx"
    assert rows("Fed holds policy rate steady") == []  # no Pakistan context
    assert (
        rows("Pakistan debuts genomics venture", "Talks covered security cooperation.") == []
    )  # snippet only


def test_macro_topic_is_deterministic_with_several_factors():
    title = "SBP policy rate, rupee and inflation outlook in Pakistan"
    assert {rows(title)[0]["topic"] for _ in range(20)} == {"market.rates"}


def test_bank_is_not_the_word_ban_in_the_shared_factor_matcher():
    assert "regulation" not in freshness.factors_in("SBP extends bank working hours on Saturday")
    assert "regulation" in freshness.factors_in("Government imposes ban on imports")
    assert "imf_fiscal" in freshness.factors_in("New taxation measures and taxes")
    assert "oil_energy" in freshness.factors_in(
        "Oil prices fall"
    ) and "oil_energy" not in freshness.factors_in("oily")


def test_opinion_and_forecasts_are_analyst_views():
    assert rows("Hub Power faces headwinds", section="Editorials")[0]["confidence"] == "analyst_view"
    assert rows("Analysts expect Hub Power profit to double")[0]["confidence"] == "analyst_view"
    assert rows("Hub Power commissions new unit")[0]["confidence"] == "fact"


def test_fact_text_is_trimmed_to_the_limit_without_cutting_a_word():
    long = "Hub Power " + "word " * 80
    text = rows(long)[0]["fact_text"]
    assert len(text) <= nf.MAX_FACT_CHARS and text.endswith("...") and not text[:-3].endswith(" wor")
    assert nf.absolute_dates("Prices rise today", date(2026, 11, 16)) == "Prices rise on 16 Nov 2026"


def test_topic_and_sector_come_from_the_headline_not_the_snippet():
    out = rows("NBP profit falls 29% in the third quarter", "The bank may revisit its dividend payout.")
    assert [(r["company"], r["topic"]) for r in out] == [("NBP", "news.results")]
    assert rows("The quiet brain drain", "Software engineers keep leaving Pakistan for the Gulf.") == []
    out = rows(
        "Pakistan forex reserves decrease by $133 million", "The State Bank of Pakistan said on Thursday."
    )
    assert [(r["company"], r["topic"]) for r in out] == [("MACRO:PAKISTAN", "market.fx")]


def test_a_company_must_be_named_in_the_headline_and_sponsors_are_ignored():
    assert rows("Tariq Nisar crosses 10% stake", "Hub Power Company Limited has disclosed it.") == []
    assert rows("HBL Manufacturing PMI edges down to a six-month low") == []
    assert rows("The miracle called the HBL PSL") == []
    assert [r["company"] for r in rows("HBL reports record profit")] == ["HBL"]


def test_one_word_names_come_only_from_confirmed_aliases():
    vocab = nf.build_vocabulary({"TCORP": "Tariq Corporation Limited"}, {}, [])
    assert nf.companies_in(vocab, "Tariq Nisar crosses 10% stake") == []


def test_no_stray_period_after_a_question_headline():
    text = nf.fact_text("Is Hub Power reviving?", "It posted a profit.", date(2026, 11, 16))
    assert text == "Is Hub Power reviving? It posted a profit."


def test_a_company_or_sector_headline_is_also_filed_once_under_macro_pakistan():
    out = rows("Hub Power posts record profit in 2026", macro_copy=True)
    assert [(r["company"], r["topic"]) for r in out] == [
        ("HUBC", "news.results"),
        ("MACRO:PAKISTAN", "market.news"),
    ]
    # a headline with its own market topic keeps that topic and gets no second macro row
    out = rows("Hub Power shares rise as KSE-100 gains 300 points", macro_copy=True)
    assert [r["topic"] for r in out if r["company"] == "MACRO:PAKISTAN"] == ["market.index"]
    # nothing matched: no macro copy either
    assert rows("Cricket final preview", macro_copy=True) == []
