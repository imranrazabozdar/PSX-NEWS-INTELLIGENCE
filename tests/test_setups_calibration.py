from datetime import date, timedelta

from engines import setups_calibration as sc


def test_spearman_and_ranks_handle_ties_and_edges():
    assert sc.ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert sc.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0
    assert sc.spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0
    assert sc.spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None  # no spread: unknown, not zero
    assert sc.spearman([1, 2], [1, 2]) is None  # too few


def make_bars(n_stocks=30, n_days=90, momentum=True):
    start = date(2026, 6, 1)
    out = {}
    for s in range(n_stocks):
        rows = []
        px = 100.0
        drift = (s - n_stocks / 2) * 0.05  # each stock has a steady drift: momentum persists
        for d in range(n_days):
            px *= 1 + (drift if momentum else -drift) / 100
            rows.append(
                {
                    "trade_date": (start + timedelta(days=d)).isoformat(),
                    "close": px,
                    "volume": 2_000_000.0,
                }
            )
        out[f"S{s:02d}"] = rows
    return out


def test_a_persistent_trend_is_found_and_a_reversal_is_found_as_negative():
    up = sc.run(make_bars(momentum=True), horizons=(5,))
    ic_up = sum(up["horizons"][5]["ic"]) / len(up["horizons"][5]["ic"])
    assert ic_up > 0.3 and sum(up["horizons"][5]["excess"]) > 0
    # drift sign flips every stock's trend but scoring still ranks by past trend: forward is the same
    # direction, so a market where past winners later lose needs the trend to reverse
    bars = make_bars()
    for rows in bars.values():  # reverse the second half: past winners become losers
        half = len(rows) // 2
        for i in range(half, len(rows)):
            rows[i]["close"] = rows[half]["close"] ** 2 / rows[i]["close"]
    rev = sc.run(bars, horizons=(5,))
    assert min(rev["horizons"][5]["ic"]) < 0


def test_report_states_its_limits_and_shows_unknowns_as_n_a():
    text = sc.report(
        {
            "horizons": {1: {"excess": [], "beat": [], "ic": []}},
            "item_ic": {1: {k: [] for k, _ in sc.setups.TECH_ITEMS}},
            "days_scored": 0,
        }
    )
    assert "Indicative only" in text and "n/a" in text and "overlapping" in text
