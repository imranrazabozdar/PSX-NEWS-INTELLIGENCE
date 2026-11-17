from engines import daily_digest as dd


def moves_for(day, values):
    return {(f"S{i}", day): {"move": v, "volume_x": None} for i, v in enumerate(values)}


def test_breadth_counts_and_picks_extremes_and_is_none_without_trading():
    mv = moves_for("2026-11-16", [5.0, -3.0, 0.0, 1.0, -8.0])
    b = dd.breadth(mv, "2026-11-16")
    assert (b["symbols"], b["up"], b["down"], b["flat"]) == (5, 2, 2, 1)
    assert b["median"] == 0.0 and b["top_up"][0] == ("S0", 5.0) and b["top_down"][0] == ("S4", -8.0)
    assert dd.breadth(mv, "2026-11-13") is None
    assert dd.latest_trading_day(mv) == "2026-11-16" and dd.latest_trading_day({}) is None


def digest():
    radar = [
        {
            "symbol": "NBP",
            "score": 55.0,
            "unknown": ["result size unknown: no pair"],
            "drivers": [
                {"kind": "results", "points": 35, "text": "NBP profit falls 29%"},
                {"kind": "price", "points": 10, "text": "closed down 3%"},
            ],
        }
    ]
    moves = [
        {
            "symbol": "DEL",
            "move": 10.0,
            "day": "2026-11-16",
            "volume_x": 4.1,
            "verdict": "evidence on file about this company is consistent with the move",
            "evidence": [{"text": "DEL reports results"}],
        },
        {
            "symbol": "ZZZ",
            "move": -7.0,
            "day": "2026-11-16",
            "volume_x": 9.0,
            "verdict": "no identified cause in the evidence on file",
            "evidence": [],
        },
    ]
    br = dd.breadth(moves_for("2026-11-16", [2.0, -1.0, 0.5]), "2026-11-16")
    return dd.render(
        "2026-11-17",
        "2026-11-16",
        br,
        radar,
        moves,
        {"latest price day": "2026-11-16", "latest news day": None},
        148,
    )


def test_the_digest_has_every_section_and_reports_unknowns():
    md = digest()
    for part in (
        "## Data freshness",
        "## Market on 2026-11-16",
        "## Companies to look at (radar)",
        "## Notable moves and what is on file",
        "## Unexplained (no cause on file): 1 of 2",
    ):
        assert part in md
    assert "latest news day: unknown" in md and "unknown: result size unknown" in md
    assert "ZZZ -7.0%" in md and "DEL +10.0%" in md


def test_the_digest_gives_no_advice_and_handles_an_empty_day():
    md = digest().lower()
    for word in ("buy ", "sell ", "will rise", "stop loss", "target price"):
        assert word not in md
    assert "not forecasts" in md
    empty = dd.render("2026-11-17", None, None, [], [], {}, 0)
    assert "No price data for that day." in empty and "Nothing scored in the window." in empty


def test_the_once_a_day_probe_reads_one_indexed_row_per_symbol_and_can_say_none():
    from scripts import build_digest as bd

    class DB:
        def __init__(self, rows_by_symbol):
            self.rows, self.calls = rows_by_symbol, []

        def execute(self, sql, params=()):
            assert "LIMIT 1" in sql and "ORDER BY trade_date DESC" in sql
            self.calls.append(params[0])
            return self.rows.get(params[0], [])

    db = DB({"OGDC": [{"trade_date": "2026-11-16"}]})
    assert bd.latest_price_day(db) == "2026-11-16" and db.calls == ["HBL", "OGDC"]
    assert bd.latest_price_day(DB({})) is None
