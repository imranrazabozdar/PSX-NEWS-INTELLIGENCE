"""Intelligence pipeline entry point, single-writer protection and readiness checks (Stage 2 final batch).

run_all() runs, in order: headline builder -> event intel (batch 1) -> exposure and T1-T9 impact (batch 2) ->
revalidation. It holds a lease (a collector_runs row, job 'intelligence', with a claim token read back in the
same transaction; the same pattern verified on Turso for market collection). A second runner exits without
writing. A run left 'running' beyond the lease is finalised as failed (abandoned) by the next claim. Every
stage is idempotent, so a restart simply continues.

This module prepares production activation; it does NOT activate anything. No workflow calls it, and the
command-line entry accepts only a local SQLite file.
"""

from __future__ import annotations

import json
import uuid

from database.canonical import now_utc
from database.connection import Database
from engines import event_intel as ei
from engines import headline_events as hb
from engines import impact_intel as ii
from engines import review_revalidation as rv

JOB = "intelligence"
LEASE_MINUTES = 60


class Busy(RuntimeError):
    """Another intelligence run holds the lease."""


def _claim(db: Database, context: dict) -> int:
    started, claim = now_utc(), uuid.uuid4().hex
    rows = db.batch(
        [
            (
                "UPDATE collector_runs SET status = 'failed', finished_at_utc = ?, errors = "
                "substr(COALESCE(errors || "
                "char(10), '') || 'abandoned: lease expired before the run was finalised', 1, 2000) "
                "WHERE job = ? "
                "AND status = 'running' AND strftime('%s', ?) - strftime('%s', started_at_utc) >= 60 * ?",
                (started, JOB, started, LEASE_MINUTES),
            ),
            (
                "INSERT INTO collector_runs(job, source_id, started_at_utc, status, quota_usage_json) "
                "SELECT ?, NULL, ?, 'running', ? WHERE NOT EXISTS (SELECT 1 FROM collector_runs "
                "WHERE job = ? "
                "AND status = 'running')",
                (JOB, started, json.dumps({"context": context, "claim": claim}), JOB),
            ),
            (
                "SELECT run_id, json_extract(quota_usage_json, '$.claim') AS claim FROM collector_runs "
                "WHERE job = ? AND status = 'running'",
                (JOB,),
            ),
        ]
    )
    holders = rows[2]
    mine = [r["run_id"] for r in holders if r["claim"] == claim]
    if len(mine) != 1 or len(holders) != 1:
        raise Busy("another intelligence run holds the lease; nothing was done")
    return mine[0]


def run_all(db: Database, *, synthetic: bool = False, limit: int = 200, context: dict | None = None) -> dict:
    run_id = _claim(db, context or {})
    out: dict = {"run_id": run_id, "stages": {}, "errors": []}
    status = "failed"
    try:
        s1 = hb.run(db, limit=limit)
        s2 = ei.run(db, limit=limit)
        s3 = ii.run(db, synthetic=synthetic, limit=limit)
        s4 = rv.revalidate(db)
        out["stages"] = {
            "headline_events": vars(s1),
            "event_intel": vars(s2),
            "impact": vars(s3),
            "revalidation": s4,
        }
        out["errors"] = s1.errors + s2.errors + s3.errors + s4["errors"]
        stopped = s1.stopped_at_budget or s2.stopped_at_budget or s3.stopped_at_budget
        status = "partial" if (out["errors"] or stopped) else "succeeded"
    except Exception as exc:  # recorded, then re-raised: a failure is never reported as success
        out["errors"].append(f"{type(exc).__name__}: {str(exc)[:300]}")
        raise
    finally:
        db.batch(
            [
                (
                    "UPDATE collector_runs SET status = ?, finished_at_utc = ?, errors = ?, "
                    "quota_usage_json = "
                    "json_set(quota_usage_json, '$.summary', json(?)) WHERE run_id = ? AND status = "
                    "'running'",
                    (
                        status,
                        now_utc(),
                        "\n".join(out["errors"])[:2000] or None,
                        json.dumps({k: _brief(v) for k, v in out["stages"].items()}),
                        run_id,
                    ),
                )
            ]
        )
    out["status"] = status
    return out


def _brief(v: dict) -> dict:
    return {k: (len(x) if isinstance(x, list) else x) for k, x in v.items() if not isinstance(x, dict)}


