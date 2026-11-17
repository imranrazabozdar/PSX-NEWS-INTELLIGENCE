from datetime import date

from engines import materiality as m
from scripts import build_radar as br


def eps(period, value, text="EPS", unit="PKR_per_share"):
    return {
        "topic": "news.results",
        "fact_text": text,
        "value": value,
        "unit": unit,
        "period": period,
        "source_name": "x",
        "source_date": "2026-11-16",
    }


def test_periods_parse_only_comparable_forms():
    assert m.parse_period("9M 2026") == ("9M", 2026)
    assert m.parse_period("2026 3Q") == ("3Q", 2026) and m.parse_period("3Q 2026") == ("3Q", 2026)
    assert m.parse_period("2026-10-29") is None and m.parse_period(None) is None


def test_like_for_like_eps_change_and_its_unknowns():
    hist = m.eps_history([eps("9M 2026", 36.84), eps("9M 2025", 35.0)])
    change, why = m.eps_change(hist)
    assert why is None and round(change["pct"], 1) == 5.3 and change["label"] == "9M 2026 vs 2025"
    assert m.eps_change(m.eps_history([eps("9M 2026", 36.84)]))[0] is None
    swing, _ = m.eps_change(m.eps_history([eps("9M 2026", -2.0), eps("9M 2025", 5.0)]))
    assert swing["pct"] is None and swing["swing"]
    assert m.eps_history([eps("9M 2026", 5.0, text="dividend")]) == {}


def test_conflicting_sources_make_it_unknown_not_averaged():
    hist = m.eps_history([eps("9M 2026", 10.0), eps("9M 2026", 20.0), eps("9M 2025", 5.0)])
    assert hist[("9M", 2026)] is None
    change, why = m.eps_change(hist)
    assert change is None and "no like-for-like" in why


def test_score_is_built_only_from_dated_sourced_drivers():
    win = [
        {
            "topic": "news.results",
            "fact_text": "NBP profit falls 29%",
            "source_name": "Profit",
            "source_date": "2026-11-16",
            "value": None,
        },
        {
            "topic": "technical.wyckoff",
            "fact_text": "score 100",
            "source_name": "tech",
            "source_date": "2026-11-16",
            "value": 100.0,
        },
    ]
    s = m.score_company(
        "NBP",
        window_facts=win,
        history_facts=[],
        price={"day": "2026-11-16", "move": -6.0, "volume_x": 4.0},
        news_signal=None,
        has_prices=True,
    )
    kinds = {d["kind"] for d in s["drivers"]}
    assert kinds == {"results", "price", "technical"} and 0 < s["score"] <= 100
    assert any("size unknown" in u for u in s["unknown"])
    assert all(d["date"] and d["source"] for d in s["drivers"])


def test_nothing_in_the_window_scores_nothing_and_is_not_ranked():
    s = m.score_company(
        "ZZZ", window_facts=[], history_facts=[], price=None, news_signal=None, has_prices=False
    )
    assert s["score"] == 0 and s["drivers"] == [] and "no price series" in s["unknown"][0]
    assert m.rank([s]) == []


def test_ranking_orders_by_score_then_symbol_and_caps():
    a = {"symbol": "B", "score": 50.0, "drivers": [1], "unknown": []}
    b = {"symbol": "A", "score": 50.0, "drivers": [1], "unknown": []}
    c = {"symbol": "C", "score": 80.0, "drivers": [1], "unknown": []}
    assert [s["symbol"] for s in m.rank([a, b, c], top=2)] == ["C", "A"]


def test_radar_text_never_carries_action_words():
    md = m.render_markdown(
        [
            {
                "symbol": "ABC",
                "score": 40.0,
                "unknown": [],
                "drivers": [
                    m._driver("price", 20, "closed up 7.0% on 2026-11-16", "2026-11-16", "price_daily")
                ],
            }
        ],
        "2026-11-17",
        10,
        5,
    )
    assert "not recommendations" in md and "ABC" in md
    for word in ("buy ", "sell ", "target", "stop loss"):
        assert word not in md.lower()


def test_price_moves_use_the_biggest_recent_session_and_need_20_sessions_for_volume():
    rows = [
        {"symbol": "ABC", "trade_date": f"2026-10-{i + 1:02d}", "close": 100.0, "volume": 100.0}
        for i in range(25)
    ]
    rows.append({"symbol": "ABC", "trade_date": "2026-11-16", "close": 110.0, "volume": 400.0})

    class DB:
        def execute(self, sql, params=()):
            return rows

    out, symbols = br.price_moves(DB(), date(2026, 11, 17), 3)
    assert symbols == {"ABC"} and round(out["ABC"]["move"], 1) == 10.0 and out["ABC"]["volume_x"] == 4.0


def test_an_old_announcement_loaded_today_is_not_new():
    old = {"topic": "announcements.Financial Result", "period": "2026-10-28", "source_date": "2026-11-16"}
    news = {"topic": "news.results", "period": "9M 2026", "source_date": "2026-11-16"}
    assert br.event_date(old) == "2026-10-28"
    assert br.event_date(news) == "2026-11-16"


def psx(period, value, basis, unit="PKR/share"):
    return {
        "topic": "results.nine_months",
        "fact_text": f"Financial result, {period} ({basis}): EPS {value}.",
        "value": value,
        "unit": unit,
        "period": period,
        "source_name": "PSX",
        "source_date": "2026-10-23",
    }


def test_psx_periods_compare_like_for_like_and_never_mix_bases():
    facts = [
        psx("nine months ended 2026-09-30", 35.23, "consolidated"),
        psx("nine months ended 2026-09-30", 36.84, "unconsolidated"),
        psx("nine months ended 2025-09-30", 32.31, "consolidated"),
    ]
    change, why = m.eps_change(m.eps_history(facts))
    assert why is None and round(change["pct"], 1) == 9.0
    assert "consolidated" in change["label"] and "unconsolidated" not in change["label"]
    only_unconsol_now = m.eps_change(m.eps_history(facts[1:2] + facts[2:3]))
    assert only_unconsol_now[0] is None


def test_ended_periods_parse_to_a_kind_that_repeats_each_year():
    assert m.parse_period("first quarter ended 2026-03-31") == ("Q@03-31", 2026)
    assert m.parse_period("half yer ended 2025-06-30") == ("H@06-30", 2025)
    assert m.parse_period("year ended 2025-12-31") == ("FY@12-31", 2025)


def test_the_most_recent_period_is_compared_first():
    def q(period, value):
        return {
            "topic": "results.quarterly",
            "fact_text": f"{period} (consolidated): EPS {value}",
            "value": value,
            "unit": "PKR/share",
            "period": period,
            "source_name": "PSX",
            "source_date": "2026-10-28",
        }

    facts = [
        q("half ended 2026-06-30", 20.0),
        q("half ended 2025-06-30", 15.0),
        q("third quarter ended 2026-09-30", 8.0),
        q("third quarter ended 2025-09-30", 10.0),
    ]
    change, _ = m.eps_change(m.eps_history(facts))
    assert change["label"].startswith("Q 09-30") and round(change["pct"]) == -20
