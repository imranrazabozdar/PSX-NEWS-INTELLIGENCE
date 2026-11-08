"""Market OHLCV collector (collectors/market_ohlcv.py): offline tests, fake transport, SYNTHETIC bars."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from collectors.engine import CollectionRefused, due_sources
from collectors.http import USER_AGENT, HttpClient
from collectors.market_ohlcv import TIMEFRAMES, collect_market, market_due, parse_udf
from database.connection import SQLiteDatabase
from database.migrate import migrate

NOW = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
D1 = int(datetime(2026, 11, 5, tzinfo=UTC).timestamp())
D2 = int(datetime(2026, 11, 6, tzinfo=UTC).timestamp())


def _udf(t, o, h, lo, c, v, s="ok"):
    return {"s": s, "t": t, "o": o, "h": h, "l": lo, "c": c, "v": v}


class FakeProvider:
    """Records each request (URL and headers) and answers with a configurable UDF payload."""

    def __init__(self, payload):
        self.payload = payload
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.requests.append((url, dict(headers)))
        body = self.payload(url) if callable(self.payload) else self.payload
        return 200, {"content-type": "application/json"}, json.dumps(body).encode()


def _client(provider):
    return HttpClient(transport=provider, sleep=lambda s: None, respect_robots=False)


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    d.execute(
        "INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, updated_at_utc, "
        "feed_url, adapter, access_method, access_status, terms_status, enabled, lifecycle_status, "
        "collection_frequency_minutes) VALUES ('synscs','SYNTHETIC chart feed','data_provider',1,?,?,"
        "'https://chart.example.invalid','udf_ohlcv','authorised_provider','verified_permitted',"
        "'approved',1,'ACTIVE',60)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    yield d
    d.close()


def _daily(close2=11.0):
    return _udf([D1, D2], [10.0, 10.5], [11.0, 11.5], [9.5, 10.0], [10.5, close2], [1000, 2000])


def _run(db, provider, **kw):
    return collect_market(
        db,
        symbols=["SYN"],
        timeframes=["1d"],
        source_id="synscs",
        client=_client(provider),
        now=NOW,
        pause_seconds=0,
        **kw,
    )


# ------------------------------------------------------------------ parsing
def test_parse_valid_and_no_data():
    bars, rej = parse_udf(_daily(), "1d")
    assert rej == 0 and [b["bar_start_utc"] for b in bars] == ["2026-11-05T00:00:00Z", "2026-11-06T00:00:00Z"]
    assert bars[0]["session_date_pkt"] == "2026-11-05"
    assert parse_udf({"s": "no_data"}, "1d") == ([], 0)


def test_parse_rejects_inconsistent_misaligned_and_duplicate_bars():
    t_mis = D2 + 5 * 3600  # a daily bar not at 00:00 UTC
    payload = _udf(
        [D1, D1, D2, t_mis], [10, 10, 10, 10], [11, 11, 9, 11], [9, 9, 9, 9], [10, 10, 10, 10], [1, 1, 1, 1]
    )  # D2: high below open/close
    bars, rej = parse_udf(payload, "1d")
    assert [b["bar_start_utc"] for b in bars] == ["2026-11-05T00:00:00Z"] and rej == 3


@pytest.mark.parametrize("payload", [{"s": "error", "errmsg": "bad symbol"}, {"s": "ok", "t": [1], "o": []}])
def test_parse_refuses_errors_and_malformed_payloads(payload):
    with pytest.raises(ValueError):
        parse_udf(payload, "1m")


def test_pkt_session_date_for_intraday():
    t = int(datetime(2026, 11, 5, 23, 0, tzinfo=UTC).timestamp())  # 04:00 PKT next day
    bars, _ = parse_udf(_udf([t], [1.0], [1.0], [1.0], [1.0], [0]), "1h")
    assert bars[0]["session_date_pkt"] == "2026-11-06"


# ------------------------------------------------------------------ collection
def test_requests_are_honest_and_no_referer_is_sent(db):
    provider = FakeProvider(_daily())
    _run(db, provider)
    url, headers = provider.requests[0]
    assert headers["User-Agent"] == USER_AGENT and "Mozilla" not in USER_AGENT
    assert "Referer" not in headers and "X-Requested-With" not in headers
    assert "/history?symbol=SYN&resolution=D&" in url


def test_insert_then_rerun_is_unchanged_and_incremental(db):
    run1 = _run(db, FakeProvider(_daily()))
    assert run1.status == "succeeded" and run1.series[0].inserted == 2
    provider = FakeProvider(_daily())
    run2 = _run(db, provider)
    assert (run2.series[0].inserted, run2.series[0].unchanged, run2.series[0].corrected) == (0, 2, 0)
    frm = int(provider.requests[0][0].split("from=")[1].split("&")[0])
    assert frm == D2 - 3 * 86400  # resumes from the last stored bar, with overlap
    assert db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"] == 2
    runs = db.execute("SELECT status, items_fetched, items_accepted FROM collector_runs ORDER BY run_id")
    assert [r["status"] for r in runs] == ["succeeded", "succeeded"]


def test_changed_bar_is_recorded_as_correction_not_overwritten(db):
    _run(db, FakeProvider(_daily(close2=11.0)))
    run = _run(db, FakeProvider(_daily(close2=11.25)))
    assert run.series[0].corrected == 1
    assert (
        db.execute("SELECT close FROM market_bars WHERE bar_start_utc = '2026-11-06T00:00:00Z'")[0]["close"]
        == 11.0
    )
    cur = db.execute(
        "SELECT close, correction_count FROM market_bars_current WHERE bar_start_utc = '2026-11-06T00:00:00Z'"
    )[0]
    assert (cur["close"], cur["correction_count"]) == (11.25, 1)


def test_dry_run_writes_nothing(db):
    run = _run(db, FakeProvider(_daily()), dry_run=True)
    assert run.status == "dry_run" and run.series[0].fetched == 2
    assert db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"] == 0
    assert db.execute("SELECT COUNT(*) n FROM collector_runs")[0]["n"] == 0


def test_provider_error_is_visible_and_nothing_is_invented(db):
    run = _run(db, FakeProvider({"s": "error", "errmsg": "unknown symbol"}))
    assert run.status == "failed" and "unknown symbol" in run.series[0].error
    assert db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"] == 0
    assert db.execute("SELECT consecutive_failures c FROM sources WHERE source_id = 'synscs'")[0]["c"] == 1


def test_inactive_source_and_kill_switch_are_refused(db, monkeypatch):
    db.execute("UPDATE sources SET lifecycle_status = 'TESTED', enabled = 0 WHERE source_id = 'synscs'")
    with pytest.raises(CollectionRefused, match="only ACTIVE"):
        _run(db, FakeProvider(_daily()))
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "true")
    with pytest.raises(CollectionRefused, match="KILL_SWITCH"):
        _run(db, FakeProvider(_daily()))


def test_all_four_timeframes_use_their_resolutions(db):
    provider = FakeProvider({"s": "no_data"})
    collect_market(
        db, symbols=["SYN"], source_id="synscs", client=_client(provider), now=NOW, pause_seconds=0
    )
    resolutions = [u.split("resolution=")[1].split("&")[0] for u, _ in provider.requests]
    assert resolutions == [TIMEFRAMES[t][0] for t in ("1m", "1h", "4h", "1d")] == ["1", "60", "240", "D"]


def test_market_source_is_scheduled_separately_from_news(db):
    assert "synscs" not in due_sources(db)  # the news scheduler never picks the market adapter
    assert market_due(db, "synscs", now=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
