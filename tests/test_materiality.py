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


# ---- pairing Investify's newest EPS with the PSX history (like-for-like only when proven) ----------------


def _psx(kind_text, period, value, basis="consolidated"):
    return {
        "topic": "results.quarterly",
        "fact_text": f"Financial result, {kind_text} ({basis}): EPS {value}.",
        "value": value,
        "unit": "PKR/share",
        "period": period,
        "source_name": "PSX",
        "source_date": "2025-11-01",
    }


def _inv(topic, period, value):
    return {
        "topic": topic,
        "fact_text": f"EPS: Rs. {value} ({period})",
        "value": value,
        "unit": "PKR",
        "period": period,
        "source_name": "Investify fundamentals (investify.pk)",
        "source_date": "2026-11-16",
    }


def single_basis_company():
    return [
        _psx("year ended 2025-12-31", "year ended 2025-12-31", 10.0),
        _psx("third quarter ended 2025-09-30", "third quarter ended 2025-09-30", 2.0),
    ]


def test_investify_periods_map_onto_psx_period_ends_for_any_fiscal_year():
    assert m.investify_key("fundamentals.latest_quarter_eps", "2026 3Q", (12, 31)) == ("Q@09-30", 2026)
    assert m.investify_key("fundamentals.year_to_date_eps", "UPTO 2026 3Q", (12, 31)) == ("9M@09-30", 2026)
    assert m.investify_key("fundamentals.annual_eps", "2025 FY", (12, 31)) == ("FY@12-31", 2025)
    # a June year end: fiscal 2027 Q1 is July-September 2026
    assert m.investify_key("fundamentals.latest_quarter_eps", "2027 1Q", (6, 30)) == ("Q@09-30", 2026)
    assert m.investify_key("fundamentals.year_to_date_eps", "UPTO 2027 2Q", (6, 30)) == ("H@12-31", 2026)
    assert m.investify_key("fundamentals.latest_quarter_eps", "2026 4Q", (12, 31)) is None
    assert m.investify_key("fundamentals.annual_eps", "garbage", (12, 31)) is None


def test_the_newest_investify_figure_pairs_with_last_year_only_when_validated():
    facts = single_basis_company() + [
        _inv("fundamentals.annual_eps", "2025 FY", 10.0),
        _inv("fundamentals.latest_quarter_eps", "2026 3Q", 3.0),
    ]
    change, why = m.eps_pair(facts)
    assert why is None and round(change["pct"]) == 50
    assert "latest figure from Investify" in change["label"] and "consolidated" in change["label"]


def test_a_disagreement_on_an_overlapping_period_blocks_the_pairing():
    facts = single_basis_company() + [
        _inv("fundamentals.annual_eps", "2025 FY", 14.0),
        _inv("fundamentals.latest_quarter_eps", "2026 3Q", 3.0),
    ]
    change, why = m.eps_pair(facts)
    assert change is None and "no like-for-like" in why


def test_no_overlap_to_prove_the_basis_means_no_pairing():
    facts = single_basis_company() + [_inv("fundamentals.latest_quarter_eps", "2026 3Q", 3.0)]
    assert m.eps_pair(facts)[0] is None


def test_a_company_reporting_two_bases_is_never_paired_with_investify():
    facts = [
        _psx("year ended 2025-12-31", "year ended 2025-12-31", 45.48),
        _psx("year ended 2025-12-31", "year ended 2025-12-31", 42.6, "unconsolidated"),
        _psx("third quarter ended 2025-09-30", "third quarter ended 2025-09-30", 12.0),
        _psx("third quarter ended 2025-09-30", "third quarter ended 2025-09-30", 11.0, "unconsolidated"),
        _inv("fundamentals.annual_eps", "2025 FY", 42.6),
        _inv("fundamentals.latest_quarter_eps", "2026 3Q", 12.36),
    ]
    assert m.eps_pair(facts)[0] is None


