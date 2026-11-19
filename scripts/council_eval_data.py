"""Read-only data for the seven-day council dry-run evaluation. Writes a JSON file; nothing is changed.

    python -m scripts.council_eval_data --days 7 --out council_eval_data.json

Reads news_item (read-only token) and recomputes, with the same pipeline the dry run uses (cluster, then
classify), the events of the window so coverage, flagging, duplicates and mapping can be audited.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engines import council_news as cn
from engines import library_db
from engines import news_facts as nf
from engines import news_importance as ni
from scripts import build_news_capsule as bnc

MATERIAL = re.compile(
    r"\b(profit|loss(?:es)?|earnings|dividend|bonus|rights issue|acquir\w+|acquisition|merger|takeover|"
    r"default|shutdown|shut down|fire|explosion|strike|imf|sbp|policy rate|circular debt|tariff|nepra|ogra|"
    r"budget|tax|ban|supreme court|secp|delist\w*|suspend\w*|petrol|diesel|gas price|rupee|inflation|"
    r"reko diq|saindak|privati[sz]\w+|bailout|rating|downgrade|upgrade|results?)\b",
    re.I,
)
LEGAL = re.compile(
    r"\b[A-Z][\w&.-]+(?: [A-Z][\w&.-]+){0,3} (?:Limited|Ltd|Bank|Cement|Sugar|Textile|Mills|Power|Energy)\b"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("council_eval_data.json"))
    args = ap.parse_args(argv)
    db = library_db.get_library_readonly_connection().db
    db.max_rows_read = max(db.max_rows_read, 400_000)
    db.max_rows_written = 1
    now = datetime.now(UTC)
    since = now - timedelta(days=args.days)
    heads = cn.load_headlines(db, since, now)
    vocab = bnc.load_vocabulary(db)
    events = ni.cluster(heads, (), vocab)
    ni.classify(vocab, events)
    out: dict = {
        "window": [since.isoformat(), now.isoformat()],
        "headlines": len(heads),
        "events": len(events),
    }

    day = lambda s: ni.pkt_day(s)  # noqa: E731
    per_day: dict = defaultdict(lambda: Counter())
    for h in heads:
        per_day[day(h.published_at)]["headlines"] += 1
        per_day[day(h.published_at)][f"src:{h.source}"] += 1
    flagged = [e for e in events if e.hits]
    for e in events:
        per_day[e.day]["events"] += 1
        if e.hits:
            per_day[e.day]["flagged"] += 1
            for r in {h.rule for h in e.hits}:
                per_day[e.day][f"rule{r}"] += 1
        if len({m.source for m in e.members}) > 1:
            per_day[e.day]["multi_outlet_events"] += 1
    out["per_day"] = {d: dict(c) for d, c in sorted(per_day.items())}

    # collection lag: published_at versus fetched_at, per outlet
    lag: dict = defaultdict(list)
    rows = db.execute(
        "SELECT source, published_at, fetched_at FROM news_item WHERE published_at >= ?",
        (since.strftime("%Y-%m-%dT%H:%M:%SZ"),),
    )
    bad_dates = 0
    for r in rows:
        try:
            p = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            f = datetime.fromisoformat(r["fetched_at"].replace("Z", "+00:00"))
            lag[r["source"]].append((f - p).total_seconds() / 3600)
            if p > f + timedelta(minutes=5):
                bad_dates += 1  # published after it was collected: a date error
        except (TypeError, ValueError, AttributeError):
            bad_dates += 1
    out["lag_hours"] = {
        s: {"n": len(v), "median": sorted(v)[len(v) // 2], "p90": sorted(v)[int(len(v) * 0.9)], "max": max(v)}
        for s, v in lag.items()
        if v
    }
    out["date_errors"] = bad_dates

    # flagged events (the dry run's candidates)
    out["flagged"] = [
        {
            "day": e.day,
            "title": e.title[:140],
            "rules": sorted({h.rule for h in e.hits}),
            "details": [h.detail[:60] for h in e.hits][:3],
            "companies": sorted(e.company_keys | set(e.companies)),
            "sectors": sorted(e.sectors),
            "outlets": sorted({m.source for m in e.members}),
            "members": len(e.members),
            "priority": ni.priority(e),
        }
        for e in sorted(flagged, key=lambda e: -ni.priority(e))
    ]

    # duplicates among flagged events (same story kept apart)
    words = [(e, ni.content_words(e.title)) for e in flagged]
    pairs = []
    for i in range(len(words)):
        for j in range(i + 1, len(words)):
            (a, wa), (b, wb) = words[i], words[j]
            if ni.similar(wa, wb) and (
                not (a.company_keys and b.company_keys) or (a.company_keys & b.company_keys)
            ):
                pairs.append([a.day, a.title[:90], b.day, b.title[:90]])
    out["duplicate_pairs"] = pairs[:60]
    out["duplicate_pair_count"] = len(pairs)

    # missed material: not flagged but the headline reads material
    missed = []
    for e in events:
        if not e.hits and MATERIAL.search(e.title):
            missed.append(
                {
                    "day": e.day,
                    "title": e.title[:140],
                    "companies": sorted(e.company_keys),
                    "outlets": sorted({m.source for m in e.members}),
                }
            )
    out["unflagged_material_looking"] = missed[:120]
    out["unflagged_material_count"] = len(missed)

    # mapping audit
    mapped = []
    unmapped = []
    for h in heads:
        cos = nf.companies_in(vocab, h.title, h.snippet)
        if cos:
            mapped.append({"title": h.title[:130], "companies": sorted(cos), "source": h.source})
        elif LEGAL.search(h.title):
            unmapped.append(
                {"title": h.title[:130], "name_like": LEGAL.findall(h.title)[:3], "source": h.source}
            )
    out["mapped_count"] = len(mapped)
    out["mapped_sample"] = mapped[:: max(1, len(mapped) // 70)][:70]
    dup: dict = defaultdict(list)
    for h in heads:
        dup[(h.source, " ".join(h.title.lower().split()))].append(h.url)
    out["stored_duplicate_titles"] = [
        {"source": k[0], "title": k[1][:90], "urls": v[:6]} for k, v in dup.items() if len(v) > 1
    ][:40]
    out["stored_duplicate_title_count"] = sum(1 for v in dup.values() if len(v) > 1)
    out["name_like_unmapped"] = unmapped[:80]
    out["name_like_unmapped_count"] = len(unmapped)
    cnt = Counter(c for m in mapped for c in m["companies"])
    out["most_mapped"] = cnt.most_common(15)
    out["multi_company_headlines"] = sum(1 for m in mapped if len(m["companies"]) > 3)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(heads)} headlines, {len(events)} events, {len(flagged)} flagged; written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
