"""Stage 4: trigger origin, trigger heartbeat, missed/late schedule detection, workflow contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from collectors.market_orchestrator import Limits, last_triggers, orchestrate, record_trigger
from collectors.schedule_health import assess, expected_slots
from tests.test_market_orchestration import NOW, SRC, Provider, _orch, db  # noqa: F401 (fixture)

WF = Path(__file__).resolve().parents[1] / ".github/workflows/scheduled-jobs.yml"


def test_trigger_heartbeat_keeps_each_origin_separately(db):  # noqa: F811
    record_trigger(db, {"trigger": "schedule", "github_run_id": 1}, NOW, SRC)
    record_trigger(db, {"trigger": "external", "github_run_id": 2}, NOW, SRC)
    record_trigger(db, {"trigger": "external", "github_run_id": 3}, NOW, SRC)
    t = last_triggers(db, SRC)
    assert t["schedule"]["github_run_id"] == 1 and t["external"]["github_run_id"] == 3
    assert db.execute("SELECT COUNT(*) AS n FROM collector_checkpoints")[0]["n"] == 1


def test_not_due_invocations_are_still_seen_and_write_no_run(db):  # noqa: F811
    _orch(db, Provider(n=20))
    runs = db.execute("SELECT COUNT(*) AS n FROM collector_runs")[0]["n"]
    out = _orch(db, Provider(n=20), context={"trigger": "external", "github_run_id": 9})
    assert out["passes"] == [] and db.execute("SELECT COUNT(*) AS n FROM collector_runs")[0]["n"] == runs
    assert last_triggers(db, SRC)["external"]["github_run_id"] == 9


def test_duplicate_external_dispatch_while_a_run_holds_the_lease_does_nothing(db):  # noqa: F811
    db.execute("INSERT INTO collector_runs(job, source_id, started_at_utc, status, quota_usage_json) "
               "VALUES ('market_ohlcv', ?, ?, 'running', '{\"context\": {}}')",
               (SRC, NOW.strftime("%Y-%m-%dT%H:%M:%SZ")))
    out = orchestrate(db.connect, context={"trigger": "external"}, limits=Limits(), now_fn=lambda: NOW,
                      source_id=SRC, symbols=["SYN"], timeframes=["1m"], now=NOW, pause_seconds=0)
    assert "holds the lease" in out["stop_reason"] and not db.execute("SELECT 1 FROM market_bars")


def test_schedule_slots_and_classification():
    now = datetime(2026, 11, 9, 13, 0, tzinfo=UTC)
    slots = expected_slots(datetime(2026, 11, 8, 13, 0, tzinfo=UTC), now)
    assert [s.hour for s in slots] == [18, 0, 6, 12]
    # observed 2026-11-08 style: 69 min late, one slot skipped, current slot not yet started
    rep = assess(["2026-11-08T19:26:11Z", "2026-11-09T06:20:00Z"], now, lookback_hours=24)
    assert [(r["slot_utc"][11:16], r["status"]) for r in rep] == [
        ("18:17", "late"), ("00:17", "missed"), ("06:17", "on_time"), ("12:17", "pending")]
    assert rep[0]["delay_minutes"] == 69


def test_workflow_records_trigger_origin_and_keeps_cron_and_concurrency():
    text = WF.read_text()
    assert '- cron: "17 */6 * * *"' in text  # GitHub cron stays as the fallback
    assert "      trigger:\n" in text and "options: [manual, external]" in text and "default: manual" in text
    assert "group: scheduled-collection\n  cancel-in-progress: false" in text
    assert "PSXNI_TRIGGER: ${{ github.event_name == 'schedule' && 'schedule' || inputs.trigger }}" in text
    assert 'margs=(--due --trigger "$PSXNI_TRIGGER")' in text
    assert "permissions:\n  contents: read\n" in text
    assert "echo $PSXNI_TURSO" not in text and "set -x" not in text
