"""News rollup and signals: counting, de-duplication, share-based baseline rules."""

from __future__ import annotations

import json
from datetime import date, timedelta

from engines import news_rollup as nr

TODAY = date(2026, 12, 20)


def fact(day, company="HUBC", url=None, topic="news.company", conf="fact"):
    return {
        "source_date": day.isoformat(),
        "company": company,
        "topic": topic,
        "fact_text": f"story {url}",
        "source_url": url or f"https://x/{day}/{company}",
        "confidence": conf,
    }


def background(days=35, per_day=3):
    """Steady news about other companies, so the total has a stable denominator."""
    return [
        fact(TODAY - timedelta(days=i), "OTHER", url=f"https://x/bg{i}-{k}")
        for i in range(days)
        for k in range(per_day)
    ]


def test_rollup_counts_distinct_stories_and_keeps_the_topic_mix():
    d = date(2026, 11, 16)
    facts = [
        fact(d, url="https://x/1"),
        fact(d, url="https://x/1"),
        fact(d, url="https://x/2", topic="news.results"),
    ]
    out = {r["entity"]: r for r in nr.rollup(facts)}
    assert out["HUBC"]["stories"] == 2 and out[nr.ALL]["stories"] == 2
    assert json.loads(out["HUBC"]["topics"]) == {"news.company": 1, "news.results": 1}


def test_a_jump_in_share_against_its_own_history_becomes_a_dated_signal():
    facts = background()
    facts += [
        fact(TODAY - timedelta(days=i), url=f"https://x/old{i}") for i in range(8, 30, 4)
    ]  # a few before
    facts += [fact(TODAY - timedelta(days=i), url=f"https://x/w{i}") for i in range(5)]  # five this week
    out = nr.signals(nr.rollup(facts), TODAY, "2026-12-20T10:00:00Z")
    hub = [s for s in out if s["company"] == "HUBC"]
    assert len(hub) == 1 and hub[0]["topic"] == "news.signal" and "5 news stories" in hub[0]["fact_text"]
    assert len(hub[0]["fact_text"]) <= 300 and hub[0]["value"] == "5"
    assert not [s for s in out if s["company"] == "OTHER"]  # steady background is not a signal


def test_more_coverage_overall_is_not_a_spike():
    quiet = background(days=28, per_day=1)  # old days: one story a day
    busy = [
        fact(TODAY - timedelta(days=i), "OTHER", url=f"https://x/b{i}-{k}")
        for i in range(7)
        for k in range(8)
    ]
    assert nr.signals(nr.rollup(quiet + busy), TODAY, "t") == []


def test_no_signal_for_a_new_entity_or_too_little_news():
    facts = background() + [fact(TODAY - timedelta(days=i), url=f"https://x/n{i}") for i in range(4)]
    assert not [s for s in nr.signals(nr.rollup(facts), TODAY, "t") if s["company"] == "HUBC"]
    assert nr.signals(nr.rollup(background(days=35, per_day=0) or []), TODAY, "t") == []
