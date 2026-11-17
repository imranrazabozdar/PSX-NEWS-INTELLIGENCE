from engines import announcement_substance as s

NIMIR = ["Nimir Resins", "Nimir Resins Limited"]
IGI = ["IGI Investments", "IGI Holdings"]


def a(label, text, names, mcap=None):
    return s.assess(label, text, company_names=names, mcap=mcap)


def test_a_takeover_stake_is_graded_for_the_target_and_not_for_the_acquirer():
    text = "2026-11-16: IGI Investments has agreed to acquire up to 60% of Nimir Resins"
    target = a("M&A / Public Offer", text, NIMIR)
    assert target["tier"] == "major" and target["points"] == 25.0 and target["quantified"]
    intent = a(
        "M&A / Public Offer",
        "2026-11-16: IGI Investments intends to acquire up to 60% of Nimir Resins",
        NIMIR,
    )
    assert intent["tier"] == "major" and intent["stage"] == "preliminary" and intent["points"] == 15.0
    assert any("60%" in b for b in target["basis"]) and any("change of control" in b for b in target["basis"])
    acquirer = a("M&A / Public Offer", text, IGI)
    assert acquirer["tier"] == "unquantified" and not acquirer["quantified"]
    assert any("not shown to be the target" in b for b in acquirer["basis"])


def test_stake_bands_follow_the_stated_percentage():
    base = "2026-11-02: controlling shareholders agree to sell {p}% stake in Target Co to Buyer"
    tiers = {p: a("M&A / Public Offer", base.format(p=p), ["Target Co"])["tier"] for p in (51, 30, 12, 4)}
    assert tiers == {51: "major", 30: "significant", 12: "moderate", 4: "minor"}


def test_amounts_are_set_against_the_companys_own_size():
    mcap = 100e9
    big = a("Financing / Restructuring", "2026-11-10: X secures Rs 15 billion loan", ["X"], mcap)
    mid = a("Capacity / Shutdown", "2026-11-10: X adds capacity worth Rs. 4 billion", ["X"], mcap)
    small = a("Operations Update", "2026-11-10: X signs a Rs 500 million contract", ["X"], mcap)
    assert (big["tier"], mid["tier"], small["tier"]) == ("major", "significant", "minor")
    assert "15.0% of market cap" in big["basis"][0]
    sizeless = a("Financing / Restructuring", "2026-11-10: X secures Rs 15 billion loan", ["X"], None)
    assert sizeless["tier"] == "unquantified" and "size not on file" in sizeless["basis"][0]


def test_a_headline_with_no_quantity_says_unquantified_not_a_size():
    out = a(
        "Operations Update",
        "2026-11-13: Mari Energies reports a significant copper-gold discovery",
        ["Mari"],
        885e9,
    )
    assert out["tier"] == "unquantified" and out["basis"] == ["no quantity stated in the announcement text"]
    assert out["points"] < s.POINTS["moderate"]


def test_per_share_figures_and_dollar_amounts_are_not_taken_as_a_size():
    div = a("Corporate Action", "2026-11-02: X credits cash dividend of Rs. 5 per share", ["X"], 100e9)
    assert div["tier"] == "unquantified"
    usd = a("Financing / Restructuring", "2026-11-02: X raises $200 million facility", ["X"], 100e9)
    assert usd["tier"] == "unquantified" and "US dollar" in usd["basis"][0]


def test_routine_labels_are_routine_and_the_market_cap_is_parsed():
    assert a("Report Transmission", "2026-11-02: report sent", ["X"])["tier"] == "routine"
    facts = [
        {
            "topic": "fundamentals.market_cap",
            "fact_text": "Market Cap: Rs. 885.19B (CURRENT)",
            "source_date": "2026-11-17",
        },
        {
            "topic": "fundamentals.market_cap",
            "fact_text": "Market Cap: Rs. 1.2T (CURRENT)",
            "source_date": "2026-11-01",
        },
    ]
    assert s.market_cap(facts) == 885.19e9
    assert s.market_cap([]) is None


