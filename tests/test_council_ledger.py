"""The council ledger: daily and per-execution caps, queue, versions, retries, crash recovery, concurrency."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from engines import council_ledger as cl
from engines import news_importance as ni

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
DAY = "2026-11-17"


def event(n, rule=1, at="2026-11-17T03:00:00Z", extra=""):
    h = ni.Headline("mettis", f"https://m/{n}", f"story {n} {extra}", at)
    e = ni.Event(event_id=f"ev{n}", anchor=frozenset({f"w{n}"}), members=[h], title=h.title, day=DAY)
    e.hits = [ni.RuleHit(rule, "test", ("HUBC",))]
    return e


def ledger(tmp_path):
    return cl.Ledger(tmp_path / "ledger.json")


def fill(led, n, **kw):
    for i in range(n):
        e = event(i, **kw)
        led.enqueue(e, ni.priority(e, NOW), NOW)


def test_at_most_two_runs_per_execution_and_six_per_day(tmp_path):
    led = ledger(tmp_path)
    fill(led, 10)
    taken = []
    for k in range(5):  # five executions the same Pakistan-local day
        taken += led.reserve_batch(f"exec{k}", NOW + timedelta(minutes=30 * k), DAY)
    assert len(taken) == 6 and led.runs_on(DAY) == 6
    per_exec = [sum(1 for t in taken if t["exec_id"] == f"exec{k}") for k in range(5)]
    assert per_exec == [2, 2, 2, 0, 0]


def test_events_beyond_the_cap_stay_queued_and_run_the_next_day_highest_priority_first(tmp_path):
    led = ledger(tmp_path)
    for i in range(8):  # priorities 10..17: higher number runs first
        e = event(i)
        led.enqueue(e, 10 + i, NOW)
    for k in range(3):
        for item in led.reserve_batch(f"a{k}", NOW, DAY):
            led.finish(item["key"], "assessed", NOW, ok=True)
    waiting = {i["key"] for i in led.pending() if i["state"] == "pending"}
    assert waiting == {event(1).key, event(0).key}  # the two lowest priorities wait
    tomorrow = "2026-11-18"
    nxt = led.reserve_batch("b0", NOW + timedelta(days=1), tomorrow)
    assert [i["key"] for i in nxt] == [event(1).key, event(0).key]  # nothing was discarded


def test_the_cap_follows_the_pakistan_local_day():
    # 18:59 UTC and 19:01 UTC on the 16th are 23:59 on the 16th and 00:01 on the 17th in Pakistan
    assert ni.local_day(datetime(2026, 11, 16, 18, 59, tzinfo=UTC)) == "2026-11-16"
    assert ni.local_day(datetime(2026, 11, 16, 19, 1, tzinfo=UTC)) == "2026-11-17"


def test_one_assessment_per_event_version(tmp_path):
    led = ledger(tmp_path)
    e = event(1)
    assert led.enqueue(e, 50, NOW) == "queued"
    assert led.enqueue(e, 50, NOW) == "already_queued"
    (item,) = led.reserve_batch("x", NOW, DAY)
    led.finish(item["key"], "assessed", NOW, ok=True)
    assert led.enqueue(e, 50, NOW) == "already_assessed"
    assert led.reserve_batch("y", NOW, DAY) == []
    revised = event(1, extra="with a new figure 12")  # same event id, changed story: a new version
    revised.members[0] = ni.Headline("mettis", "https://m/1", "story 1 Rs12 billion", "2026-11-17T03:00:00Z")
    assert revised.version != e.version and led.enqueue(revised, 50, NOW) == "queued"


def test_a_failed_run_is_retried_then_held_for_review_never_discarded(tmp_path):
    led = ledger(tmp_path)
    fill(led, 1)
    for attempt in range(1, cl.MAX_ATTEMPTS + 1):
        (item,) = led.reserve_batch(f"e{attempt}", NOW, DAY, counted=False)
        assert item["attempts"] == attempt
        led.finish(item["key"], "provider error", NOW, ok=False)
    (held,) = led.pending()
    assert held["state"] == "needs_review" and "provider error" in held["last_error"]
    assert led.reserve_batch("late", NOW, DAY, counted=False) == []  # not retried automatically, still kept


def test_a_reservation_from_a_crashed_execution_is_released(tmp_path):
    led = ledger(tmp_path)
    fill(led, 1)
    led.reserve_batch("crashed", NOW, DAY)
    assert led.reserve_batch("next", NOW + timedelta(minutes=30), DAY) == []  # still reserved
    again = led.reserve_batch("later", NOW + timedelta(hours=cl.STALE_RESERVATION_HOURS + 1), DAY)
    assert len(again) == 1 and again[0]["attempts"] == 2


def test_uncounted_runs_do_not_use_the_caps(tmp_path):
    led = ledger(tmp_path)
    fill(led, 10)
    got = led.reserve_batch("ten", NOW, DAY, counted=False)
    assert len(got) == 10 and led.runs_on(DAY) == 0


def test_concurrent_executions_never_exceed_the_daily_cap(tmp_path):
    led = ledger(tmp_path)
    fill(led, 30)
    taken, lock = [], threading.Lock()

    def worker(k):
        got = cl.Ledger(tmp_path / "ledger.json").reserve_batch(f"exec{k}", NOW, DAY)
        with lock:
            taken.extend(got)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(taken) == 6 and len({t["key"] for t in taken}) == 6  # no slot taken twice
    assert led.runs_on(DAY) == 6


def test_concurrent_enqueue_and_calls_lose_nothing(tmp_path):
    led = ledger(tmp_path)

    def worker(k):
        l2 = cl.Ledger(tmp_path / "ledger.json")
        l2.enqueue(event(k), 10, NOW)
        l2.record_call({"ts": cl.stamp(NOW), "vendor": "groq", "account": 1, "outcome": "ok", "ms": 1})

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    snap = led.snapshot()
    assert len(snap["queue"]) == 25 and len(snap["calls"]) == 25


def test_individual_calls_and_quotas_are_counted_per_vendor_account(tmp_path):
    led = ledger(tmp_path)
    for account, outcome in ((1, "ok"), (1, "transient_error"), (2, "ok"), (1, "not_connected")):
        led.record_call(
            {"ts": cl.stamp(NOW), "vendor": "groq", "account": account, "outcome": outcome, "ms": 5}
        )
    since = NOW - timedelta(hours=1)
    assert led.calls_since("groq", 1, since) == 2  # a not-connected attempt made no request
    assert led.calls_since("groq", 2, since) == 1 and led.calls_since("gemini", 1, since) == 0
    assert led.calls_since("groq", 1, NOW + timedelta(minutes=1)) == 0


def test_a_damaged_ledger_fails_closed(tmp_path):
    led = ledger(tmp_path)
    (tmp_path / "ledger.json").write_text("{not json")
    with pytest.raises(cl.LedgerError):
        led.reserve_batch("x", NOW, DAY)
    assert json.loads(json.dumps({"ok": True}))  # the error did not rewrite the file
    assert (tmp_path / "ledger.json").read_text() == "{not json"
