"""Investify announcements -> psx-library facts, under the written consent (docs/consent/investify-2026-11-12)

This is the same consent-bound client as collectors/investify_job.py (every rule there applies unchanged: the
good-citizen gate, one request per cycle, 15-minute floor, trading hours, ETag and Last-Modified, robots.txt,
backoff and the circuit breaker, an honest User-Agent). The only difference is where the result goes: this run
never touches the older news database. It calls the same `run_once` in its no-database mode, which gives what
was parsed, and turns each announcement into a dated fact for psx-library.

Metadata plus, from 17 Nov 2026 (consent addendum), the card's Highlights text, kept in private psx-library
only and never quoted in reports. Never a PDF. Every fact carries the attribution. A fact states what was
announced, not what it means: no figure is read from a headline, and nothing is said about the price.

Usage:  python -m collectors.investify_library_job --state <state.json> --out <capsule.json>
Then load the capsule with `python -m scripts.absorb_sector_capsule <capsule.json> --apply --since-days 60`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from collectors import investify_job as job
from collectors import investify_policy as pol
from engines import announcement_substance as asub
from engines import investify_collector as ic

SOURCE_NAME = "Investify (investify.pk), announcements listing"
HIGHLIGHTS_SOURCE = "Investify (investify.pk), announcement highlights"
HIGHLIGHTS_TOPIC = asub.HIGHLIGHTS_TOPIC
HIGHLIGHT_CHUNK = 285  # a fact holds 300 characters: the date and ": " take the rest
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


def facts_from_records(
    records: list[dict[str, Any]], stamp: str, *, with_highlights: bool = False, cutoff: str = ""
) -> list[dict[str, Any]]:
    """One fact per announcement, dated by the announcement day. The text format matches the earlier facts
    from the owner's Investify snapshot ('<date>: <title>'), so an announcement already stored is skipped."""
    if cutoff:  # owner rule: previous three months and the latest only, never history
        records = [r for r in records if (r.get("announced_on_pkt") or r["announced_at_utc"][:10]) >= cutoff]
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
    if with_highlights:
        out += highlight_facts(records, stamp)
    return out


def highlight_chunks(text: str, size: int = HIGHLIGHT_CHUNK, parts: int = 2) -> list[str]:
    """The Highlights text in at most `parts` chunks of at most `size` characters, cut at word boundaries."""
    words, chunks, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > size:
            chunks.append(cur)
            cur = w
            if len(chunks) == parts:
                return chunks
        else:
            cur = f"{cur} {w}".strip()
    if cur and len(chunks) < parts:
        chunks.append(cur)
    return chunks


def highlight_fact_rows(sym: str, title: str, when: str, text: str, created_at: str) -> list[dict[str, Any]]:
    """Private Highlights facts for one announcement: '<date>: <text>' in up to two chunks, linked to the
    title fact by the title's key in the URL fragment, so no characters are spent repeating the title."""
    key = asub.title_key(title)
    out = []
    for n, chunk in enumerate(highlight_chunks(text), start=1):
        out.append(
            {
                "company": sym,
                "topic": HIGHLIGHTS_TOPIC,
                "fact_text": f"{when}: {chunk}",
                "value": None,
                "unit": None,
                "period": when,
                "source_name": HIGHLIGHTS_SOURCE,
                "source_url": f"https://investify.pk/company/{sym}/announcements#{key}-{n}",
                "source_date": when,
                "as_of": when,
                "confidence": "fact",
                "created_at": created_at,
            }
        )
    return out


def highlight_facts(records: list[dict[str, Any]], stamp: str) -> list[dict[str, Any]]:
    """The card's key-facts line and summary paragraph as private facts. Allowed only under the 17 Nov 2026
    addendum."""
    out = []
    for r in records:
        pkt = r.get("announced_on_pkt") or r["announced_at_utc"][:10]
        title = " ".join(str(r["title"]).split())
        extra = " ".join(" ".join(str(r.get(k) or "") for k in ("highlights", "summary")).split())
        if title and extra and r.get("symbol"):
            out += highlight_fact_rows(r["symbol"], title, pkt, extra, stamp)
    return out


# robots.txt is read first when its 24-hour copy is stale, and that read is a request, so the page request
# must wait out the 15-minute floor. One dispatch now does both (robots, wait, page) instead of needing two
# dispatches and wasting a morning window. The limit of one request per 15 minutes is unchanged: the gate
# re-checks every rule (window, floor, ceilings, calendar) before the second request.
AFTER_ROBOTS_WAIT_S = 15 * 60 + 30


def run(
    state_path: Path,
    out_path: Path,
    *,
    now: datetime | None = None,
    transport=job.default_transport,
    sleep=None,
    rng=None,
) -> int:
    injected = now is not None
    now = now or datetime.now(UTC)
    kwargs: dict[str, Any] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    if rng is not None:
        kwargs["rng"] = rng
    audit = job.AuditLog(state_path.with_name("investify_audit.jsonl"))  # every request and skip

    def cycle(at: datetime):
        return job.run_once(
            now=at,
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

    outcome = cycle(now)
    if outcome.status == "robots_refreshed":
        print(f"investify: {outcome.reason}")
        print(f"waiting {AFTER_ROBOTS_WAIT_S}s (the 15-minute floor) before the page request")
        (sleep or time.sleep)(AFTER_ROBOTS_WAIT_S)
        later = now + timedelta(seconds=AFTER_ROBOTS_WAIT_S + 200) if injected else datetime.now(UTC)
        first = outcome.http_requests
        outcome = cycle(later)  # the gate re-checks the window, floor, ceilings and calendar
        outcome.http_requests += first
    print(f"investify: {outcome.status}: {outcome.reason}")
    print(f"requests made this run: {outcome.http_requests}")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    facts = facts_from_records(
        outcome.records, stamp, with_highlights=pol.highlights_allowed(now), cutoff=pol.capture_cutoff(now)
    )
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
