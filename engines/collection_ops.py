"""Collection operations data for the dashboard: run outcomes, triggers, backfill progress, completeness.

Read-only. Every value comes from collector_runs, sources, collector_checkpoints (trigger heartbeat) and
market_bars via indexed lookups. Nothing is estimated or invented: a value that is not recorded is shown
as not recorded.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

from collectors.market_ohlcv import JOB, SOURCE_ID, TIMEFRAMES
from collectors.market_orchestrator import last_triggers
from engines.market_quality import assess, coverage_summary

SCHEDULE_EVERY = timedelta(hours=6)
SCHEDULE_LATE = timedelta(minutes=30)
EXTERNAL_EXPECTED = timedelta(hours=3)  # documented in docs/EXTERNAL_DISPATCH.md


def _meta(row: dict) -> dict:
    try:
        return json.loads(row.get("quota_usage_json") or "{}") or {}
    except ValueError:
        return {}


def run_outcome(row: dict) -> str:
    """A plain label that keeps complete, partial and failed runs apart."""
    st, meta = row["status"], _meta(row)
    if st == "succeeded":
        return "Complete"
    if st == "partial":
        if meta.get("budget_stopped") and not meta.get("series_errors"):
            return "Partial: budget reached, continuing"
        return "Partial: some series failed"
    if st == "running":
        return "Running" if "context" in meta else "Stale legacy record (owner cleanup pending)"
    return {"failed": "Failed", "dry_run": "Dry run (nothing written)"}.get(st, st)


def recent_runs(db, limit: int = 30) -> list[dict]:
    rows = db.execute(
        "SELECT run_id, job, source_id, started_at_utc, finished_at_utc, status, items_fetched, "
        "items_accepted, items_rejected, http_requests, errors, quota_usage_json FROM collector_runs "
        "ORDER BY run_id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        meta = _meta(r)
        ctx, usage = meta.get("context") or {}, meta.get("usage_before_finalise") or {}
        out.append({
            "run_id": r["run_id"], "job": r["job"], "source": r["source_id"], "outcome": run_outcome(r),
            "trigger": ctx.get("trigger", "not recorded"), "pass": ctx.get("pass"),
            "github_run_id": ctx.get("github_run_id"), "started_utc": r["started_at_utc"],
            "finished_utc": r["finished_at_utc"], "fetched": r["items_fetched"],
            "accepted": r["items_accepted"], "rejected": r["items_rejected"], "requests": r["http_requests"],
            "rows_written": usage.get("rows_written", "not recorded"),
            "errors": (r["errors"] or "")[:200],
        })
    return out


def latest_success(db) -> dict:
    """Latest finished run per job that collected successfully (complete, or budget-stopped partial)."""
    rows = db.execute(
        "SELECT job, finished_at_utc, status, quota_usage_json FROM collector_runs "
        "WHERE status IN ('succeeded', 'partial') AND finished_at_utc IS NOT NULL "
        "ORDER BY run_id DESC LIMIT 200"
    )
    out: dict[str, dict] = {}
    for r in rows:
        if r["job"] in out or run_outcome(r) == "Partial: some series failed":
            continue
        out[r["job"]] = {"finished_utc": r["finished_at_utc"], "outcome": run_outcome(r)}
    return out


def trigger_status(db, now: datetime, source_id: str = SOURCE_ID) -> list[dict]:
    t = last_triggers(db, source_id)
    out = []
    for origin, expected in (("schedule", SCHEDULE_EVERY + SCHEDULE_LATE), ("external", EXTERNAL_EXPECTED),
                             ("manual", None)):
        rec = t.get(origin)
        if not rec:
            out.append({"trigger": origin, "last_utc": "never recorded", "status": "no record"})
            continue
        age = now - datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        late = f"overdue ({int(age.total_seconds() // 60)} min since last)"
        status = "ok" if expected is None or age <= expected else late
        out.append({"trigger": origin, "last_utc": rec["at"], "github_run_id": rec.get("github_run_id"),
                    "status": status})
    return out


def backfill_progress(db, symbols, now: datetime, source_id: str = SOURCE_ID) -> list[dict]:
    """Covered share of each series' target window (the collector's first-run window per timeframe)."""
    out = []
    for c in coverage_summary(db, source_id, symbols, list(TIMEFRAMES)):
        days = TIMEFRAMES[c["timeframe"]][2]
        start = now - timedelta(days=days)
        if not c["first_bar_utc"]:
            pct = 0.0
        else:
            first = datetime.strptime(c["first_bar_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            last = datetime.strptime(c["last_bar_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            pct = max(0.0, min(1.0, (last - max(first, start)) / (now - start)))
        out.append({**c, "target_window_days": days, "covered_pct": round(100 * pct, 1)})
    return out


def completeness(db, symbols, now: datetime, source_id: str = SOURCE_ID, timeframes=None) -> dict:
    """Per series: counts of each session state, and the remaining gaps (newest first)."""
    summary, gaps = [], []
    for tf in timeframes or list(TIMEFRAMES):
        grades = assess(db, source_id, symbols, tf, now=now)
        by_sym: dict[str, Counter] = {}
        for g in grades:
            by_sym.setdefault(g.symbol, Counter())[g.state] += 1
            if g.state in ("MISSING", "INCOMPLETE", "ANOMALY", "PROVIDER_UNAVAILABLE"):
                gaps.append({"symbol": g.symbol, "timeframe": tf, "session": g.session_date,
                             "state": g.state, "bars": g.bars, "expected": g.expected, "reason": g.reason})
        for sym in symbols:
            summary.append({"symbol": sym, "timeframe": tf, **dict(by_sym.get(sym, Counter()))})
    return {"summary": summary, "gaps": sorted(gaps, key=lambda g: g["session"], reverse=True)}


def source_health(db) -> list[dict]:
    return db.execute(
        "SELECT source_id, lifecycle_status, last_attempt_at_utc, last_success_at_utc, consecutive_failures, "
        "failure_count, last_error FROM sources WHERE lifecycle_status = 'ACTIVE' ORDER BY source_id"
    )


def current_market_runs(db) -> list[dict]:
    rows = db.execute(
        "SELECT run_id, started_at_utc, status, quota_usage_json FROM collector_runs "
        "WHERE job = ? AND status = 'running' ORDER BY run_id",
        (JOB,),
    )
    return [
        {"run_id": r["run_id"], "started_utc": r["started_at_utc"], "outcome": run_outcome(r)} for r in rows
    ]
