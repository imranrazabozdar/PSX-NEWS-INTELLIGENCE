"""Market collection orchestration: one coordinated decision about whether, why and how often to run.

Responsibilities (collectors.market_ohlcv does the fetching and storing; this module only coordinates):
* Recovery: an orchestrated market run left 'running' past its lease (process killed, job timed out) is
  finalised as 'failed' with an explicit reason; started_at and counts are kept. Legacy runs without run
  context (production run 11) are never changed automatically: they are only reported, and are cleaned
  up by the owner-approved procedure in docs/COLLECTION_ORCHESTRATION.md.
* Fencing: bar writes are conditional on the run still holding its lease, so a taken-over run cannot
  write after the takeover, and its finalisation cannot overwrite the recovery record.
* Due decision, in order: source ACTIVE and enabled; daily run cap not reached; a continuation is due
  at once when the previous run stopped at the per-run database budget; otherwise the source's
  collection interval must have elapsed, lengthened by exponential backoff after consecutive failures.
* Controlled continuation: after a budget-stopped run, start another run with a FRESH connection (so a
  fresh per-run budget of the same size; the budget itself is never raised), up to max_passes per
  invocation and the daily cap. It stops when a run completes, fails, makes no progress, is refused or
  another run holds the lease.
* Trigger tracking: every run records its trigger origin (schedule / external / manual), GitHub run id,
  pass number and reason in collector_runs.quota_usage_json, with the database usage it consumed.

No schema change: uses collector_runs and sources only. Duplicate triggers are safe: the lease admits
one writer, the due check turns later triggers into no-ops, and bar writes are idempotent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from collectors.engine import CollectionRefused
from collectors.market_ohlcv import (
    DEFAULT_LEASE_MINUTES,
    JOB,
    SOURCE_ID,
    CollectionBusy,
    collect_market,
)
from database.connection import Database

DEFAULT_MAX_PASSES = 3
DEFAULT_MAX_RUNS_PER_DAY = 12
MAX_BACKOFF_EXPONENT = 4  # interval x 16 at most


def _env_int(env: dict, name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(env.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class Limits:
    max_passes: int = DEFAULT_MAX_PASSES
    max_runs_per_day: int = DEFAULT_MAX_RUNS_PER_DAY
    lease_minutes: int = DEFAULT_LEASE_MINUTES

    @classmethod
    def from_env(cls, env: dict | None = None) -> Limits:
        env = os.environ if env is None else env
        return cls(
            max_passes=_env_int(env, "PSXNI_MARKET_MAX_PASSES", DEFAULT_MAX_PASSES, 1, 6),
            max_runs_per_day=_env_int(env, "PSXNI_MARKET_MAX_RUNS_PER_DAY", DEFAULT_MAX_RUNS_PER_DAY, 1, 48),
            lease_minutes=_env_int(env, "PSXNI_MARKET_LEASE_MINUTES", DEFAULT_LEASE_MINUTES, 25, 240),
        )


def trigger_context(trigger: str | None = None, env: dict | None = None) -> dict:
    """Trigger origin from the CLI flag or the GitHub event; never includes tokens or secrets."""
    env = os.environ if env is None else env
    event = env.get("GITHUB_EVENT_NAME", "")
    origin = (trigger or env.get("PSXNI_TRIGGER") or "").strip().lower()
    if origin not in ("schedule", "external", "manual"):
        origin = "schedule" if event == "schedule" else "manual"
    ctx = {"trigger": origin}
    if env.get("GITHUB_RUN_ID", "").isdigit():
        ctx["github_run_id"] = int(env["GITHUB_RUN_ID"])
    return ctx


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_trigger(db: Database, context: dict, now: datetime, source_id: str = SOURCE_ID) -> None:
    """Heartbeat: the last time each trigger origin invoked market collection (even when nothing was
    due), in the market source's collector_checkpoints.cursor JSON. One row written per invocation."""
    origin = context.get("trigger", "manual")
    db.batch(
        [
            (
                "INSERT INTO collector_checkpoints(source_id, endpoint_url, cursor, updated_at_utc) "
                "SELECT source_id, COALESCE(feed_url, ''), json_object(?, json_object('at', ?, "
                "'github_run_id', ?)), ? FROM sources WHERE source_id = ? "
                "ON CONFLICT(source_id) DO UPDATE SET cursor = json_set(COALESCE(CASE WHEN "
                "json_valid(collector_checkpoints.cursor) THEN collector_checkpoints.cursor END, '{}'), "
                "'$.' || ?, json(json_extract(excluded.cursor, '$.' || ?))), "
                "updated_at_utc = excluded.updated_at_utc",
                (origin, _iso(now), context.get("github_run_id"), _iso(now), source_id, origin, origin),
            )
        ]
    )


def last_triggers(db: Database, source_id: str = SOURCE_ID) -> dict:
    """{origin: {at, github_run_id}} from the heartbeat, e.g. for the operations view."""
    rows = db.execute("SELECT cursor FROM collector_checkpoints WHERE source_id = ?", (source_id,))
    try:
        return json.loads(rows[0]["cursor"]) if rows and rows[0]["cursor"] else {}
    except ValueError:
        return {}


