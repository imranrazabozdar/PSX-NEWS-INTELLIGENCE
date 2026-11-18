"""Investify announcements into psx-library facts. Offline: the transport is injected, no socket is opened."""

from __future__ import annotations

import json
import random
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collectors import investify_library_job as lj
from collectors import investify_policy as pol
from engines import announcement_substance as asub

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "investify" / "announcements_point_in_time_2026-11-11.html"
MONDAY_10AM = datetime(
    2026, 11, 16, 5, 0, tzinfo=UTC
)  # 10:00 PKT, inside trading hours, after the consent date


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the collector must not open a socket in tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        return self.responses.pop(0)


class Jitter:
    def randint(self, lo, hi):
        return 1


def seeded_state(path: Path, now: datetime = MONDAY_10AM) -> None:
    pol.save_state(
        path,
        pol.PollState(robots_txt="User-agent: *\nDisallow: /admin\n", robots_fetched_utc=pol._iso(now)),
    )


def run(tmp_path, transport, now: datetime = MONDAY_10AM):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"
    seeded_state(state, now)
    code = lj.run(state, out, now=now, transport=transport, sleep=lambda s: None, rng=Jitter())
    return code, out


def test_one_request_makes_dated_attributed_facts_without_any_database(tmp_path, capsys):
    t = Transport((200, {"etag": '"v1"'}, FIXTURE.read_bytes()))
    code, out = run(tmp_path, t)
    assert code == 0 and len(t.calls) == 1 and t.calls[0][0] == pol.ANNOUNCEMENTS_URL
    facts = json.loads(out.read_text("utf-8"))
    assert facts, "the fixture page has announcements"
    for f in facts:
        assert f["source_name"] == lj.SOURCE_NAME and "investify" in f["source_name"].lower()
        assert f["topic"].startswith("announcements.") and f["confidence"] == "fact"
        assert f["fact_text"].startswith(f["period"] + ": ") and f["source_date"] == f["period"]
        assert f["value"] is None and len(f["fact_text"]) <= 300
    assert "requests made this run: 1" in capsys.readouterr().out


def test_highlights_are_stored_as_private_attributed_facts_when_the_consent_is_in_force(tmp_path):
    t = Transport((200, {}, FIXTURE.read_bytes()))
    _, out = run(
        tmp_path, t, now=datetime(2026, 11, 18, 5, 0, tzinfo=UTC)
    )  # Wednesday 10:00 PKT, addendum in force
    facts = json.loads(out.read_text("utf-8"))
    high = [f for f in facts if f["topic"] == lj.HIGHLIGHTS_TOPIC]
    titles = [f for f in facts if f["topic"].startswith("announcements.")]
    keys = {asub.title_key(f["fact_text"].split(": ", 1)[1]) for f in titles}
    assert (
        high and {f["source_url"].split("#")[1].rsplit("-", 1)[0] for f in high} <= keys
    )  # each links to a title
    for f in high:
        assert f["source_name"] == lj.HIGHLIGHTS_SOURCE and "investify" in f["source_name"].lower()
        assert len(f["fact_text"]) <= 300 and f["value"] is None and "#" in f["source_url"]


def test_before_the_addendum_is_in_force_no_highlights_are_stored():
    from datetime import datetime as dt

    assert not pol.highlights_allowed(dt(2026, 11, 16, 23, 59, tzinfo=UTC))
    assert pol.highlights_allowed(dt(2026, 11, 17, 0, 0, tzinfo=UTC))
    rec = {
        "symbol": "X",
        "title": "X news",
        "announced_at_utc": "2026-11-16T10:00:00Z",
        "announced_on_pkt": "2026-11-16",
        "investify_label": "Other",
        "highlights": "k",
        "summary": "s",
    }
    assert [f["topic"] for f in lj.facts_from_records([rec], "t")] == ["announcements.Other"]
    both = lj.facts_from_records([rec], "t", with_highlights=True)
    assert [f["topic"] for f in both] == ["announcements.Other", lj.HIGHLIGHTS_TOPIC]
    assert both[1]["fact_text"] == "2026-11-16: k s"
    assert both[1]["source_url"].endswith(f"#{asub.title_key('X news')}-1")


def test_long_highlights_are_cut_at_word_boundaries_into_at_most_two_chunks():
    words = " ".join(f"word{i}" for i in range(200))
    chunks = lj.highlight_chunks(words)
    assert len(chunks) == 2 and all(len(c) <= lj.HIGHLIGHT_CHUNK for c in chunks)
    assert all(not c.endswith(" ") and c.split()[0].startswith("word") for c in chunks)
    assert lj.highlight_chunks("short text") == ["short text"] and lj.highlight_chunks("") == []


def test_a_304_writes_nothing(tmp_path):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"
    pol.save_state(
        state,
        pol.PollState(robots_txt="User-agent: *\n", robots_fetched_utc=pol._iso(MONDAY_10AM), etag='"v1"'),
    )
    t = Transport((304, {}, b""))
    lj.run(state, out, now=MONDAY_10AM, transport=t, sleep=lambda s: None, rng=Jitter())
    assert len(t.calls) == 1 and not out.exists()
    assert t.calls[0][1].get("If-None-Match") == '"v1"'


