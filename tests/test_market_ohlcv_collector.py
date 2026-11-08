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


# ------------------------------------------------------------------ bookkeeping under a write budget
import collectors.market_ohlcv as mo  # noqa: E402
from database.connection import DatabaseBudgetError, DatabaseError  # noqa: E402


class BudgetedSQLite(SQLiteDatabase):
    """SQLite with the Turso client's per-run budget: checked before each request; each bar insert billed as
    3 rows written (table + 2 indexes, as observed on Turso), each UPDATE as 1."""

    def __init__(self, *, max_rows_written, fail_on=None):
        super().__init__()
        self.requests = self.rows_read = self.rows_written = 0
        self.max_requests, self.max_rows_read, self.max_rows_written = 2000, 50_000, max_rows_written
        self.fail_on = fail_on  # callable(statements) -> bool: raise a DatabaseError for that batch

    def usage(self):
        return {"requests": self.requests, "rows_read": self.rows_read, "rows_written": self.rows_written}

    def batch(self, statements, *, transactional=True, rollback=False):
        statements = list(statements)
        if (
            self.requests >= self.max_requests
            or self.rows_read >= self.max_rows_read
            or self.rows_written >= self.max_rows_written
        ):
            raise DatabaseBudgetError(f"per-run database budget exhausted: {self.usage()}")
        self.requests += 1
        if self.fail_on and self.fail_on(statements):
            raise DatabaseError("simulated write failure")
        out = super().batch(statements, transactional=transactional, rollback=rollback)
        for sql, _ in statements:
            head = sql.lstrip().upper()
            self.rows_written += (
                3
                if head.startswith("INSERT INTO MARKET_BAR")
                else 1
                if head.startswith(("INSERT", "UPDATE"))
                else 0
            )
        return out


def _budget_db(max_rows_written, fail_on=None):
    d = BudgetedSQLite(max_rows_written=max_rows_written, fail_on=fail_on)
    migrate(d)
    d.execute(
        "INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, updated_at_utc, "
        "feed_url, adapter, access_method, access_status, terms_status, enabled, lifecycle_status, "
        "collection_frequency_minutes) VALUES ('synscs','SYNTHETIC chart feed','data_provider',1,?,?,"
        "'https://chart.example.invalid','udf_ohlcv','authorised_provider','verified_permitted',"
        "'approved',1,'ACTIVE',60)",
        (NOW.isoformat(), NOW.isoformat()),
    )
    d.rows_written = d.requests = 0  # measure the collection run only
    return d


def _many_daily(n):
    start = D2 - (n - 1) * 86400
    t = [start + i * 86400 for i in range(n)]
    return _udf(t, [10.0] * n, [11.0] * n, [9.0] * n, [10.5] * n, [100] * n)


def _stored(db):
    return db.execute("SELECT COUNT(*) n FROM market_bars")[0]["n"]


def _run_row(db, run):
    return db.execute("SELECT * FROM collector_runs WHERE run_id = ?", (run.run_id,))[0]


def test_budget_exhaustion_stops_cleanly_and_run_is_finalised(monkeypatch):
    monkeypatch.setattr(mo, "CHUNK", 10)
    db = _budget_db(max_rows_written=400)
    run = _run(db, FakeProvider(_many_daily(300)))
    assert run.status == "partial" and run.finalized is True
    assert any("finalisation reserve" in e for e in run.errors)
    row = _run_row(db, run)
    assert row["status"] == "partial" and row["finished_at_utc"] is not None
    assert row["items_accepted"] == _stored(db) == run.series[0].inserted > 0  # counts match storage
    src = db.execute("SELECT last_attempt_at_utc, last_success_at_utc FROM sources WHERE source_id='synscs'")[
        0
    ]
    assert src["last_attempt_at_utc"] and src["last_success_at_utc"]  # health recorded
    assert db.rows_written <= db.max_rows_written  # budget never exceeded


def test_reserve_shrinks_an_oversized_chunk_to_what_fits(monkeypatch):
    monkeypatch.setattr(mo, "CHUNK", 200)
    db = _budget_db(max_rows_written=500)
    run = _run(db, FakeProvider(_many_daily(300)))
    first_fit = (500 - 1 - mo.FINALIZE_RESERVE_ROWS_WRITTEN) // mo.ROWS_WRITTEN_PER_BAR  # 1 = run row insert
    assert first_fit < 200 <= 300                    # a full 200-bar chunk would not have fitted
    assert first_fit <= _stored(db) < 300            # shrunk chunks were written, then the run stopped
    assert run.series[0].inserted == _stored(db) and run.status == "partial" and run.finalized is True
    assert db.rows_written <= db.max_rows_written


def test_inserted_counts_only_successful_batches(monkeypatch):
    monkeypatch.setattr(mo, "CHUNK", 10)
    calls = {"bar_batches": 0}

    def fail_second_bar_batch(stmts):
        if stmts and stmts[0][0].lstrip().upper().startswith("INSERT INTO MARKET_BARS"):
            calls["bar_batches"] += 1
            return calls["bar_batches"] == 2
        return False

    db = _budget_db(max_rows_written=100_000, fail_on=fail_second_bar_batch)
    run = _run(db, FakeProvider(_many_daily(30)))
    s = run.series[0]
    assert s.error and "simulated write failure" in s.error  # failure visible per series
    assert s.inserted == _stored(db) == 10  # only the committed chunk
    assert run.status == "failed" and run.finalized is True
    assert _run_row(db, run)["items_accepted"] == 10
    assert db.execute("SELECT consecutive_failures c FROM sources WHERE source_id='synscs'")[0]["c"] == 1


def test_corrections_are_counted_after_their_batch_commits():
    db = _budget_db(max_rows_written=100_000)
    _run(db, FakeProvider(_daily(close2=11.0)))
    run = _run(db, FakeProvider(_daily(close2=11.25)))
    assert run.series[0].corrected == db.execute("SELECT COUNT(*) n FROM market_bar_corrections")[0]["n"] == 1


def test_failed_finalisation_is_reported_not_swallowed(monkeypatch):
    def fail_bookkeeping(stmts):
        final = "UPDATE COLLECTOR_RUNS SET FINISHED_AT_UTC"
        return any(sql.lstrip().upper().startswith(final) for sql, _ in stmts)

    db = _budget_db(max_rows_written=100_000, fail_on=fail_bookkeeping)
    run = _run(db, FakeProvider(_daily()))
    assert run.finalized is False
    assert any("bookkeeping could not be written" in e for e in run.errors)
    monkeypatch.setattr("database.connection.connect", lambda: db)
    monkeypatch.setattr(mo, "collect_market", lambda *a, **k: run)
    assert mo.main(["--symbols", "SYN", "--timeframes", "1d"]) == 1  # non-zero exit in Actions
