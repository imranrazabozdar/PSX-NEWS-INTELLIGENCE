from datetime import date, timedelta

from engines import dashboard_html as ui
from engines import setups as su

TODAY = date(2026, 11, 17)


def bars(n=40, start=100.0, step=1.0, volume=1_000_000.0, last_volume=None):
    out = []
    for i in range(n):
        d = (TODAY - timedelta(days=n - 1 - i)).isoformat()
        out.append({"trade_date": d, "close": start + step * i, "volume": volume})
    if last_volume:
        for b in out[-5:]:
            b["volume"] = last_volume
    return out


def fact(topic, value, day="2026-11-10", text="x"):
    return {"topic": topic, "value": value, "source_date": day, "fact_text": text, "period": day}


GOOD = [
    fact("fundamentals.return_on_equity", 24.0),
    fact("fundamentals.annual_p_e", 5.0),
    fact("fundamentals.price_book", 0.9),
    fact("fundamentals.dividend_yield", 8.0),
    fact("fundamentals.debt_equity", 40.0),
]


def test_eligibility_floors_thin_cheap_or_short_series_are_skipped():
    assert su.eligible(bars())
    assert not su.eligible(bars(n=10))
    assert not su.eligible(bars(volume=1000.0))  # turnover far below Rs 25m
    assert not su.eligible(bars(start=2.0, step=0.01))  # price below the floor


def test_technical_score_rises_with_trend_volume_and_the_engines_scores():
    flat = su.score_symbol("A", bars(step=0.0), [], TODAY, None)
    up = su.score_symbol("B", bars(step=1.0, last_volume=3_000_000.0), [], TODAY, None)
    withsig = su.score_symbol(
        "C",
        bars(step=1.0, last_volume=3_000_000.0),
        [fact("technical.wyckoff", 80.0), fact("technical.pattern", 0.9)],
        TODAY,
        None,
    )
    assert flat["technical"] < up["technical"]
    # a score is over the items that are measured: engine scores that are on file count, missing ones do not
    assert withsig["technical"] != up["technical"] and withsig["technical"] > 90
    assert any("accumulation score 80/100" in x for x in withsig["tech_evidence"])
    assert "technical engine accumulation score" in up["tech_unknown"]


def test_fundamental_score_and_unknowns_are_never_zero_filled():
    row = su.score_symbol("A", bars(), GOOD, TODAY, "CEMENT")
    assert row["fundamental"] is not None and row["fundamental"] > 70
    assert "EPS change" in row["fund_unknown"] and any(
        "return on equity 24.0%" in x for x in row["fund_evidence"]
    )
    none = su.score_symbol("B", bars(), [], TODAY, None)
    assert none["fundamental"] is None and none["combined"] is None and none["technical"] is not None


def test_artefacts_are_not_scored():
    for bad in (
        fact("fundamentals.price_book", -1.0, "2026-11-12"),
        fact("fundamentals.return_on_equity", 95.0, "2026-11-12"),
        fact("fundamentals.annual_p_e", -4.0, "2026-11-12"),
    ):
        row = su.score_symbol("A", bars(), GOOD[:1] + [bad], TODAY, None)
        assert row["fundamental"] is None and row["fund_unknown"] == ["fundamentals not usable"]


def test_ranking_needs_the_pillar_and_orders_best_first():
    rows = [
        su.score_symbol("A", bars(step=0.0), GOOD, TODAY, None),
        su.score_symbol("B", bars(step=1.0, last_volume=3e6), GOOD, TODAY, None),
        su.score_symbol("C", bars(step=1.0, last_volume=3e6), [], TODAY, None),
    ]
    assert [r["symbol"] for r in su.rank(rows, "combined")] == ["B", "A"]
    assert [r["symbol"] for r in su.rank(rows, "technical")][0] in ("B", "C")
    assert "C" not in [r["symbol"] for r in su.rank(rows, "fundamental")]
    assert len(su.rank(rows * 10, "technical", top=10)) == 10


def test_setup_cards_escape_text_show_pillars_and_use_no_advice_words():
    row = su.score_symbol("A<i>", bars(step=1.0, last_volume=3e6), GOOD, TODAY, "X & Y")
    html = ui.setup_cards_html([row], "combined")
    assert "A&lt;i&gt;" in html and "X &amp; Y" in html and "Technical" in html and "Fundamental" in html
    only_t = ui.setup_cards_html([row], "technical")
    assert "Fundamental:" not in only_t
    low = html.lower()
    for word in ("buy ", "sell ", "stop loss", "target price"):
        assert word not in low
    assert "Nothing qualifies" in ui.setup_cards_html([], "technical")


def test_announcements_news_and_corporate_actions_lift_the_fundamental_side():
    drivers = [
        {"kind": "announcement", "points": 25.0, "date": "2026-11-17", "text": "material deal"},
        {"kind": "corporate", "points": 10.0, "date": "2026-11-16", "text": "dividend"},
    ]
    plain = su.score_symbol("A", bars(), GOOD, TODAY, None)
    with_events = su.score_symbol("A", bars(), GOOD, TODAY, None, drivers)
    assert any(x.startswith("announcement (2026-11-17)") for x in with_events["fund_evidence"])
    assert "a recent material announcement" in plain["fund_unknown"]
    assert "a recent material announcement" not in with_events["fund_unknown"]
    assert "unusual recent news flow" in with_events["fund_unknown"]  # none on file: unknown, not zero
    assert with_events["fundamental"] != plain["fundamental"]
    pts, _ = su.event_items(drivers)
    assert pts["announcement"] == 10.0 and pts["corporate"] == 2.5 and pts["news"] is None


def test_lookup_says_where_a_stock_stands_or_why_it_is_not_scored():
    rows = {s: su.score_symbol(s, bars(step=st), GOOD, TODAY, None) for s, st in (("A", 0.0), ("B", 1.0))}
    result = {"rows": rows, "skipped": {"THIN": "thinly traded (Rs 1.0m a day; the floor is Rs 25m)"}}
    found = su.lookup(result, " b ")
    assert found["ranks"]["technical"] == (1, 2) and found["row"]["symbol"] == "B"
    assert su.lookup(result, "thin")["reason"].startswith("thinly traded")
    assert "no price series" in su.lookup(result, "zzz")["reason"]
    html = ui.lookup_html(found)
    assert "rank 1 of 2" in html and "not scored" in ui.lookup_html(su.lookup(result, "thin"))
