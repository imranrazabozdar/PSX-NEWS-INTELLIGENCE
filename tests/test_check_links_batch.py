from scripts import check_links_batch as chk

FACTS = [{"id": 1, "company": "LUCK", "topic": "cost.coal", "fact_text": "Coal prices up hurt margins"}]


def test_valid_link_passes_and_fabricated_quote_fails():
    ok = {"driver": "coal", "affected": "LUCK", "direction": "down", "fact_id": 1, "quote": "Coal prices up"}
    bad = dict(ok, quote="Coal prices collapsed")
    assert chk.judge([ok], FACTS)["passes"]
    out = chk.judge([ok, bad], FACTS)
    assert out["valid"] == 1 and not out["passes"]


def test_unknown_fact_or_direction_fails():
    link = {"driver": "x", "affected": "LUCK", "direction": "sideways", "fact_id": 1, "quote": "Coal"}
    assert not chk.judge([link], FACTS)["passes"]
    assert not chk.judge([dict(link, direction="up", fact_id=9)], FACTS)["passes"]
