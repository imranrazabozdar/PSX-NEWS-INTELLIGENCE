"""Investify consented collection: rate limit, trading hours, 304, robots.txt, 429/503 backoff, attribution.

All offline. The transport is injected, so no test opens a socket (the fixture refuses sockets).
The database is local SQLite with the real migrations and the real seed registry.
"""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collectors import investify_job as job
from collectors import investify_policy as pol
from collectors.engine import load_source
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "investify" / "announcements_point_in_time_2026-11-11.html"
WATCH = frozenset({"FCL", "PSO", "STL", "THCCL", "TOMCL"})  # the five fixture symbols on the watchlist
SUMMARY_PHRASE = "are not assessed"  # text that appears only in Investify's own summary paragraphs

# Monday 16 Nov 2026 10:00 PKT = 05:00 UTC (inside trading hours); after the consent's effective date.
MONDAY_10AM = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
assert MONDAY_10AM.astimezone(pol.PKT).weekday() == 0


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the consented collector must not open a socket in tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeTransport:
    """Returns queued responses in order and records every call (url and headers)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError(f"unexpected request to {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def page_calls(self):
        return [c for c in self.calls if c[0] == pol.ANNOUNCEMENTS_URL]


def ok_page(headers=None):
    default = {"etag": '"v1"', "last-modified": "Mon, 16 Nov 2026 05:00:00 GMT"}
    return 200, headers or default, FIXTURE.read_bytes()


ROBOTS_ALLOW = (200, {}, b"User-agent: *\nDisallow: /admin\n")
ROBOTS_BLOCK = (200, {}, b"User-agent: *\nDisallow: /announcements\n")


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


@pytest.fixture
def entry(db):
    return load_source(db, pol.SOURCE_ID)


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "investify_state.json"


def _state_with_robots(state_path, now=MONDAY_10AM, **extra):
    st = pol.PollState(robots_txt=ROBOTS_ALLOW[2].decode(), robots_fetched_utc=pol._iso(now), **extra)
    pol.save_state(state_path, st)
    return st


def _stored_count(db) -> int:
    return db.execute("SELECT COUNT(*) AS n FROM source_items WHERE source_id = ?",
                      (pol.SOURCE_ID,))[0]["n"]


def run(now, state_path, entry, db, transport, **kw):
    return job.run_once(now=now, state_path=state_path, entry=entry, db=db, transport=transport,
                        watchlist=WATCH, **kw)


# ------------------------------------------------------------------ consent gates

def test_nothing_is_polled_before_the_consent_is_effective(state_path, entry, db):
    before = datetime(2026, 11, 11, 5, 0, tzinfo=UTC)  # a Wednesday, inside trading hours, but too early
    t = FakeTransport()
    out = run(before, state_path, entry, db, t)
    assert out.status == "skipped" and "not yet effective" in out.reason
    assert t.calls == []


@pytest.mark.parametrize("change,fragment", [
    ({"enabled": 0}, "disabled"),
    ({"lifecycle_status": "RESTRICTED"}, "not APPROVED"),
    ({"terms_status": "prohibits_automation"}, "terms_status"),
    ({"access_method": "not_permitted"}, "access_method"),
])
def test_registry_must_still_say_consented_and_enabled(state_path, entry, db, change, fragment):
    t = FakeTransport()
    out = run(MONDAY_10AM, state_path, replace_entry(entry, change), db, t)
    assert out.status == "refused" and fragment in out.reason and t.calls == []


def replace_entry(entry, change):
    return {**entry, **change}


def test_kill_switch_stops_everything(state_path, entry, db):
    t = FakeTransport()
    out = run(MONDAY_10AM, state_path, entry, db, t, kill_switch=True)
    assert out.status == "skipped" and out.reason == "kill switch is on" and t.calls == []


# ------------------------------------------------------------------ trading-hours gate (PKT, Mon-Fri)

@pytest.mark.parametrize("pkt,allowed", [
    (datetime(2026, 11, 14, 10, 0), False),  # Saturday
    (datetime(2026, 11, 15, 10, 0), False),  # Sunday
    (datetime(2026, 11, 16, 8, 59), False),  # Monday before open
    (datetime(2026, 11, 16, 9, 0), True),    # open
    (datetime(2026, 11, 16, 16, 30), True),  # close (inclusive, as in the existing gate)
    (datetime(2026, 11, 16, 16, 31), False),  # after close
])
def test_trading_hours_gate(pkt, allowed):
    now = pkt.replace(tzinfo=pol.PKT).astimezone(UTC)
    decision = pol.may_poll(now, pol.PollState())
    assert decision.allowed is allowed
    if not allowed:
        assert "trading hours" in decision.reason or "effective" in decision.reason


# ------------------------------------------------------------------ rate limit: one request per 15 minutes

def test_rate_limit_refuses_inside_fifteen_minutes(state_path, entry, db):
    last = MONDAY_10AM - timedelta(minutes=10)
    pol.save_state(state_path, pol.PollState(last_request_utc=pol._iso(last)))
    t = FakeTransport()
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "skipped" and "15 minutes" in out.reason and t.calls == []


def test_rate_limit_allows_exactly_fifteen_minutes(state_path, entry, db):
    last = MONDAY_10AM - timedelta(minutes=15)
    _state_with_robots(state_path, last_request_utc=pol._iso(last))
    t = FakeTransport(ok_page())
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "fetched"


def test_backoff_blocks_polling_until_it_expires(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)),
                       backoff_until_utc=pol._iso(MONDAY_10AM + timedelta(minutes=30)))
    t = FakeTransport()
    out = run(MONDAY_10AM + timedelta(minutes=20), state_path, entry, db, t)
    assert out.status == "skipped" and "backing off" in out.reason and t.calls == []


# ------------------------------------------------------------------ robots.txt

def test_a_stale_robots_cache_is_fetched_as_the_only_request_of_the_run(state_path, entry, db):
    t = FakeTransport(ROBOTS_ALLOW)
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "robots_refreshed" and out.http_requests == 1
    assert [c[0] for c in t.calls] == [pol.ROBOTS_URL]  # no page request in the same run
    assert pol.load_state(state_path).robots_txt


def test_a_disallowed_path_is_never_fetched(state_path, entry, db):
    _state_with_robots(state_path)
    pol.save_state(state_path, replace(pol.load_state(state_path), robots_txt=ROBOTS_BLOCK[2].decode()))
    t = FakeTransport()
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "robots_disallowed" and t.calls == []


def test_robots_unreadable_is_treated_as_disallow_all(state_path, entry, db):
    t = FakeTransport((503, {}, b""))
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "robots_refreshed"
    assert "Disallow: /" in pol.load_state(state_path).robots_txt
    assert not pol.robots_allows(pol.load_state(state_path).robots_txt, pol.ANNOUNCEMENTS_URL)


def test_robots_allows_is_checked_per_path():
    text = "User-agent: *\nDisallow: /announcements\n"
    assert pol.robots_allows(text, "https://www.investify.pk/") is True
    assert pol.robots_allows(text, pol.ANNOUNCEMENTS_URL) is False


# ------------------------------------------------------------------ conditional requests and 304

def test_etag_and_if_modified_since_are_sent_and_304_is_a_no_op(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)),
                       etag='"v1"', last_modified="Mon, 16 Nov 2026 05:00:00 GMT")
    t = FakeTransport((304, {}, b""))
    out = run(MONDAY_10AM, state_path, entry, db, t)
    sent = t.page_calls[0][1]
    assert sent["If-None-Match"] == '"v1"' and sent["If-Modified-Since"] == "Mon, 16 Nov 2026 05:00:00 GMT"
    assert out.status == "not_modified" and out.new == 0
    assert _stored_count(db) == 0
    st = pol.load_state(state_path)
    assert st.etag == '"v1"' and st.last_request_utc == pol._iso(MONDAY_10AM)


# ------------------------------------------------------------------ 429 / 503 backoff: stop, no retry storm

def test_429_stops_the_run_without_a_retry_and_honours_retry_after(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
    t = FakeTransport((429, {"retry-after": "1800"}, b""))
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "backoff" and len(t.page_calls) == 1
    assert pol.load_state(state_path).backoff_until_utc == pol._iso(MONDAY_10AM + timedelta(minutes=30))


def test_503_without_retry_after_backs_off_an_hour(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
    t = FakeTransport((503, {}, b""))
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "backoff" and len(t.page_calls) == 1
    assert pol.load_state(state_path).backoff_until_utc == pol._iso(MONDAY_10AM + timedelta(hours=1))


def test_a_huge_retry_after_is_capped_at_six_hours():
    until = pol.backoff_until(MONDAY_10AM, "864000")
    assert until == MONDAY_10AM + pol.BACKOFF_CAP


def test_a_retry_after_date_is_honoured():
    until = pol.backoff_until(MONDAY_10AM, "Mon, 16 Nov 2026 07:00:00 GMT")
    assert until == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)


# ------------------------------------------------------------------ storage: metadata only, attributed

def test_a_200_stores_only_watchlist_metadata_with_attribution_and_no_summary(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
    t = FakeTransport(ok_page())
    out = run(MONDAY_10AM, state_path, entry, db, t)
    assert out.status == "fetched" and out.http_requests == 1 and out.new == 5
    rows = db.execute("SELECT * FROM source_items WHERE source_id = ?", (pol.SOURCE_ID,))
    assert len(rows) == 5
    assert sorted(r["title"] for r in rows)[0].startswith("Fast Cables")
    for r in rows:
        blob = json.dumps(dict(r), default=str, ensure_ascii=False)
        assert pol.ATTRIBUTION in blob  # attribution travels with the stored metadata
        assert SUMMARY_PHRASE not in blob  # Investify's own summary text is never stored
        for key in dict(r):
            if "excerpt" in key:
                assert dict(r)[key] is None


def test_a_second_identical_poll_adds_nothing(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
    run(MONDAY_10AM, state_path, entry, db, FakeTransport(ok_page()))
    later = MONDAY_10AM + timedelta(minutes=15)
    out = run(later, state_path, entry, db, FakeTransport(ok_page()))
    assert out.status == "fetched" and out.new == 0 and out.duplicates == 5


def test_dry_run_returns_what_would_be_stored_and_writes_nothing(state_path, entry, db):
    _state_with_robots(state_path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
    t = FakeTransport(ok_page())
    out = run(MONDAY_10AM, state_path, entry, db, t, dry_run=True)
    assert len(out.records) == 5 and out.new == 0
    assert _stored_count(db) == 0


# ------------------------------------------------------------------ budget: at most one request per run

def test_no_branch_makes_more_than_one_request(state_path, entry, db):
    scenarios = [
        (None, FakeTransport(ROBOTS_ALLOW)),
        (None, FakeTransport((304, {}, b""))),
        (None, FakeTransport((429, {}, b""))),
        (None, FakeTransport((500, {}, b""))),
        (None, FakeTransport(ok_page())),
    ]
    for i, (_, t) in enumerate(scenarios):
        path = state_path.parent / f"s{i}.json"
        _state_with_robots(path, last_request_utc=pol._iso(MONDAY_10AM - timedelta(hours=1)))
        run(MONDAY_10AM, path, entry, db, t)
        assert len(t.calls) <= 1, t.calls


# ------------------------------------------------------------------ state file

def test_state_round_trips_and_a_missing_file_is_empty(tmp_path):
    p = tmp_path / "s.json"
    assert pol.load_state(p) == pol.PollState()
    st = pol.PollState(last_request_utc="2026-11-16T05:00:00Z", etag='"x"')
    pol.save_state(p, st)
    assert pol.load_state(p) == st


def test_the_user_agent_identifies_the_project_and_the_consent():
    assert "psx-news-intelligence" in pol.USER_AGENT and "consented research" in pol.USER_AGENT
    assert "@" not in pol.USER_AGENT  # no personal contact details in outbound requests


# ------------------------------------------------------------------ generic engine never fetches it

@pytest.mark.parametrize("dry_run", [True, False])
def test_the_generic_engine_refuses_the_consent_governed_source(entry, dry_run):
    from collectors.engine import CollectionRefused, authorise

    with pytest.raises(CollectionRefused, match="consent-bound job"):
        authorise(entry, dry_run=dry_run)


# ------------------------------------------------------------------ validator keeps consent rules

def test_the_validator_rejects_a_consent_governed_source_without_its_terms():
    from database.validation import validate_source_registry

    data = json.loads((ROOT / "database" / "seed" / "sources.json").read_text(encoding="utf-8"))
    for s in data["sources"]:
        if s["source_id"] == pol.SOURCE_ID:
            s["terms_status"] = "prohibits_automation"
            s["access_method"] = "not_permitted"
    errors = validate_source_registry(data)
    assert any("terms_status approved" in e for e in errors)
    assert any("access_method html_permitted" in e for e in errors)
