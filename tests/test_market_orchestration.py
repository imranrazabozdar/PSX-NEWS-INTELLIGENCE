"""Market collection orchestration (collectors/market_orchestrator.py): lease, recovery, due decision,
backoff, bounded continuation and backfill priority. Offline: local SQLite, fake provider, SYNTHETIC bars."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from collectors.http import HttpClient
from collectors.market_ohlcv import (
    CollectionBusy,
    CollectionRefused,
    collect_market,
    ordered_series,
    timeframe_priority,
)
from collectors.market_orchestrator import Limits, decide, orchestrate, recover_abandoned, trigger_context
from database.migrate import migrate
from tests.test_market_ohlcv_collector import BudgetedSQLite

# Run bookkeeping is stamped with the real clock, so the test clock is "now" (to the minute).
NOW = datetime.now(UTC).replace(second=0, microsecond=0)
BASE = int((NOW - timedelta(days=2)).timestamp())
SRC = "synscs"


class SharedDB(BudgetedSQLite):
    """One persistent SQLite database; each 'connection' gets a fresh per-run budget of the same size."""

    def connect(self):
        self.requests = self.rows_read = self.rows_written = 0
        return self

    def close(self):  # the shared database outlives each pass
        pass


class Provider:
    """SYNTHETIC 1-minute bars honouring from/to; optional per-symbol failure."""

    def __init__(self, n=600, fail=()):
        self.n, self.fail, self.urls = n, set(fail), []

    def __call__(self, url, headers, timeout):
        self.urls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        if q["symbol"] in self.fail:
            return 503, {}, b"unavailable"
        ts = [t for t in (BASE + 60 * i for i in range(self.n)) if int(q["from"]) <= t <= int(q["to"])]
        body = {"s": "ok" if ts else "no_data", "t": ts, "o": [10.0] * len(ts), "h": [11.0] * len(ts),
                "l": [9.0] * len(ts), "c": [10.5] * len(ts), "v": [100] * len(ts)}
        return 200, {"content-type": "application/json"}, json.dumps(body).encode()


@pytest.fixture
def db():
    d = SharedDB(max_rows_written=1000)
    migrate(d)
    d.execute(
        "INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, updated_at_utc, "
        "feed_url, adapter, access_method, access_status, terms_status, enabled, lifecycle_status, "
        "collection_frequency_minutes) VALUES (?,'SYNTHETIC chart feed','data_provider',1,?,?,"
        "'https://chart.example.invalid','udf_ohlcv','authorised_provider','verified_permitted',"
        "'approved',1,'ACTIVE',60)",
        (SRC, NOW.isoformat(), NOW.isoformat()),
    )
    yield d
    SharedDB.__mro__[2].close(d)


def _orch(db, provider, *, limits=None, symbols=("SYN",), now=NOW, context=None):
    return orchestrate(
        db.connect, context=context or {"trigger": "manual"}, limits=limits or Limits(), now_fn=lambda: now,
        source_id=SRC, symbols=list(symbols), timeframes=["1m"], now=now,
        client=HttpClient(transport=provider, sleep=lambda s: None, respect_robots=False), pause_seconds=0,
    )


def _ago(minutes):
    return (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runs(db):
    return db.execute("SELECT run_id, status, errors, quota_usage_json FROM collector_runs ORDER BY run_id")


def _bars(db):
    return db.execute("SELECT COUNT(*) AS n FROM market_bars")[0]["n"]


# ------------------------------------------------------------------ priority
def test_short_retention_1m_is_collected_for_every_symbol_first(monkeypatch):
    monkeypatch.delenv("PSXNI_MARKET_TIMEFRAME_PRIORITY", raising=False)
    order = ordered_series(["OGDC", "HBL"], ["1d", "4h", "1h", "1m"])
    assert order[:2] == [("OGDC", "1m"), ("HBL", "1m")] and order[-1] == ("HBL", "1d")


def test_priority_is_configurable_and_invalid_values_are_refused(monkeypatch):
    monkeypatch.setenv("PSXNI_MARKET_TIMEFRAME_PRIORITY", "1h,1m")
    assert timeframe_priority() == ("1h", "1m", "4h", "1d")
    monkeypatch.setenv("PSXNI_MARKET_TIMEFRAME_PRIORITY", "1m,5m")
    with pytest.raises(CollectionRefused):
        timeframe_priority()


# ------------------------------------------------------------------ continuation and budget
def test_budget_stop_continues_automatically_and_stops_when_done(db):
    out = _orch(db, Provider(n=900))
    passes = out["passes"]
    assert len(passes) == 3 and [p["budget_stopped"] for p in passes] == [True, True, False]
    assert passes[1]["context"]["reason"].startswith("continuation") and passes[1]["context"]["pass"] == 2
    assert all(p["usage"]["rows_written"] <= 1000 - 50 for p in passes)  # reserve kept every pass
    assert _bars(db) == 900 == sum(s["inserted"] for p in passes for s in p["series"])
    assert [r["status"] for r in _runs(db)] == ["partial", "partial", "succeeded"]
    assert "no budget-limited work remains" in out["stop_reason"] and out["exit_code"] == 0
    meta = json.loads(_runs(db)[0]["quota_usage_json"])
    assert meta["budget_stopped"] and meta["context"]["trigger"] == "manual"


def test_continuation_is_bounded_by_max_passes_and_daily_cap(db):
    out = _orch(db, Provider(n=5000), limits=Limits(max_passes=2))
    assert len(out["passes"]) == 2 and out["stop_reason"] == "max passes reached"
    out = _orch(db, Provider(n=5000), limits=Limits(max_passes=3, max_runs_per_day=3))
    assert len(out["passes"]) == 1 and out["stop_reason"].startswith("daily run cap reached (3/3)")
    assert len(_runs(db)) == 3


def test_resumes_from_stored_bars_and_never_rewrites_completed_history(db):
    p = Provider(n=300)
    _orch(db, p)
    before = _bars(db)
    later = NOW + timedelta(hours=2)
    out = _orch(db, p, now=later)
    s = out["passes"][0]["series"][0]
    assert _bars(db) == before == 300 and s["inserted"] == 0 and s["unchanged"] == 4  # overlap only
    assert int(parse_qs(urlparse(p.urls[-1]).query)["from"][0]) >= BASE + 60 * 296


def test_duplicate_trigger_is_a_no_op_when_nothing_is_due(db):
    _orch(db, Provider(n=100))
    runs = len(_runs(db))
    out = _orch(db, Provider(n=100), context={"trigger": "schedule"})
    assert out["passes"] == [] and out["stop_reason"].startswith("not due") and len(_runs(db)) == runs


# ------------------------------------------------------------------ lease and recovery
def test_a_live_lease_blocks_a_second_writer(db):
    db.execute("INSERT INTO collector_runs(job, source_id, started_at_utc, status) "
               "VALUES ('market_ohlcv', ?, ?, 'running')", (SRC, _ago(10)))
    out = _orch(db, Provider(n=100))
    assert out["passes"] == [] and "holds the lease" in out["stop_reason"] and _bars(db) == 0
    with pytest.raises(CollectionBusy):
        collect_market(db, source_id=SRC, symbols=["SYN"], timeframes=["1m"], now=NOW, pause_seconds=0,
                       client=HttpClient(transport=Provider(), sleep=lambda s: None, respect_robots=False))


def test_abandoned_run_is_finalised_as_failed_then_work_resumes(db):
    db.execute("INSERT INTO collector_runs(job, source_id, started_at_utc, status) "
               "VALUES ('market_ohlcv', ?, ?, 'running')", (SRC, _ago(120)))
    db.execute("INSERT INTO collector_runs(job, source_id, started_at_utc, status) "  # other jobs untouched
               "VALUES ('news', ?, ?, 'running')", (SRC, _ago(120)))
    out = _orch(db, Provider(n=100))
    runs = _runs(db)
    assert out["recovered_abandoned_runs"] == 1 and runs[0]["status"] == "failed"
    assert "abandoned" in runs[0]["errors"] and runs[1]["status"] == "running"
    assert runs[2]["status"] == "succeeded" and _bars(db) == 100
    assert recover_abandoned(db, NOW, 30, SRC) == 0  # idempotent


# ------------------------------------------------------------------ failures and backoff
def test_provider_failure_fails_the_run_without_continuation(db):
    out = _orch(db, Provider(fail={"SYN"}))
    assert len(out["passes"]) == 1 and out["exit_code"] == 1 and _runs(db)[0]["status"] == "failed"


def test_one_symbol_failing_is_isolated_and_not_retried_immediately(db):
    out = _orch(db, Provider(n=50, fail={"BAD"}), symbols=("BAD", "SYN"))
    p = out["passes"][0]
    assert p["status"] == "partial" and not p["budget_stopped"] and _bars(db) == 50
    assert not decide(db, NOW + timedelta(minutes=5), Limits(), SRC).run


def test_consecutive_failures_back_off_exponentially(db):
    db.execute("UPDATE sources SET consecutive_failures = 2, last_attempt_at_utc = ? WHERE source_id = ?",
               (_ago(120), SRC))
    d = decide(db, NOW, Limits(), SRC)
    assert not d.run and "interval 240 min" in d.reason and "backoff" in d.reason
    assert decide(db, NOW + timedelta(hours=2), Limits(), SRC).run


def test_inactive_source_is_never_run(db):
    db.execute("UPDATE sources SET lifecycle_status = 'DISABLED' WHERE source_id = ?", (SRC,))
    assert _orch(db, Provider())["stop_reason"].startswith("market source not ACTIVE")


# ------------------------------------------------------------------ trigger origin and limits
def test_trigger_context_records_origin_without_secrets():
    env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_RUN_ID": "42", "PSXNI_TURSO_AUTH_TOKEN": "x"}
    assert trigger_context(None, env) == {"trigger": "schedule", "github_run_id": 42}
    assert trigger_context("external", {"GITHUB_EVENT_NAME": "workflow_dispatch"})["trigger"] == "external"
    assert trigger_context("bogus", {"GITHUB_EVENT_NAME": "workflow_dispatch"}) == {"trigger": "manual"}


def test_limits_are_clamped_and_the_budget_is_not_configurable_here():
    lim = Limits.from_env({"PSXNI_MARKET_MAX_PASSES": "99", "PSXNI_MARKET_MAX_RUNS_PER_DAY": "0",
                           "PSXNI_MARKET_LEASE_MINUTES": "1"})
    assert (lim.max_passes, lim.max_runs_per_day, lim.lease_minutes) == (6, 1, 25)
    assert "rows" not in " ".join(vars(lim))
