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


def seeded_state(path: Path) -> None:
    pol.save_state(
        path,
        pol.PollState(
            robots_txt="User-agent: *\nDisallow: /admin\n", robots_fetched_utc=pol._iso(MONDAY_10AM)
        ),
    )


def run(tmp_path, transport):
    state, out = tmp_path / "state.json", tmp_path / "facts.json"
    seeded_state(state)
    code = lj.run(state, out, now=MONDAY_10AM, transport=transport, sleep=lambda s: None, rng=Jitter())
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


def test_no_investify_summary_text_is_stored(tmp_path):
    t = Transport((200, {}, FIXTURE.read_bytes()))
    _, out = run(tmp_path, t)
    text = out.read_text("utf-8")
    assert "are not assessed" not in text  # appears only in Investify's own summary paragraphs


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
