from datetime import UTC, datetime, timedelta

from engines import council_ledger as cl
from engines import news_importance as ni

NOW = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)


def event(eid, title, companies=(), rule=2, when="2026-11-19T01:00:00Z", extra=""):
    h = ni.Headline("brecorder", f"https://x.pk/{eid}", title, when)
    return ni.Event(
        event_id=eid,
        anchor=ni.content_words(title + extra),
        members=[h],
        kind="headline",
        title=title,
        hits=[ni.RuleHit(rule, "d", tuple(companies))],
        companies=list(companies),
        day="2026-11-19",
    )


def reserve(led, at=NOW, exec_id="e"):
    return led.reserve_batch(exec_id, at, "2026-11-19", cap_day=6, cap_exec=2)


def test_a_story_already_assessed_lately_is_marked_covered_and_kept_not_run_again(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    a = event("a", "Govt cuts petrol, diesel price by Rs3 per litre")
    led.enqueue(a, ni.priority(a, NOW), NOW)
    first = reserve(led)
    assert [i["event_id"] for i in first] == ["a"]
    led.finish(first[0]["key"], "assessed", NOW, ok=True)
    again = event("b", "Petrol and diesel price cut by Rs3 per litre", extra=" ogra")
    led.enqueue(again, ni.priority(again, NOW), NOW)
    assert reserve(led, NOW + timedelta(hours=2), "e2") == []
    item = next(i for i in led.snapshot()["queue"] if i["event_id"] == "b")
    assert item["state"] == "covered" and "similar story" in item["note"]  # kept, not discarded
    assert led.pending() == []  # covered items no longer wait


def test_a_similar_figure_for_a_different_company_is_not_covered(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    a = event("a", "NBP profit falls 29% in the third quarter", ["NBP"], rule=1)
    led.enqueue(a, ni.priority(a, NOW), NOW)
    first = reserve(led)
    led.finish(first[0]["key"], "assessed", NOW, ok=True)
    b = event("b", "MCB profit falls 29% in the third quarter", ["MCB"], rule=1)
    led.enqueue(b, ni.priority(b, NOW), NOW)
    assert [i["event_id"] for i in reserve(led, NOW + timedelta(hours=1), "e2")] == ["b"]


def test_a_story_outside_the_cover_window_may_run_again(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    a = event("a", "Govt cuts petrol, diesel price by Rs3 per litre")
    led.enqueue(a, ni.priority(a, NOW), NOW)
    first = reserve(led)
    led.finish(first[0]["key"], "assessed", NOW, ok=True)
    later = NOW + timedelta(hours=cl.COVER_HOURS + 1)
    b = event("b", "Govt cuts petrol, diesel price by Rs3 per litre again", extra=" new")
    led.enqueue(b, ni.priority(b, later), later)
    assert [i["event_id"] for i in reserve(led, later, "e3")] == ["b"]


def test_the_same_story_twice_in_one_batch_runs_once(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    for eid, t in (
        ("a", "Govt cuts petrol, diesel price by Rs3 per litre"),
        ("b", "Petrol and diesel price cut by Rs3 per litre"),
    ):
        e = event(eid, t)
        led.enqueue(e, ni.priority(e, NOW), NOW)
    assert len(reserve(led)) == 1


def test_a_story_naming_a_listed_company_outranks_an_equal_market_wide_one():
    macro = event("m", "SBP holds policy rate at 11 percent")
    named = event("c", "NBP announces something", ["NBP"], rule=2)
    named.company_keys = {"NBP"}
    assert ni.priority(named, NOW) > ni.priority(macro, NOW)
    assert ni.COMPANY_BONUS > 0