def _last_detail(r: dict) -> str:
    when = r["finished_at_utc"] or r["started_at_utc"]
    detail = f"run {r['run_id']} {r['status']} at {when}"
    return detail + (f": {r['errors'][:200]}" if r["errors"] else "")


def readiness(db: Database) -> dict:
    """Operational health for activation decisions. 'fail' and 'warn' are never hidden behind 'ok'."""
    q = lambda sql, p=(): db.execute(sql, p)[0]["n"]  # noqa: E731
    news_items = q(
        "SELECT COUNT(*) AS n FROM source_items i JOIN sources s USING(source_id) "
        "WHERE s.source_type IN ('news_media','government')"
    )
    built = q("SELECT COUNT(*) AS n FROM event_extractions WHERE schema_version = ?", (hb.SCHEMA_VERSION,))
    with_event = q(
        "SELECT COUNT(*) AS n FROM event_extractions WHERE schema_version = ? AND event_id IS NOT NULL",
        (hb.SCHEMA_VERSION,),
    )
    intel = q("SELECT COUNT(*) AS n FROM event_extractions WHERE schema_version = ?", (ei.SCHEMA_VERSION,))
    events = q("SELECT COUNT(*) AS n FROM events")
    unassessed = q(
        "SELECT COUNT(*) AS n FROM events e WHERE NOT EXISTS (SELECT 1 FROM event_extractions x "
        "WHERE x.event_id = e.event_id AND x.schema_version = ?)",
        (ei.SCHEMA_VERSION,),
    )
    stale = len(rv.stale_assessments(db))
    review = len(rv.review_queue(db, limit=10_000))
    last = db.execute(
        "SELECT run_id, status, started_at_utc, finished_at_utc, errors FROM collector_runs "
        "WHERE job = ? ORDER BY run_id DESC LIMIT 1",
        (JOB,),
    )
    running = q("SELECT COUNT(*) AS n FROM collector_runs WHERE job = ? AND status = 'running'", (JOB,))
    checks = [
        (
            "headline backlog",
            "ok" if built >= news_items else "warn",
            f"{news_items - built} news items not yet processed by the headline builder",
        ),
        (
            "classification backlog",
            "ok" if intel >= with_event else "warn",
            f"{with_event - intel} built items not yet classified",
        ),
        (
            "unclassified events",
            "ok" if not unassessed else "warn",
            f"{unassessed} of {events} events not assessed",
        ),
        (
            "stale assessments",
            "ok" if not stale else "warn",
            f"{stale} assessments behind their event revision",
        ),
        ("review backlog", "ok" if not review else "warn", f"{review} items await a human decision"),
        (
            "last intelligence run",
            (
                "fail"
                if last and last[0]["status"] == "failed"
                else "warn"
                if not last or last[0]["status"] != "succeeded"
                else "ok"
            ),
            _last_detail(last[0]) if last else "no intelligence run recorded",
        ),
        (
            "single writer",
            "ok" if running <= 1 else "fail",
            f"{running} intelligence run(s) currently running",
        ),
    ]
    return {
        "checked_at_utc": now_utc(),
        "checks": [{"check": c, "status": s, "detail": d} for c, s, d in checks],
        "overall": "fail"
        if any(s == "fail" for _, s, _ in checks)
        else "warn"
        if any(s == "warn" for _, s, _ in checks)
        else "ok",
    }


def main(argv: list[str] | None = None) -> int:
    """Local only: runs against a SQLite file. Production activation is a separate, approved step."""
    import argparse

    from database.connection import SQLiteDatabase

    ap = argparse.ArgumentParser(description="Run all intelligence stages on a LOCAL SQLite database")
    ap.add_argument("--local-db", required=True)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--readiness", action="store_true", help="only print readiness checks")
    args = ap.parse_args(argv)
    db = SQLiteDatabase(args.local_db)
    try:
        out = (
            readiness(db)
            if args.readiness
            else run_all(db, synthetic=args.synthetic, context={"trigger": "cli"})
        )
    except Busy as exc:
        print(json.dumps({"skipped": str(exc)}))
        return 0
    finally:
        db.close()
    print(json.dumps(out, indent=1, default=str))
    return 0 if args.readiness or out.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
