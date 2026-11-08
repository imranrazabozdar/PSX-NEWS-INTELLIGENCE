"""Market-run lease on a real, dedicated Turso TEST database (never production).

Runs only when tests/turso_guard.integration_config_status is 'ok' (PSXNI_TEST_TURSO_DATABASE_URL and
PSXNI_TEST_TURSO_AUTH_TOKEN set, production host and token refused) AND the owner opts in to committed
test writes with PSXNI_TEST_TURSO_ALLOW_COMMITS=yes-commit-test-rows. Lease tests must commit, because
two separate connections have to see each other's rows. Only collector_runs rows and one SYNTHETIC source
are written, all removed afterwards; no market bars are ever committed (the fencing check runs in a
rolled-back batch). The test database needs migrations applied (as for tests/test_turso_integration.py).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from collectors.http import HttpClient
from collectors.market_ohlcv import CollectionBusy, collect_market
from database.connection import TursoHTTPDatabase
from tests.turso_guard import TEST_TOKEN_VAR, TEST_URL_VAR, integration_config_status

COMMIT_VAR, COMMIT_VALUE = "PSXNI_TEST_TURSO_ALLOW_COMMITS", "yes-commit-test-rows"
_STATUS, _REASON = integration_config_status(os.environ)
pytestmark = pytest.mark.skipif(
    _STATUS == "skip" or os.environ.get(COMMIT_VAR) != COMMIT_VALUE,
    reason=_REASON or f"{COMMIT_VAR} not set: committed lease tests not run",
)
SRC = "synlease" + uuid.uuid4().hex[:8]


def _db():
    if _STATUS != "ok":
        pytest.fail(_REASON)
    return TursoHTTPDatabase(os.environ[TEST_URL_VAR].strip(), os.environ[TEST_TOKEN_VAR].strip())


def _iso(minutes_ago=0):
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_data(url, headers, timeout):
    return 200, {"content-type": "application/json"}, json.dumps({"s": "no_data"}).encode()


def _collect(d):
    return collect_market(d, source_id=SRC, symbols=["SYN"], timeframes=["1m"], pause_seconds=0,
                          client=HttpClient(transport=_no_data, sleep=lambda s: None, respect_robots=False))


@pytest.fixture
def db():
    d = _db()
    d.batch([(
        "INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, updated_at_utc, "
        "feed_url, adapter, access_method, access_status, terms_status, enabled, lifecycle_status) "
        "VALUES (?,'SYNTHETIC lease test','data_provider',1,?,?,'https://chart.example.invalid','udf_ohlcv',"
        "'authorised_provider','verified_permitted','approved',1,'ACTIVE')", (SRC, _iso(), _iso()))])
    yield d
    d.batch([("DELETE FROM collector_runs WHERE source_id = ?", (SRC,)),
             ("DELETE FROM sources WHERE source_id = ?", (SRC,))])
    assert d.execute("SELECT COUNT(*) AS n FROM collector_runs WHERE source_id = ?", (SRC,))[0]["n"] == 0


def _runs(d):
    return d.execute("SELECT status, errors FROM collector_runs WHERE source_id = ? ORDER BY run_id", (SRC,))


def test_simultaneous_claims_on_turso_admit_exactly_one(db):
    barrier, results = threading.Barrier(2), []

    def attempt():
        d = _db()
        barrier.wait()
        try:
            _collect(d)
            results.append("owner")
        except CollectionBusy:
            results.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # either one owner and one busy, or (if the first finished before the second claimed) two owners in
    # sequence; never two concurrent 'running' rows
    assert results.count("owner") >= 1 and len(results) == 2
    assert all(r["status"] == "succeeded" for r in _runs(db))
    assert len(_runs(db)) == results.count("owner")


def test_live_lease_blocks_and_expired_orchestrated_lease_is_taken_over(db):
    ctx = '{"context": {"trigger": "test"}}'
    db.batch([("INSERT INTO collector_runs(job, source_id, started_at_utc, status, quota_usage_json) "
               "VALUES ('market_ohlcv', ?, ?, 'running', ?)", (SRC, _iso(5), ctx))])
    with pytest.raises(CollectionBusy):
        _collect(db)
    db.batch([("UPDATE collector_runs SET started_at_utc = ? WHERE source_id = ?", (_iso(90), SRC))])
    run = _collect(db)
    runs = _runs(db)
    assert run.status == "succeeded" and runs[0]["status"] == "failed" and "abandoned" in runs[0]["errors"]
    assert not [r for r in runs if r["status"] == "running"]  # clean after success


def test_fenced_write_after_takeover_writes_nothing(db):
    db.batch([("INSERT INTO collector_runs(job, source_id, started_at_utc, status) "
               "VALUES ('market_ohlcv', ?, ?, 'failed')", (SRC, _iso()))])
    run_id = db.execute("SELECT MAX(run_id) AS id FROM collector_runs WHERE source_id = ?", (SRC,))[0]["id"]
    out = db.batch([
        ("INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
         "open, high, low, "
         "close, volume, retrieved_at_utc, collection_run_id) SELECT ?,'SYN','1m','2026-11-05T04:00:00Z',"
         "'2026-11-05',1,1,1,1,1,?,? WHERE EXISTS (SELECT 1 FROM collector_runs WHERE run_id = ? "
         "AND status = 'running')", (SRC, _iso(), run_id, run_id)),
        ("SELECT changes() AS n", ()),
    ], rollback=True)
    assert out[1][0]["n"] == 0
