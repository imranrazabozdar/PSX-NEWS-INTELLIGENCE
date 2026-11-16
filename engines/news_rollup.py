"""Daily news rollup per company, sector and Pakistan market, and the dated signals built from it. No model.

rollup(): one row per (day, entity): story count, topic mix, and the best-sourced headline. The count is of
distinct stories, so the same headline from two outlets counts once per outlet row only if the text differs.
signals(): compares each entity's last 7 days with its own earlier baseline. A signal is written only when
there is enough history (BASELINE_MIN_DAYS of coverage), at least MIN_STORIES in the last 7 days and the
share of all news is at least SPIKE_RATIO times its baseline share. Signals state counts and dates only.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

BASELINE_DAYS = 28
BASELINE_MIN_DAYS = 14
MIN_STORIES = 3
SPIKE_RATIO = 2.0
MIN_SHARE = 0.01  # floor on the baseline share so a near-zero baseline does not make everything a spike
MIN_TOTAL_WEEK = 20  # a quiet week of tracked news says nothing
MIN_TOTAL_BASE = 60
CONFIDENCE_ORDER = {"fact": 0, "analyst_view": 1}


ALL = "ALL"  # pseudo-entity: distinct stories that day across everything, the denominator for shares


def rollup(facts: list[dict]) -> list[dict]:
    """facts: rows from news_facts.rows_for_item (source_date, company, topic, fact_text, ...)."""
    seen: set[tuple[str, str, str]] = set()
    days: dict[tuple[str, str], list[dict]] = defaultdict(list)
    all_urls: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        key = (f["source_date"], f["company"], f["source_url"])
        if key in seen:
            continue
        seen.add(key)
        days[(f["source_date"], f["company"])].append(f)
        all_urls[f["source_date"]].add(f["source_url"])
    out = []
    for (day, entity), rows in sorted(days.items()):
        best = min(rows, key=lambda r: (CONFIDENCE_ORDER.get(r["confidence"], 9), r["fact_text"]))
        out.append(
            {
                "day": day,
                "entity": entity,
                "stories": len(rows),
                "topics": json.dumps(
                    dict(sorted(Counter(r["topic"] for r in rows).items())), separators=(",", ":")
                ),
                "top_title": best["fact_text"][:200],
                "top_url": best["source_url"],
            }
        )
    out += [
        {"day": d, "entity": ALL, "stories": len(u), "topics": "{}", "top_title": None, "top_url": None}
        for d, u in sorted(all_urls.items())
    ]
    return out


def _sum(per_day: dict[str, dict], start: date, end: date) -> int:
    return sum(r["stories"] for d, r in per_day.items() if start <= date.fromisoformat(d) <= end)


def signals(rows: list[dict], today: date, created_at: str) -> list[dict]:
    """research_fact rows (news.signal) for entities whose share of the news in the last 7 days stands out.

    A share, not a raw count, so a source that starts reporting more does not look like a spike."""
    by_entity: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_entity[r["entity"]][r["day"]] = r
    total = by_entity.get(ALL, {})
    week_start = today - timedelta(days=6)
    base_start = week_start - timedelta(days=BASELINE_DAYS)
    base_end = week_start - timedelta(days=1)
    total_week, total_base = _sum(total, week_start, today), _sum(total, base_start, base_end)
    if total_week < MIN_TOTAL_WEEK or total_base < MIN_TOTAL_BASE:
        return []
    out = []
    for entity, per_day in sorted(by_entity.items()):
        if entity == ALL:
            continue
        first = min(date.fromisoformat(d) for d in per_day)
        if (week_start - first).days < BASELINE_MIN_DAYS:
            continue  # not enough history to call anything unusual
        n_week = _sum(per_day, week_start, today)
        if n_week < MIN_STORIES:
            continue
        share_week = n_week / total_week
        share_base = _sum(per_day, base_start, base_end) / total_base
        if share_week < SPIKE_RATIO * max(share_base, MIN_SHARE):
            continue
        topics: Counter = Counter()
        for d, r in per_day.items():
            if week_start <= date.fromisoformat(d) <= today:
                topics.update(json.loads(r["topics"]))
        main_topic, main_n = topics.most_common(1)[0]
        top = max(
            (r for d, r in per_day.items() if week_start <= date.fromisoformat(d) <= today),
            key=lambda r: (r["stories"], r["day"]),
        )
        label = {"MACRO:PAKISTAN": "Pakistan market"}.get(entity, entity)
        text = (
            f"{label}: {n_week} news stories in the 7 days to {today.isoformat()}, "
            f"{100 * share_week:.0f}% of all tracked news against {100 * share_base:.0f}% over the "
            f"previous {BASELINE_DAYS} days; most common topic {main_topic} ({main_n})."
        )
        out.append(
            {
                "company": entity,
                "topic": "news.signal",
                "fact_text": text[:300],
                "value": str(n_week),
                "unit": "stories/7d",
                "period": f"{week_start.isoformat()}..{today.isoformat()}",
                "source_name": f"PSX-NI news rollup, {today.isoformat()}",
                "source_url": top["top_url"],
                "source_date": today.isoformat(),
                "as_of": today.isoformat(),
                "confidence": "fact",
                "created_at": created_at,
            }
        )
    return out


def parse_day(text: str) -> date:
    return datetime.fromisoformat(text).date()
