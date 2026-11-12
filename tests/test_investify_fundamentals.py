"""Investify fundamentals, profile, competitors and industry under consent.

Record: docs/consent/investify-fundamentals-2026-11-12.md.

All offline. The transport is injected; no test opens a socket. The database is local SQLite with the real
migrations and the real seed registry. The endpoint paths used here are TEST paths: the production ENDPOINTS
are unconfirmed on purpose. Bodies are SYNTHETIC; no test contains Investify data.
"""

from __future__ import annotations

import ast
import json
import random
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collectors import investify_fundamentals as fund
from collectors import investify_policy as pol
from collectors.engine import load_source
from collectors.investify_job import AuditLog
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import investify_collector as ic

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # Monday 10:00 PKT, inside trading hours, after consent
assert NOW.astimezone(pol.PKT).weekday() == 0
TEST_ENDPOINTS = {
    "fundamentals": fund.Endpoint("fundamentals", "/company/{symbol}/fundamentals", "announcement"),
    "profile": fund.Endpoint("profile", "/company/{symbol}/profile", "backfill_once"),
    "announcements": fund.Endpoint("announcements", "/company/{symbol}/announcements", "feed"),
}
ALLOW = "User-agent: *\nDisallow: /admin\n"
SAVED_PAGE = ROOT / "tests" / "fixtures" / "investify" / "announcements_point_in_time_2026-11-11.html"
SYNTHETIC_PROFILE = ROOT / "tests" / "fixtures" / "investify" / "profile_synthetic.html"
SYNTHETIC_FEED = ROOT / "tests" / "fixtures" / "investify" / "announcements_synthetic.html"
CFG = pol.PolicyConfig(jitter_min=1, jitter_max=1)  # deterministic, tiny jitter


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the consented fundamentals client must not open a socket in tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError(f"unexpected request to {url}")
        return self.responses.pop(0)

    def page_calls(self, suffix):
        return [c for c in self.calls if c[0].endswith(suffix)]


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


@pytest.fixture
def entry(db):
    # the seed is DISABLED until the owner approves; tests enable a copy of it, never the seed itself
    return {**load_source(db, fund.SOURCE_ID), "enabled": 1}


@pytest.fixture
def state_path(tmp_path):
    p = tmp_path / "state.json"
    pol.save_state(p, pol.PollState(robots_txt=ALLOW, robots_fetched_utc=pol._iso(NOW)))
    return p


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def announcement(symbol, category="financial_results", at=NOW - timedelta(hours=1), title="Half year result"):
    return ic.AnnouncementRecord(
        symbol=symbol, company_name=f"{symbol} Ltd", announced_at_utc=pol._iso(at),
        announced_on_pkt="2026-11-16", title=title, investify_label="", category=category,
        sentiment_label="", source="investify", source_url=f"https://www.investify.pk/announcements/{symbol}/x",
        pdf_url=None, pdf_access="none", retrieved_at_utc=pol._iso(NOW),
        content_sha256=f"{symbol}-{category}-{title}-{at.isoformat()}")


def queue(state_path, *records, now=NOW):
    st, queued = fund.enqueue_from_announcements(pol.load_state(state_path), list(records), now=now)
    pol.save_state(state_path, st)
    return queued


def run(db, entry, state_path, audit, transport, *, endpoint="fundamentals", symbol="FCL", now=NOW,
        manual=False, cfg=CFG, watch=frozenset({"FCL", "PSO"}), endpoints=TEST_ENDPOINTS):
    return fund.run_endpoint(now=now, state_path=state_path, entry=entry, db=db, endpoint=endpoint,
                             symbol=symbol, watchlist=watch, endpoints=endpoints, manual=manual,
                             transport=transport, cfg=cfg, rng=random.Random(7),  # noqa: S311 - test jitter
                           audit=audit)


def ok(body: str, headers=None):
    return 200, headers or {"etag": '"v1"', "last-modified": "Mon, 16 Nov 2026 04:00:00 GMT"}, body.encode()


def stored(db):
    return db.execute("SELECT * FROM source_items WHERE source_id = ? ORDER BY source_item_id",
                      (fund.SOURCE_ID,))


