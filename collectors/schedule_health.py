"""Detect missed and late scheduled runs of the collection workflow.

GitHub's cron is best effort: it can start runs late or skip them. This module compares the cron's
expected slots with the runs that actually started (from GitHub's run list) and classifies each slot as
on_time, late, missed or pending. It reads only data passed to it and makes no network requests.

Usage (the runs list comes from GitHub, e.g. with a read-only token outside this module):
    gh run list --workflow scheduled-jobs.yml --event schedule --limit 50 --json createdAt > runs.json
    python -m collectors.schedule_health runs.json
Exit code 1 if any slot in the window was missed.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

CRON_MINUTE, CRON_EVERY_HOURS = 17, 6  # .github/workflows/scheduled-jobs.yml: "17 */6 * * *"
LATE_AFTER = timedelta(minutes=30)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def expected_slots(start: datetime, end: datetime) -> list[datetime]:
    t = start.replace(minute=CRON_MINUTE, second=0, microsecond=0)
    t = t.replace(hour=t.hour - t.hour % CRON_EVERY_HOURS)
    out = []
    while t <= end:
        if t >= start:
            out.append(t)
        t += timedelta(hours=CRON_EVERY_HOURS)
    return out


def assess(run_starts: list[str], now: datetime, lookback_hours: int = 48) -> list[dict]:
    """Each slot in the window: the first scheduled run that started before the next slot covers it."""
    starts = sorted(_parse(s) for s in run_starts)
    period = timedelta(hours=CRON_EVERY_HOURS)
    out = []
    for slot in expected_slots(now - timedelta(hours=lookback_hours), now):
        run = next((s for s in starts if slot <= s < slot + period), None)
        if run is not None:
            delay = run - slot
            status = "late" if delay > LATE_AFTER else "on_time"
        else:
            delay, status = None, "pending" if now < slot + period else "missed"
        out.append({
            "slot_utc": slot.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status,
            "delay_minutes": None if delay is None else round(delay.total_seconds() / 60),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0], encoding="utf-8") as f:
        runs = json.load(f)
    report = assess([r["createdAt"] for r in runs], datetime.now(UTC))
    print(json.dumps(report, indent=1))
    return 1 if any(r["status"] == "missed" for r in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
