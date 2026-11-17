"""Investify announcements -> psx-library facts, under the written consent (docs/consent/investify-2026-11-12)

This is the same consent-bound client as collectors/investify_job.py (every rule there applies unchanged: the
good-citizen gate, one request per cycle, 15-minute floor, trading hours, ETag and Last-Modified, robots.txt,
backoff and the circuit breaker, an honest User-Agent). The only difference is where the result goes: this run
never touches the older news database. It calls the same `run_once` in its no-database mode, which gives what
was parsed, and turns each announcement into a dated fact for psx-library.

Metadata only (consent condition 7): the title as shown, the date, Investify's category. Never Investify's own
summary text, never a PDF. Every fact carries the attribution. A fact states what was announced, not what it
means: no figure is read from a headline, and nothing is said about the price.

Usage:  python -m collectors.investify_library_job --state <state.json> --out <capsule.json>
Then load the capsule with `python -m scripts.absorb_sector_capsule <capsule.json> --apply --since-days 60`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collectors import investify_job as job
from collectors import investify_policy as pol
from engines import investify_collector as ic

SOURCE_NAME = "Investify (investify.pk), announcements listing"
# The registry entry values that the consent record encodes (docs/consent/investify-2026-11-12.md, "How the
# registry encodes this consent"). The policy's own check still requires the consent record file to exist.
ENTRY = {
    "source_id": pol.SOURCE_ID,
    "enabled": 1,
    "lifecycle_status": "APPROVED",
    "terms_status": "approved",
    "access_status": "verified_permitted",
    "access_method": "html_permitted",
}


def listed_symbols() -> frozenset[str]:
    """Every symbol PSX lists (the official directory the owner supplied), plus the coverage watchlist."""
    root = Path(__file__).resolve().parents[1]
    listed = json.loads((root / "docs" / "research" / "psx_listed_companies.json").read_text("utf-8"))
    return frozenset(listed["companies"]) | ic.load_watchlist_symbols()


def topic_for(record: dict[str, Any]) -> str:
    """Investify's own card label ('Financial Result', 'Board Meeting', ...), as the earlier snapshot load."""
    label = " ".join(str(record.get("investify_label") or "").split()) or "Other"
    return f"announcements.{label}"


def facts_from_records(records: list[dict[str, Any]], stamp: str) -> list[dict[str, Any]]:
    """One fact per announcement, dated by the announcement day. The text format matches the earlier facts
    from the owner's Investify snapshot ('<date>: <title>'), so an announcement already stored is skipped."""
    out = []
    for r in records:
        day = r["announced_at_utc"][:10]
        pkt = r.get("announced_on_pkt") or day
        title = " ".join(str(r["title"]).split())
        if not title or not r.get("symbol"):
            continue
        out.append(
            {
                "company": r["symbol"],
                "topic": topic_for(r),
                "fact_text": f"{pkt}: {title}"[:300],
                "value": None,
                "unit": None,
                "period": pkt,
                "source_name": SOURCE_NAME,
                "source_url": None,
                "source_date": pkt,
                "as_of": pkt,
                "confidence": "fact",
                "created_at": stamp,
            }
        )
    return out


def run(
    state_path: Path,
    out_path: Path,
    *,
    now: datetime | None = None,
    transport=job.default_transport,
    sleep=None,
    rng=None,
) -> int:
    now = now or datetime.now(UTC)
    kwargs: dict[str, Any] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    if rng is not None:
        kwargs["rng"] = rng
    audit = job.AuditLog(state_path.with_name("investify_audit.jsonl"))  # every request and skip
    outcome = job.run_once(
        now=now,
        state_path=state_path,
        entry=ENTRY,
        db=None,
        transport=transport,
        watchlist=listed_symbols(),
        dry_run=True,
        cfg=pol.PolicyConfig.from_env(),
        audit=audit,
        **kwargs,
    )
    print(f"investify: {outcome.status}: {outcome.reason}")
    print(f"requests made this run: {outcome.http_requests}")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    facts = facts_from_records(outcome.records, stamp)
    print(f"announcements parsed: {len(outcome.records)}; facts built: {len(facts)}")
    for f in facts[:8]:
        print("  sample:", f["company"], f["topic"], "|", f["fact_text"][:150])
    if outcome.status == "fetched":
        out_path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    return 1 if outcome.status in ("refused", "failed") else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    return run(args.state, args.out)


if __name__ == "__main__":
    sys.exit(main())