def audit_events(audit):
    if not audit.path.exists():
        return []
    return [json.loads(x) for x in audit.path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ rule (a): fundamentals on event only

def test_fundamentals_are_never_fetched_without_a_new_financial_result(db, entry, state_path, audit):
    t = FakeTransport()  # any request would fail the test
    out = run(db, entry, state_path, audit, t)
    assert out.status == "skipped" and "no pending financial-result announcement" in out.reason
    assert t.calls == []


def test_a_non_financial_announcement_queues_no_fundamentals_refresh(db, entry, state_path, audit):
    queued = queue(state_path, announcement("FCL", category="board_meeting", title="Board meeting"))
    assert queued == []
    assert run(db, entry, state_path, audit, FakeTransport()).status == "skipped"


def test_a_new_financial_result_queues_exactly_one_refresh(state_path):
    rec = announcement("FCL")
    first = queue(state_path, rec)
    again = queue(state_path, rec)  # the same announcement seen again on a later poll
    assert len(first) == 1 and again == []
    assert pol.load_state(state_path).pending_triggers[0]["announcement_id"] == rec.content_sha256


def test_an_old_financial_result_is_seen_but_not_queued_once_the_company_has_fundamentals(state_path):
    old = announcement("FCL", at=NOW - timedelta(days=10))
    st, queued = fund.enqueue_from_announcements(pol.load_state(state_path), [old], now=NOW,
                                                 has_fundamentals={"FCL": True})
    assert queued == []
    assert old.content_sha256 in st.seen_announcements


def test_fundamentals_cannot_be_refreshed_manually(db, entry, state_path, audit):
    out = run(db, entry, state_path, audit, FakeTransport(), manual=True)
    assert out.status == "refused" and "not manually" in out.reason


# ------------------------------------------------------------------ rule (b): profile backfilled once

def test_profile_is_backfilled_once_then_only_refreshed_manually(db, entry, state_path, audit):
    t = FakeTransport(ok("<p>profile v1</p>"), ok("<p>profile v2</p>"))
    first = run(db, entry, state_path, audit, t, endpoint="profile", symbol="FCL")
    assert first.status == "fetched" and len(stored(db)) == 1
    later = run(db, entry, state_path, audit, t, endpoint="profile", symbol="FCL",
                now=NOW + timedelta(hours=2))
    assert later.status == "skipped" and "backfilled" in later.reason
    assert len(t.calls) == 1  # the scheduler path made no second request
    manual = run(db, entry, state_path, audit, t, endpoint="profile", symbol="FCL",
                 now=NOW + timedelta(hours=3), manual=True)
    assert manual.status == "fetched" and len(t.calls) == 2


# ------------------------------------------------------------------ the rate cap

def test_one_request_per_fifteen_minutes_across_all_endpoints(db, entry, state_path, audit):
    t = FakeTransport(ok("<p>fund FCL</p>"), ok("<p>fund PSO</p>"))
    queue(state_path, announcement("FCL"))
    assert run(db, entry, state_path, audit, t, symbol="FCL").status == "fetched"
    queue(state_path, announcement("PSO", at=NOW + timedelta(minutes=4)), now=NOW + timedelta(minutes=5))
    early = run(db, entry, state_path, audit, t, symbol="PSO", now=NOW + timedelta(minutes=5))
    assert early.status == "skipped" and "queued" in early.reason
    assert len(t.calls) == 1
    later = run(db, entry, state_path, audit, t, symbol="PSO", now=NOW + timedelta(minutes=16))
    assert later.status == "fetched"
    assert len(t.calls) == 2


def test_the_rate_cap_holds_for_profile_requests_too(db, entry, state_path, audit):
    t = FakeTransport(ok("<p>fund</p>"))
    queue(state_path, announcement("FCL"))
    run(db, entry, state_path, audit, t, symbol="FCL")
    out = run(db, entry, state_path, audit, t, endpoint="profile", symbol="PSO",
              now=NOW + timedelta(minutes=2))
    assert out.status == "skipped" and "queued" in out.reason and len(t.calls) == 1


# ------------------------------------------------------------------ conditional requests and 304

def test_a_304_is_a_recorded_no_op(db, entry, state_path, audit):
    feed = SYNTHETIC_FEED.read_text(encoding="utf-8")
    t = FakeTransport(ok(feed), (304, {}, b""))
    assert run(db, entry, state_path, audit, t, endpoint="announcements", symbol="FCL").status == "fetched"
    before = len(stored(db))
    out = run(db, entry, state_path, audit, t, endpoint="announcements", symbol="FCL",
              now=NOW + timedelta(minutes=20))
    assert out.status == "not_modified" and len(stored(db)) == before  # nothing written
    assert t.calls[1][1].get("If-None-Match") == '"v1"'  # the conditional header was sent
    events = [e for e in audit_events(audit) if e["event"] == "endpoint_request"]
    assert events[-1]["status"] == 304 and events[-1]["outcome"] == "not_modified"
def test_a_robots_disallowed_path_is_never_fetched(db, entry, audit, tmp_path):
    p = tmp_path / "state.json"
    pol.save_state(p, pol.PollState(robots_txt="User-agent: *\nDisallow: /company/\n",
                                    robots_fetched_utc=pol._iso(NOW)))
    queue(p, announcement("FCL"))
    t = FakeTransport()
    out = run(db, entry, p, audit, t)
    assert out.status == "skipped" and "robots.txt disallows" in out.reason and t.calls == []


def test_a_stale_robots_copy_blocks_the_request(db, entry, audit, tmp_path):
    p = tmp_path / "state.json"
    pol.save_state(p, pol.PollState(robots_txt=ALLOW, robots_fetched_utc=pol._iso(NOW - timedelta(days=2))))
    queue(p, announcement("FCL"))
    t = FakeTransport()
    assert run(db, entry, p, audit, t).status == "skipped" and t.calls == []


def test_429_backs_off_and_keeps_the_trigger_pending(db, entry, state_path, audit):
    t = FakeTransport((429, {"retry-after": "1800"}, b""))
    queue(state_path, announcement("FCL"))
    out = run(db, entry, state_path, audit, t)
    assert out.status == "backoff" and "cooldown" in out.reason
    st = pol.load_state(state_path)
    assert st.cooldown_until_utc and len(st.pending_triggers) == 1  # the trigger stays pending
    later = run(db, entry, state_path, audit, t, now=NOW + timedelta(minutes=20))
    assert later.status == "skipped" and "cooldown" in later.reason and len(t.calls) == 1


def test_an_unconfirmed_path_is_refused_with_no_request(db, entry, state_path, audit):
    queue(state_path, announcement("FCL"))
    t = FakeTransport()
    unset = {"profile": fund.Endpoint("profile", None, "backfill_once")}  # a path not yet confirmed
    out = run(db, entry, state_path, audit, t, endpoint="profile", endpoints=unset)
    assert out.status == "refused" and "not yet confirmed" in out.reason and t.calls == []


def test_the_kill_switch_stops_everything(db, entry, state_path, audit):
    queue(state_path, announcement("FCL"))
    t = FakeTransport()
    out = run(db, entry, state_path, audit, t, cfg=replace(CFG, kill_switch=True))
    assert out.status == "skipped" and t.calls == []


def test_the_seed_entry_is_enabled_under_its_own_consent_record(db):
    seed = load_source(db, fund.SOURCE_ID)
    assert seed["enabled"] == 1 and seed["lifecycle_status"] == "APPROVED"
    assert pol.registry_problem(seed, source_id=fund.SOURCE_ID, consent_record=fund.CONSENT_RECORD) is None
    assert seed["retention_mode"] == "metadata_only"  # structured fields only


def test_every_stored_record_carries_the_investify_attribution(db, entry, state_path, audit):
    t = FakeTransport(ok(SYNTHETIC_PROFILE.read_text(encoding="utf-8")))
    run(db, entry, state_path, audit, t, endpoint="profile", symbol="FCL")
    rows = stored(db)
    assert len(rows) == 1
    meta = json.loads(rows[0]["source_metadata_json"])
    assert meta["source"] == "investify.pk"
    assert meta["attribution"] == pol.ATTRIBUTION
    assert meta["storage"] == "structured_fields_only"
    assert rows[0]["external_id"] == "FCL:profile"


def test_storage_is_the_operational_database_and_never_the_archive():
    """The module writes through record_source_item only; it imports no archive or financial repository."""
    tree = ast.parse((ROOT / "collectors" / "investify_fundamentals.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("archive" in m or m == "database.financial_repo" for m in imported)
    assert "database.repositories" in imported


# ------------------------------------------------------------------ the acceptance flow, on synthetic bodies

def test_one_company_end_to_end_profile_then_feed_under_the_cap(db, entry, state_path, audit):
    """A backfill runs first; the announcements feed then queues the first fill. Backfill yields to pending
    triggers, so the order matters and the test pins it. Requests are 16 minutes apart."""
    announcements_url = "https://www.investify.pk/company/FCL/announcements"
    synthetic_feed = (ROOT / "tests" / "fixtures" / "investify" / "announcements_synthetic.html").read_text(
        encoding="utf-8")
    t = FakeTransport(ok(SYNTHETIC_PROFILE.read_text(encoding="utf-8")), ok(synthetic_feed))
    prof = run(db, entry, state_path, audit, t, endpoint="profile", symbol="FCL")
    assert prof.status == "fetched"
    feed = run(db, entry, state_path, audit, t, endpoint="announcements", symbol="FCL",
               now=NOW + timedelta(minutes=16))
    assert feed.status == "fetched"
    pending = pol.load_state(state_path).pending_triggers
    assert len(pending) == 1 and pending[0]["kind"] == "first_fill"  # no fundamentals on record yet
    rows = stored(db)
    assert sorted(r["external_id"] for r in rows) == ["FCL:announcements", "FCL:profile"]
    assert all(json.loads(r["source_metadata_json"])["source"] == "investify.pk" for r in rows)
    fetches = [e for e in audit_events(audit) if e["event"] == "endpoint_request"]
    assert [f["url"] for f in fetches] == ["https://www.investify.pk/company/FCL/profile", announcements_url]
    gap = (datetime.fromisoformat(fetches[1]["ts_utc"].replace("Z", "+00:00"))
           - datetime.fromisoformat(fetches[0]["ts_utc"].replace("Z", "+00:00")))
    assert gap >= pol.MIN_INTERVAL  # the 15-minute cap held between the two requests


def _run_announcements_job(db, tmp_path, html: str, name: str):
    from collectors import investify_job as job

    page_time = datetime(2026, 11, 12, 5, 30, tzinfo=UTC)  # Thursday 10:30 PKT: after consent, in hours
    watch = frozenset({"FCL", "PSO", "STL", "THCCL", "TOMCL"})
    state_path = tmp_path / f"{name}.json"
    pol.save_state(state_path, pol.PollState(robots_txt=ALLOW, robots_fetched_utc=pol._iso(page_time)))
    outcome = job.run_once(now=page_time, state_path=state_path, entry=load_source(db, pol.SOURCE_ID), db=db,
                           transport=FakeTransport(ok(html)), watchlist=watch, cfg=CFG, sleep=lambda s: None,
                           rng=random.Random(3),  # noqa: S311 - test jitter
                           audit=AuditLog(tmp_path / f"{name}.jsonl"))
    assert outcome.status == "fetched"
    return pol.load_state(state_path).pending_triggers


def test_the_announcements_job_queues_nothing_from_the_saved_real_page(db, tmp_path):
    """Negative case: the saved page (2026-11-11) has no financial result, so nothing is queued."""
    html = SAVED_PAGE.read_text(encoding="utf-8")
    assert _run_announcements_job(db, tmp_path, html, "real") == []


def test_the_announcements_job_queues_one_trigger_for_a_financial_result(db, tmp_path):
    """Positive case. SYNTHETIC: one card's title on the saved page is changed to a financial result."""
    html = SAVED_PAGE.read_text(encoding="utf-8")
    old = "Fast Cables publishes annual progress report"
    assert html.count(old) >= 1  # the title appears in the card heading and in the structured data
    html = html.replace(old, "Fast Cables announces half-year financial results")
    pending = _run_announcements_job(db, tmp_path, html, "synthetic")
    assert [t["symbol"] for t in pending] == ["FCL"]
    assert pending[0]["announced_at_utc"].startswith("2026-11-11")


# ------------------------------------------------- first fill and refresh rules (owner, 2026-11-12)

def _ann(days_ago, title, category="financial_results", symbol="FCL"):
    return announcement(symbol, category=category, at=NOW - timedelta(days=days_ago), title=title)


def test_first_fill_seeds_from_the_latest_result_even_if_older_than_three_days():
    old = _ann(20, "Financial Results For The Year")
    latest = _ann(15, "Financial Result For The First Quarter")
    st, queued = fund.enqueue_from_announcements(pol.PollState(), [old, latest], now=NOW,
                                                 has_fundamentals={"FCL": False})
    assert len(queued) == 1
    assert queued[0]["kind"] == "first_fill"
    assert queued[0]["announcement_id"] == latest.content_sha256  # the MOST RECENT qualifying result
    assert "FCL" in st.first_filled_symbols


def test_first_fill_happens_once_per_company():
    latest = _ann(15, "Financial Result For The First Quarter")
    st, _ = fund.enqueue_from_announcements(pol.PollState(), [latest], now=NOW, has_fundamentals={})
    st2, queued = fund.enqueue_from_announcements(st, [latest], now=NOW + timedelta(hours=1),
                                                  has_fundamentals={})
    assert queued == []
    assert len(st2.pending_triggers) == 1  # still the one first-fill item, not a second one


def test_a_company_with_fundamentals_on_record_gets_no_first_fill():
    latest = _ann(15, "Financial Result For The First Quarter")
    st, queued = fund.enqueue_from_announcements(pol.PollState(), [latest], now=NOW,
                                                 has_fundamentals={"FCL": True})
    assert queued == [] and st.first_filled_symbols == []


def test_an_already_seen_result_never_retriggers():
    fresh = _ann(1, "Financial Result For The Half Year")
    st, first = fund.enqueue_from_announcements(pol.PollState(), [fresh], now=NOW,
                                                has_fundamentals={"FCL": True})
    assert len(first) == 1 and first[0]["kind"] == "refresh"
    st = replace(st, pending_triggers=[], consumed_triggers=[fresh.content_sha256])
    st2, again = fund.enqueue_from_announcements(st, [fresh], now=NOW + timedelta(hours=2),
                                                 has_fundamentals={"FCL": True})
    assert again == []
    assert fresh.content_sha256 in st2.seen_announcements


def test_after_first_fill_only_results_newer_than_the_last_one_seen_refresh():
    anchor = _ann(15, "Financial Result For The First Quarter")
    st, _ = fund.enqueue_from_announcements(pol.PollState(), [anchor], now=NOW, has_fundamentals={})
    st = replace(st, pending_triggers=[])
    older = _ann(25, "Financial Results For The Year Before")  # older than the anchor: never a refresh
    st2, queued = fund.enqueue_from_announcements(st, [older], now=NOW, has_fundamentals={"FCL": True})
    assert queued == []


def test_a_newer_result_within_the_window_refreshes_once():
    anchor = _ann(15, "Financial Result For The First Quarter")
    st, _ = fund.enqueue_from_announcements(pol.PollState(), [anchor], now=NOW, has_fundamentals={})
    st = replace(st, pending_triggers=[])
    newer = _ann(1, "Financial Result For The Half Year")
    st2, queued = fund.enqueue_from_announcements(st, [anchor, newer], now=NOW,
                                                  has_fundamentals={"FCL": True})
    assert len(queued) == 1 and queued[0]["kind"] == "refresh"
    assert queued[0]["announcement_id"] == newer.content_sha256


def test_first_fill_seeds_from_a_financial_result_not_a_newer_report_transmission():
    result = _ann(15, "Financial Result For The First Quarter")
    transmission = _ann(15, "Transmission Of Quarterly Report", category="report_transmission")
    transmission = replace(transmission, announced_at_utc=pol._iso(NOW - timedelta(days=14)))  # newer
    st, queued = fund.enqueue_from_announcements(pol.PollState(), [result, transmission], now=NOW,
                                                 has_fundamentals={"FCL": False})
    assert len(queued) == 1 and queued[0]["announcement_id"] == result.content_sha256


def test_a_first_fill_is_never_recorded_as_manual():
    assert fund.manual_refresh_flag(True, {"kind": "first_fill"}) is False
    assert fund.manual_refresh_flag(False, None) is False
    assert fund.manual_refresh_flag(True, None) is True  # a genuine manual refresh is still recorded as one


def test_the_audit_flag_on_a_first_fill_request_is_false(db, entry, state_path, audit):
    # a financial result queues a first fill (no fundamentals on record yet)
    queue(state_path, announcement("FCL"))
    t = FakeTransport(ok(SYNTHETIC_FEED.read_text(encoding="utf-8")))
    run(db, entry, state_path, audit, t, endpoint="fundamentals", symbol="FCL", manual=False)
    events = [e for e in audit_events(audit) if e["event"] == "endpoint_request"]
    assert len(events) == 1 and events[0]["manual"] is False  # no manual label on a triggered request