def test_when_psx_already_has_the_period_its_figure_stands_and_nothing_is_overridden():
    facts = single_basis_company() + [
        _psx("third quarter ended 2026-09-30", "third quarter ended 2026-09-30", 2.5),
        _inv("fundamentals.annual_eps", "2025 FY", 10.0),
        _inv("fundamentals.latest_quarter_eps", "2026 3Q", 99.0),
    ]
    change, _ = m.eps_pair(facts)
    assert change["cur"] == 2.5 and "Investify" not in change["label"]


def test_unlabelled_psx_results_are_a_single_basis_and_can_pair():
    def u(period, value):
        return {
            "topic": "results.quarterly",
            "fact_text": f"Financial result, {period}: EPS {value}.",
            "value": value,
            "unit": "PKR/share",
            "period": period,
            "source_name": "PSX",
            "source_date": "2025-11-01",
        }

    facts = [
        u("year ended 2025-06-30", 10.0),
        u("first quarter ended 2025-09-30", 2.0),
        _inv("fundamentals.annual_eps", "2025 FY", 10.0),
        _inv("fundamentals.latest_quarter_eps", "2027 1Q", 3.0),
    ]
    change, why = m.eps_pair(facts)
    assert why is None and round(change["pct"]) == 50 and "Investify" in change["label"]
    # one labelled and one unlabelled figure for the same period is two bases: never paired
    both = [
        *facts,
        {
            **u("first quarter ended 2025-09-30", 9.0),
            "fact_text": "Financial result, first quarter ended 2025-09-30 (consolidated): EPS 9.0.",
        },
    ]
    assert m.eps_pair(both)[0] is None


def test_an_implausible_jump_in_the_investify_figure_is_not_used():
    facts = single_basis_company() + [
        _inv("fundamentals.annual_eps", "2025 FY", 10.0),
        _inv("fundamentals.latest_quarter_eps", "2026 3Q", 25.0),
    ]  # 12.5x last year
    assert m.eps_pair(facts)[0] is None


def _ann(label, day="2026-11-16", text="x"):
    return {
        "topic": f"announcements.{label}",
        "fact_text": f"{day}: {text}",
        "source_date": day,
        "source_name": "Investify",
        "value": None,
    }


def test_a_material_announcement_is_sized_from_its_numbers_and_routine_ones_are_not():
    base = dict(history_facts=[], price=None, news_signal=None, has_prices=True)
    vague = m.score_company("HUBC", window_facts=[_ann("Operations Update", text="smelter study")], **base)
    assert [d["kind"] for d in vague["drivers"]] == ["announcement"]
    assert vague["score"] == 8.0 and "unquantified" in vague["drivers"][0]["text"]
    assert any("announcement size unknown" in u for u in vague["unknown"])
    deal = m.score_company(
        "NRSL",
        window_facts=[
            _ann("M&A / Public Offer", text="IGI Investments intends to acquire up to 60% of Nimir Resins")
        ],
        company_names=["Nimir Resins"],
        **base,
    )
    assert deal["score"] == 25.0 and "major" in deal["drivers"][0]["text"] and deal["unknown"] == []
    big = m.score_company(
        "X",
        window_facts=[_ann("Financing / Restructuring", text="X secures Rs 15 billion loan")],
        company_names=["X"],
        mcap=100e9,
        **base,
    )
    assert big["score"] == 25.0 and "15.0% of market cap" in big["drivers"][0]["text"]
    scheduled = m.score_company("HUBC", window_facts=[_ann("Board Meeting")], **base)
    assert scheduled["score"] == 3.0 and scheduled["drivers"][0]["text"].startswith("routine notice")
    routine = m.score_company(
        "HUBC", window_facts=[_ann("Report Transmission"), _ann("Insider Sell")], **base
    )
    assert routine["drivers"] == [] and routine["score"] == 0
    several = m.score_company(
        "HUBC", window_facts=[_ann("Operations Update"), _ann("Management Change")], **base
    )
    assert several["score"] == 8.0 and "2 material announcements" in several["drivers"][0]["text"]