def recover_abandoned(db: Database, now: datetime, lease_minutes: int, source_id: str = SOURCE_ID) -> int:
    """Finalise market runs left 'running' beyond the lease as failed. Returns how many were recovered."""
    cutoff = _iso(now - timedelta(minutes=lease_minutes))
    rows = db.batch(
        [
            (
                "UPDATE collector_runs SET status = 'failed', finished_at_utc = ?, errors = "
                "substr(COALESCE(errors || char(10), '') || 'abandoned: still running after the lease "
                "expired (process ended before finalising)', 1, 2000) "
                "WHERE job = ? AND source_id = ? AND status = 'running' AND started_at_utc < ? "
                "AND json_extract(quota_usage_json, '$.context') IS NOT NULL",
                (_iso(now), JOB, source_id, cutoff),
            ),
            ("SELECT changes() AS n", ()),
        ]
    )
    return int(rows[1][0]["n"] or 0)


def legacy_stale_runs(
    db: Database, now: datetime, lease_minutes: int, source_id: str = SOURCE_ID
) -> list[int]:
    """Runs left 'running' by pre-orchestration code: reported, never changed automatically."""
    cutoff = _iso(now - timedelta(minutes=lease_minutes))
    return [
        r["run_id"]
        for r in db.execute(
            "SELECT run_id FROM collector_runs WHERE job = ? AND source_id = ? AND status = 'running' "
            "AND started_at_utc < ? AND json_extract(quota_usage_json, '$.context') IS NULL "
            "ORDER BY run_id",
            (JOB, source_id, cutoff),
        )
    ]


@dataclass
class Decision:
    run: bool
    reason: str


def decide(db: Database, now: datetime, limits: Limits, source_id: str = SOURCE_ID) -> Decision:
    src = db.execute(
        "SELECT lifecycle_status, enabled, last_attempt_at_utc, consecutive_failures, "
        "COALESCE(collection_frequency_minutes, 60) AS freq FROM sources WHERE source_id = ?",
        (source_id,),
    )
    if not src or src[0]["lifecycle_status"] != "ACTIVE" or not src[0]["enabled"]:
        return Decision(False, "market source not ACTIVE or not enabled")
    s = src[0]
    day = _iso(now)[:10]
    today = db.execute(
        "SELECT COUNT(*) AS n FROM collector_runs WHERE job = ? AND source_id = ? "
        "AND status <> 'dry_run' AND started_at_utc >= ?",
        (JOB, source_id, day + "T00:00:00Z"),
    )[0]["n"]
    if today >= limits.max_runs_per_day:
        return Decision(False, f"daily run cap reached ({today}/{limits.max_runs_per_day})")
    last = db.execute(
        "SELECT status, quota_usage_json FROM collector_runs WHERE job = ? AND source_id = ? "
        "AND status NOT IN ('dry_run', 'running') ORDER BY run_id DESC LIMIT 1",
        (JOB, source_id),
    )
    if last and last[0]["status"] == "partial":
        try:
            meta = json.loads(last[0]["quota_usage_json"] or "{}")
        except ValueError:
            meta = {}
        if meta.get("budget_stopped") and not meta.get("series_errors"):
            return Decision(True, "continuation: previous run stopped at the per-run budget")
    failures = int(s["consecutive_failures"] or 0)
    interval = int(s["freq"]) * 2 ** min(failures, MAX_BACKOFF_EXPONENT)
    if s["last_attempt_at_utc"]:
        last_at = datetime.strptime(s["last_attempt_at_utc"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        if now - last_at < timedelta(minutes=interval):
            backoff = f" (backoff after {failures} failures)" if failures else ""
            return Decision(False, f"not due: interval {interval} min{backoff}")
    return Decision(True, "due: interval elapsed" + (f" (after {failures} failures)" if failures else ""))


def orchestrate(
    connect_fn: Callable[[], Database],
    *,
    context: dict | None = None,
    limits: Limits | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    source_id: str = SOURCE_ID,
    **collect_kwargs,
) -> dict:
    """Run due market collection with bounded continuation. Returns a summary with an exit code."""
    limits = limits or Limits.from_env()
    passes: list[dict] = []
    recovered = 0
    legacy: list[int] = []
    stop = "max passes reached"
    exit_code = 0
    for i in range(limits.max_passes):
        db = connect_fn()  # a fresh connection carries a fresh per-run budget of the same configured size
        try:
            now = now_fn()
            recovered += recover_abandoned(db, now, limits.lease_minutes, source_id)
            if i == 0:
                record_trigger(db, context or {}, now, source_id)
                legacy = legacy_stale_runs(db, now, limits.lease_minutes, source_id)
            d = decide(db, now, limits, source_id)
            if not d.run:
                stop = d.reason
                break
            ctx = {**(context or {}), "pass": i + 1, "reason": d.reason}
            try:
                run = collect_market(
                    db, source_id=source_id, context=ctx, lease_minutes=limits.lease_minutes, **collect_kwargs
                )
            except CollectionBusy as exc:
                stop = str(exc)
                break
            except CollectionRefused as exc:
                stop, exit_code = f"refused: {exc}", 2
                break
            passes.append(run.as_dict())
            progress = sum(s.inserted + s.corrected for s in run.series)
            if run.status == "failed" or run.finalized is False:
                stop, exit_code = f"run {run.run_id} {run.status}; finalised={run.finalized}", 1
                break
            if not run.budget_stopped:
                stop = f"run {run.run_id} {run.status}: no budget-limited work remains"
                break
            if progress == 0:
                stop = f"run {run.run_id} made no progress; not continuing"
                break
        finally:
            db.close()
    return {
        "job": JOB,
        "context": context or {},
        "limits": vars(limits),
        "recovered_abandoned_runs": recovered,
        "legacy_stale_runs_needing_owner_cleanup": legacy,
        "passes": passes,
        "stop_reason": stop,
        "exit_code": exit_code,
    }
