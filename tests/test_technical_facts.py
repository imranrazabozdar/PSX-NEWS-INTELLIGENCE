from engines import technical_facts as tf
from scripts import apply_price_table as apt
from scripts import tech_link_sync as sync

STAMP = "2026-11-17T00:00:00Z"


def bars(n=30, last_close=110.0, last_vol=100.0):
    out = [{"symbol": "ABC", "trade_date": f"2026-10-{i + 1:02d}", "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 100.0} for i in range(n - 1)]
    out.append({"symbol": "ABC", "trade_date": "2026-11-16", "open": 100.0, "high": 111.0, "low": 99.0,
                "close": last_close, "volume": last_vol})
    return out


def test_a_big_move_becomes_a_dated_fact_with_volume_context():
    f = tf.price_move_facts("ABC", bars(), "2026-11-01", STAMP)
    assert len(f) == 1
    assert f[0]["topic"] == "price.move" and f[0]["confidence"] == "fact"
    assert "up 10.0%" in f[0]["fact_text"] and f[0]["source_date"] == "2026-11-16"
    assert f[0]["value"] == 10.0 and len(f[0]["fact_text"]) <= 300


def test_quiet_days_make_no_fact_and_heavy_volume_alone_does():
    assert tf.price_move_facts("ABC", bars(last_close=101.0), "2026-11-01", STAMP) == []
    heavy = tf.price_move_facts("ABC", bars(last_close=101.0, last_vol=500.0), "2026-11-01", STAMP)
    assert len(heavy) == 1 and "5.0x" in heavy[0]["fact_text"]


def test_not_enough_history_or_bad_bars_make_no_fact():
    assert tf.price_move_facts("ABC", bars(n=10), "2026-01-01", STAMP) == []
    bad = bars()
    bad[-1]["low"] = 0
    assert tf.price_move_facts("ABC", bad, "2026-11-01", STAMP) == []


def test_signal_facts_are_heuristic_dated_and_never_an_instruction():
    w = tf.wyckoff_fact({"symbol": "ABC", "scan_date": "2026-11-16", "accumulation_score": 72,
                         "signal_type": "BUY_NOW"}, STAMP)
    assert w["confidence"] == "analyst_view" and "unlabelled" in w["fact_text"]
    assert "buy" not in w["fact_text"].lower() and w["source_date"] == "2026-11-16"
    assert tf.wyckoff_fact({"symbol": "ABC", "scan_date": "2026-11-16", "accumulation_score": 20,
                            "signal_type": "NO_SIGNAL"}, STAMP) is None
    assert tf.wyckoff_fact({"symbol": "ABC", "scan_date": "2026-11-16", "accumulation_score": None,
                            "signal_type": "STRONG"}, STAMP) is None
    p = tf.pattern_fact({"symbol": "ABC", "pattern_type": "DOUBLE_BOTTOM", "signal_date": "2026-11-16",
                         "confidence_score": 0.8847}, STAMP)
    assert "double bottom" in p["fact_text"] and "not a probability" in p["fact_text"]
    missing = {"symbol": "ABC", "signal_date": "2026-11-16", "confidence_score": None}
    assert tf.pattern_fact(missing, STAMP) is None


def test_the_price_table_migration_is_exactly_one_create_table():
    assert len(apt.statements(apt.FILE.read_text("utf-8"))) == 1
    for bad in ("DROP TABLE price_daily", "CREATE TABLE IF NOT EXISTS price_daily (a); DROP TABLE x"):
        try:
            apt.statements(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_only_changed_bars_are_written():
    class FakeDB:
        def execute(self, sql, params=()):
            return [{"symbol": "ABC", "trade_date": "2026-11-16", "open": 100.0, "high": 111.0, "low": 99.0,
                     "close": 110.0, "volume": 100.0}]

    same = bars()[-1]
    moved = dict(same, close=105.0, trade_date="2026-11-16")
    assert sync.changed_bars(FakeDB(), [same]) == []
    assert sync.changed_bars(FakeDB(), [moved]) == [moved]
    assert sync.changed_bars(FakeDB(), [dict(same, trade_date="2026-11-17")]) != []


def test_an_idle_check_costs_only_two_one_row_reads():
    class Link:
        calls = 0

        def select_from(self, obj, sql, params=()):
            Link.calls += 1
            assert "LIMIT 1" in sql and obj == "daily_ohlc"
            return [{"trade_date": "2026-11-16"}]

    class Lib:
        def __init__(self, day):
            self.day = day

        def execute(self, sql, params=()):
            assert "LIMIT 1" in sql
            return [{"trade_date": self.day}] if self.day else []

    assert sync.anything_new(Link(), Lib("2026-11-16")) is False
    assert sync.anything_new(Link(), Lib("2026-11-13")) is True
    assert sync.anything_new(Link(), Lib(None)) is True
