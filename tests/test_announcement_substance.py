from engines import announcement_substance as s

NIMIR = ["Nimir Resins", "Nimir Resins Limited"]
IGI = ["IGI Investments", "IGI Holdings"]


def a(label, text, names, mcap=None):
    return s.assess(label, text, company_names=names, mcap=mcap)


def test_a_takeover_stake_is_graded_for_the_target_and_not_for_the_acquirer():
    text = "2026-11-16: IGI Investments intends to acquire up to 60% of Nimir Resins"
    target = a("M&A / Public Offer", text, NIMIR)
    assert target["tier"] == "major" and target["points"] == 25.0 and target["quantified"]
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