def test_in_a_sale_the_company_named_before_the_verb_is_the_target():
    text = (
        "2026-11-02: Nimir Industrial Chemicals controlling shareholders "
        "agree to sell 51% stake to Cherat Cement"
    )
    seller_side = a("M&A / Public Offer", text, ["Nimir Industrial Chemicals"])
    assert seller_side["tier"] == "major" and seller_side["quantified"]
    buyer = a("M&A / Public Offer", text, ["Cherat Cement"])
    assert buyer["tier"] == "unquantified" and "not shown to be the target" in buyer["basis"][0]


def test_a_deal_the_text_calls_preliminary_counts_for_less_and_says_why():
    title = "2026-11-16: IGI Investments has agreed to acquire up to 60% of Nimir Resins"
    firm = a("M&A / Public Offer", title, NIMIR)
    early = s.assess(
        "M&A / Public Offer",
        title,
        company_names=NIMIR,
        mcap=None,
        highlights="The board gave in-principle approval to evaluate and conduct due diligence.",
    )
    assert firm["stage"] == "definitive" and firm["points"] == 25.0
    assert early["tier"] == "major" and early["stage"] == "preliminary" and early["points"] == 15.0
    assert any("stage: preliminary" in b and "in-principle" in b.lower() for b in early["basis"])
    signed = s.assess(
        "M&A / Public Offer",
        title,
        company_names=NIMIR,
        mcap=None,
        highlights="IGI has signed a share purchase agreement.",
    )
    assert signed["stage"] == "definitive" and signed["points"] == 25.0


def test_a_discovery_whose_scale_is_still_to_be_determined_is_preliminary_and_unquantified():
    out = s.assess(
        "Operations Update",
        "2026-11-13: Mari Energies reports a significant copper-gold discovery",
        company_names=["Mari"],
        mcap=885e9,
        highlights="Further drilling and resource estimation are needed to determine "
        "the discovery's scale and economic potential.",
    )
    assert out["tier"] == "unquantified" and out["stage"] == "preliminary" and out["points"] == 4.8
    assert any("no stake or rupee amount stated" in b for b in out["basis"])


def test_the_highlights_chunks_are_joined_in_order_by_the_title_key():
    title = "X signs an agreement"
    facts = [
        {
            "topic": s.HIGHLIGHTS_TOPIC,
            "period": "2026-11-16",
            "fact_text": "2026-11-16: second part",
            "source_url": f"https://investify.pk/company/X/announcements#{s.title_key(title)}-2",
        },
        {
            "topic": s.HIGHLIGHTS_TOPIC,
            "period": "2026-11-16",
            "fact_text": "2026-11-16: first part",
            "source_url": f"https://investify.pk/company/X/announcements#{s.title_key(title)}-1",
        },
        {
            "topic": s.HIGHLIGHTS_TOPIC,
            "period": "2026-11-16",
            "fact_text": "2026-11-16: other",
            "source_url": "https://investify.pk/company/X/announcements#0000000000-1",
        },
    ]
    assert s.highlight_text(facts, "2026-11-16", title) == "first part second part"
    assert s.highlight_text(facts, "2026-11-15", title) == ""


def test_stray_punctuation_after_a_currency_is_not_an_amount():
    assert s.rupee_amounts("paid Rs, then PKR., and Rs. ,") == []
    assert s.usd_amounts("US$, million") == []
    out = a("Financing / Restructuring", "2026-11-10: X reports Rs, PKR. and ,", ["X"], 100e9)
    assert out["tier"] == "unquantified"
    assert s.rupee_amounts("loan of Rs. 1,250 million and Rs 3.5 billion") == [1.25e9, 3.5e9]


def test_conditions_on_a_signed_deal_do_not_make_it_preliminary_but_proposals_do():
    sale = s.assess(
        "M&A / Public Offer",
        "2026-11-02: Yco Ltd controlling shareholders agree to sell 51% stake to Buyer",
        company_names=["Yco Ltd"],
        mcap=None,
        highlights="Completion is subject to regulatory approvals and a public offer.",
    )
    assert sale["stage"] == "definitive" and sale["points"] == 25.0
    for text in (
        "X proposes PKR 3 billion rights issue",
        "X seeks SECP approval to raise capital",
        "X intends to acquire a stake",
    ):
        assert s.stage_of(text)[0] == "preliminary", text
    assert s.stage_of("X approves PKR 3 billion rights issue")[0] == "unclear"