def test_a_block_backs_off_and_writes_nothing(tmp_path):
    t = Transport((429, {"retry-after": "3600"}, b""))
    code, out = run(tmp_path, t)
    assert code == 0 and not out.exists() and len(t.calls) == 1


def test_outside_trading_hours_no_request_is_made(tmp_path):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"
    seeded_state(state)
    saturday = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)
    t = Transport()
    lj.run(state, out, now=saturday, transport=t, sleep=lambda s: None, rng=Jitter())
    assert t.calls == [] and not out.exists()


def test_the_registry_entry_is_the_consented_one_and_every_listed_symbol_is_kept():
    assert pol.registry_problem(lj.ENTRY) is None
    assert {"NBP", "HBL", "FCL", "PSO"} <= lj.listed_symbols()
    assert random  # imported for the jitter stand-in's signature only


def test_facts_skip_untitled_rows_and_repeat_the_earlier_text_format():
    rec = {
        "symbol": "NBP",
        "title": "  NBP reports   lower profit ",
        "announced_at_utc": "2026-10-28T10:00:00Z",
        "announced_on_pkt": "2026-10-28",
        "investify_label": "Financial Result",
    }
    facts = lj.facts_from_records([rec, {**rec, "title": ""}, {**rec, "symbol": ""}], "2026-11-17T00:00:00Z")
    assert len(facts) == 1
    assert facts[0]["fact_text"] == "2026-10-28: NBP reports lower profit"
    assert facts[0]["topic"] == "announcements.Financial Result"


def test_only_the_previous_three_months_and_the_latest_are_kept_never_history():
    from datetime import datetime as dt

    assert pol.CAPTURE_WINDOW_DAYS == 92
    assert pol.capture_cutoff(dt(2026, 11, 17, 5, 0, tzinfo=UTC)) == "2026-08-17"
    old = {
        "symbol": "X",
        "title": "old news",
        "announced_at_utc": "2026-05-01T10:00:00Z",
        "announced_on_pkt": "2026-05-01",
        "investify_label": "Other",
        "highlights": "k",
        "summary": "s",
    }
    new = {
        **old,
        "title": "new news",
        "announced_at_utc": "2026-11-16T10:00:00Z",
        "announced_on_pkt": "2026-11-16",
    }
    facts = lj.facts_from_records([old, new], "t", with_highlights=True, cutoff="2026-08-17")
    assert {f["fact_text"].split(": ", 1)[0] for f in facts} == {"2026-11-16"}
    assert (
        len(lj.facts_from_records([old, new], "t", with_highlights=True)) == 4
    )  # no cutoff given: nothing dropped


def test_a_stale_robots_copy_is_refreshed_then_the_page_is_fetched_in_the_same_run_after_the_floor(
    tmp_path, capsys
):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"  # no cached robots.txt at all
    t = Transport(
        (200, {}, b"User-agent: *\nDisallow: /admin\n"),
        (200, {"etag": '"v1"'}, FIXTURE.read_bytes()),
    )
    slept = []
    code = lj.run(state, out, now=MONDAY_10AM, transport=t, sleep=lambda s: slept.append(s), rng=Jitter())
    assert code == 0
    assert [u for u, _h in t.calls] == [pol.ROBOTS_URL, pol.ANNOUNCEMENTS_URL]
    assert lj.AFTER_ROBOTS_WAIT_S in slept and lj.AFTER_ROBOTS_WAIT_S >= 15 * 60  # the 15-minute floor holds
    assert json.loads(out.read_text("utf-8")), "the page was parsed into facts"
    assert "requests made this run: 2" in capsys.readouterr().out


def test_a_dry_run_that_parses_nothing_keeps_the_page_and_never_stores_validators(tmp_path):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"
    seeded_state(state)
    page = b"<html><body>no announcements here</body></html>"
    t = Transport((200, {"etag": '"v9"', "last-modified": "Tue"}, page))
    lj.run(state, out, now=MONDAY_10AM, transport=t, sleep=lambda s: None, rng=Jitter())
    assert (tmp_path / "investify_page.html").read_text("utf-8") == page.decode()
    saved = pol.load_state(state)
    assert saved.etag is None and saved.last_modified is None  # a later real run is not told "unchanged"
    # --unconditional forgets stored validators so a page, not a 304, comes back
    pol.save_state(
        state,
        pol.PollState(robots_txt="User-agent: *\n", robots_fetched_utc=pol._iso(MONDAY_10AM), etag='"old"'),
    )
    t2 = Transport((200, {}, page))
    lj.run(state, out, now=MONDAY_10AM, transport=t2, sleep=lambda s: None, rng=Jitter(), unconditional=True)
    assert "If-None-Match" not in t2.calls[0][1]
