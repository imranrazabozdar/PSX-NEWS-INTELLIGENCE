"""Phase 2 collection engine tests. Deterministic: no network, fixtures only, local SQLite."""

from __future__ import annotations

import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from collectors import engine
from collectors.engine import CollectionRefused, collect, collect_document, due_sources, fetch_pages
from collectors.http import MAX_BYTES, FetchError, HttpClient, RobotsDisallowed
from collectors.parsers import (
    ParseError,
    document_info,
    parse_feed,
    parse_html_table,
    parse_json_api,
    parse_timestamp,
)
from database import seed_loader
from database.connection import DatabaseBudgetError, DatabaseError, SQLiteDatabase
from database.migrate import migrate

FIX = Path(__file__).parent / "fixtures"
RSS = (FIX / "rss_sample.xml").read_bytes()
ATOM = (FIX / "atom_sample.xml").read_bytes()
FEED_URL = "https://news.example.com/feed"
REVIEWED_SOURCE = {"source_id": "fixture", "lifecycle_status": "TESTED", "access_status": "unverified",
                   "terms_status": "not_found", "licensing_status": "unknown", "access_method": "rss"}


# ---------------------------------------------------------------- helpers
def _http_error(code, headers=None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x.example/", code, "err", msg, None)


class FakeNet:
    """Scripted transport. routes: url -> list of responses (tuple or exception), consumed in order."""

    def __init__(self, routes=None, robots=b"User-agent: *\nDisallow:\n"):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.robots = robots
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        if url.endswith("/robots.txt"):
            if isinstance(self.robots, Exception):
                raise self.robots
            return 200, {}, self.robots
        queue = self.routes.get(url)
        if not queue:
            raise _http_error(404)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def client_for(net, **kw):
    slept = []
    c = HttpClient(transport=net, sleep=slept.append, min_interval=0, **kw)
    c.slept = slept  # type: ignore[attr-defined]
    return c


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def make_active(db, source_id="test_feed", feed_url=FEED_URL, retention="metadata_only"):
    """Register a synthetic ACTIVE source the way an approved activation would."""
    db.execute(
        """INSERT INTO sources(source_id, name, source_type, enabled, created_at_utc, updated_at_utc,
               access_status, terms_status, lifecycle_status, adapter, feed_url, retention_mode,
               collection_frequency_minutes, priority)
           VALUES (?, 'Synthetic test feed', 'news_media', 1, '2026-11-07T00:00:00Z',
               '2026-11-07T00:00:00Z', 'verified_permitted', 'approved', 'ACTIVE', 'rss', ?, ?, 60, 2)""",
        (source_id, feed_url, retention))
    return source_id


def count(db, table):
    return db.execute(f"SELECT COUNT(*) n FROM {table}")[0]["n"]  # noqa: S608 - test helper


# ---------------------------------------------------------------- parsers
def test_rss_parsing_and_timestamps():
    kind, entries = parse_feed(RSS)
    assert kind == "rss" and len(entries) == 4
    e = entries[0]
    assert e.title == "Synthetic headline one & more"
    assert e.summary == "Synthetic summary one ."
    assert e.external_id == "https://news.example.com/story/1"
    assert e.metadata["categories"] == ["Business"]
    t = [parse_timestamp(x.published_raw) for x in entries]
    assert t[0].utc == "2026-11-07T15:26:16Z" and t[0].offset == "+05:00"
    assert t[1].utc == "2026-11-07T07:58:41Z"  # two-digit year
    assert t[2].utc == "2026-11-06T14:00:00Z"  # EST, CDATA, double space
    assert (t[3].utc, t[3].status) == (None, "unavailable")  # never filled with retrieval time


def test_atom_parsing():
    kind, entries = parse_feed(ATOM)
    assert kind == "atom" and [e.url for e in entries] == [
        "https://official.example.org/notice/10", "https://official.example.org/notice/11"]
    assert parse_timestamp(entries[0].published_raw).utc == "2026-11-05T05:00:00Z"
    assert entries[1].published_raw == "2026-11-06T12:00:00Z"  # falls back to <updated>


def test_date_only_and_garbage_timestamps():
    assert parse_timestamp("2026-11-05").status == "date_only"
    assert parse_timestamp("sometime soon").status == "unavailable"
    assert parse_timestamp("Fri, Nov 6, 2026 4:48 PM").status == "unavailable"  # no zone: not guessed


def test_malformed_and_dangerous_xml_refused():
    with pytest.raises(ParseError, match="malformed"):
        parse_feed(b"<rss><channel><item></rss>")
    with pytest.raises(ParseError, match="DOCTYPE"):
        parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss>&a;</rss>')
    with pytest.raises(ParseError, match="not an RSS"):
        parse_feed(b"<html><body>not a feed</body></html>")


def test_json_api_parsing():
    data = (FIX / "api_sample.json").read_bytes()
    entries = parse_json_api(data, items_key="data.results", fields={
        "title": "headline", "url": "link", "external_id": "id", "published_raw": "date"})
    assert [e.external_id for e in entries] == ["A-1", "A-2"]  # non-object skipped
    assert entries[1].published_raw is None
    with pytest.raises(ParseError):
        parse_json_api(b"{broken", items_key="x", fields={})
    with pytest.raises(ParseError):
        parse_json_api(data, items_key="data.missing", fields={})


def test_permitted_html_listing_extraction():
    rows = parse_html_table((FIX / "listing_sample.html").read_bytes(),
                            base_url="https://official.example.org/notices/")
    assert [r["cells"][1] for r in rows[1:]] == ["Synthetic notification one", "Synthetic notification two"]
    assert rows[1]["links"] == ["https://official.example.org/docs/one.pdf"]
    with pytest.raises(ParseError):
        parse_html_table(b"\xff\xfe\x00", base_url="https://x.example/")


def test_pdf_document_metadata():
    body = b"%PDF-1.7\n% synthetic\n"
    info = document_info("https://official.example.org/a.pdf",
                         {"content-type": "application/pdf",
                          "last-modified": "Thu, 05 Nov 2026 10:00:00 GMT"},
                         body)
    assert info.is_pdf and info.pdf_version == "1.7" and info.size_bytes == len(body)
    with pytest.raises(ParseError, match="not a PDF"):
        document_info("https://x.example/a.pdf", {"content-type": "application/pdf"}, b"<html>")
    with pytest.raises(ParseError, match="empty"):
        document_info("https://x.example/a.pdf", {}, b"")


# ---------------------------------------------------------------- HTTP client
def test_retry_with_backoff_then_success():
    net = FakeNet({FEED_URL: [_http_error(503), (200, {}, RSS)]})
    c = client_for(net)
    assert c.get(FEED_URL).status == 200
    assert c.slept == [2.0]  # exponential backoff base 2


def test_rate_limited_429_honours_retry_after():
    net = FakeNet({FEED_URL: [_http_error(429, {"Retry-After": "7"}), (200, {}, RSS)]})
    c = client_for(net)
    c.get(FEED_URL)
    assert 7.0 in c.slept


def test_retry_after_is_capped():
    net = FakeNet({FEED_URL: [_http_error(503, {"Retry-After": "9999"}), (200, {}, RSS)]})
    c = client_for(net, max_retry_after=30)
    c.get(FEED_URL)
    assert c.slept == [30]


def test_timeouts_retry_then_fail():
    net = FakeNet({FEED_URL: [TimeoutError("slow")]})
    c = client_for(net, max_attempts=3)
    with pytest.raises(FetchError, match="after 3 attempts"):
        c.get(FEED_URL)
    assert sum(1 for u, _ in net.calls if u == FEED_URL) == 3


def test_client_errors_are_not_retried():
    net = FakeNet({FEED_URL: [_http_error(404)]})
    c = client_for(net)
    with pytest.raises(FetchError) as exc:
        c.get(FEED_URL)
    assert exc.value.status == 404 and sum(1 for u, _ in net.calls if u == FEED_URL) == 1


def test_robots_disallow_is_respected():
    net = FakeNet({FEED_URL: [(200, {}, RSS)]}, robots=b"User-agent: *\nDisallow: /feed\n")
    with pytest.raises(RobotsDisallowed):
        client_for(net).get(FEED_URL)
    assert all(not u.endswith("/feed") for u, _ in net.calls)  # never fetched


def test_robots_forbidden_means_disallow():
    net = FakeNet({FEED_URL: [(200, {}, RSS)]}, robots=_http_error(403))
    with pytest.raises(FetchError):
        client_for(net, max_attempts=1).get(FEED_URL)


def test_per_host_rate_limit():
    net = FakeNet({FEED_URL: [(200, {}, RSS)]})
    times = iter([0.0, 0.0, 0.5, 0.5, 0.5, 0.5])
    slept = []
    c = HttpClient(transport=net, sleep=slept.append, clock=lambda: next(times), min_interval=2.0)
    c.get(FEED_URL)
    assert slept and abs(slept[0] - 1.5) < 1e-9


def test_conditional_request_headers_and_304():
    net = FakeNet({FEED_URL: [(304, {}, b"")]})
    r = client_for(net).get(FEED_URL, etag='"abc"', last_modified="Sat, 07 Nov 2026 10:00:00 GMT")
    assert r.not_modified
    sent = [h for u, h in net.calls if u == FEED_URL][0]
    assert sent["If-None-Match"] == '"abc"' and sent["If-Modified-Since"].startswith("Sat")


def test_oversized_response_refused():
    net = FakeNet({FEED_URL: [(200, {}, b"x" * (MAX_BYTES + 1))]})
    with pytest.raises(FetchError, match="larger than"):
        client_for(net, max_attempts=1).get(FEED_URL)


def test_pagination_stops_on_empty_page_and_errors():
    base = "https://api.example.org/list?page="
    net = FakeNet({base + "1": [(200, {}, b"[1]")], base + "2": [(200, {}, b"[2]")],
                   base + "3": [(200, {}, b"  ")]})
    pages = fetch_pages(client_for(net), base + "1", source=REVIEWED_SOURCE, dry_run=True,
                        next_url=lambda r, n: f"{base}{n + 1}", max_pages=10)
    assert [p.body for p in pages] == [b"[1]", b"[2]"]
    net2 = FakeNet({base + "1": [(200, {}, b"[1]")], base + "2": [_http_error(500)]})
    pages2 = fetch_pages(client_for(net2, max_attempts=1), base + "1", source=REVIEWED_SOURCE, dry_run=True,
                         next_url=lambda r, n: f"{base}{n + 1}")
    assert len(pages2) == 1  # partial: earlier pages kept


# ---------------------------------------------------------------- engine: policy
def test_non_active_sources_are_never_collected_for_real(db):
    with pytest.raises(CollectionRefused, match="only ACTIVE"):
        collect(db, "thenews", client=client_for(FakeNet()))  # IMPLEMENTED, stale, not owner-approved
    with pytest.raises(CollectionRefused, match="dry runs are not permitted"):
        collect(db, "psx", client=client_for(FakeNet()), dry_run=True)


def _prohibited(db):
    rows = db.execute("SELECT * FROM sources ORDER BY source_id")
    out = []
    for r in rows:
        try:
            engine.authorise(r, dry_run=True)
        except CollectionRefused:
            out.append(r)
    return out


def test_prohibited_sources_are_refused_before_any_network_request(db):
    prohibited = _prohibited(db)
    ids = {r["source_id"] for r in prohibited}
    # every restricted, blocked, licence-required or unreviewed source is in the refused set
    for r in db.execute("SELECT source_id, lifecycle_status FROM sources"):
        if r["lifecycle_status"] in ("RESTRICTED", "BLOCKED", "LICENCE REQUIRED", "NOT REVIEWED", "DISABLED"):
            assert r["source_id"] in ids, r
    assert {"psx", "psx_dps", "eia", "eia_press", "reuters", "x_platform", "sbp", "commerce"} <= ids
    for r in prohibited:
        net = FakeNet()
        client = client_for(net)
        with pytest.raises(CollectionRefused):
            collect(db, r["source_id"], client=client, dry_run=True)
        with pytest.raises(CollectionRefused):
            collect_document(db, r["source_id"], "https://example.org/doc.pdf", client=client, dry_run=True)
        with pytest.raises(CollectionRefused):
            fetch_pages(client, "https://example.org/list?page=1", source=r, dry_run=True,
                        next_url=lambda resp, n: None)
        assert net.calls == [], (r["source_id"], net.calls)  # not even robots.txt was requested


def test_restricted_source_with_feed_is_refused_even_if_robots_would_allow(db):
    # EIA has a feed URL and an adapter; refusal must come from policy, not from robots.txt
    net = FakeNet(robots=b"User-agent: *\nDisallow:\n")
    with pytest.raises(CollectionRefused, match="dry runs are not permitted"):
        collect(db, "eia", client=client_for(net), dry_run=True)
    assert net.calls == []


@pytest.mark.parametrize("field,value", [("access_status", "restricted"),
                                         ("terms_status", "prohibits_automation"),
                                         ("licensing_status", "licence_required"),
                                         ("access_method", "not_permitted")])
def test_any_single_prohibition_blocks_a_dry_run(field, value):
    src = dict(REVIEWED_SOURCE, **{field: value})
    with pytest.raises(CollectionRefused, match="may not be fetched"):
        engine.authorise(src, dry_run=True)
    engine.authorise(REVIEWED_SOURCE, dry_run=True)  # baseline allowed
    with pytest.raises(CollectionRefused, match="only ACTIVE"):
        engine.authorise(REVIEWED_SOURCE, dry_run=False)


def test_dry_run_writes_nothing(db):
    before = {t: count(db, t) for t in ("source_items", "collector_runs", "collector_checkpoints")}
    url = db.execute("SELECT feed_url FROM sources WHERE source_id='dawn'")[0]["feed_url"]
    r = collect(db, "dawn", client=client_for(FakeNet({url: [(200, {}, RSS)]})), dry_run=True)
    assert r.status == "dry_run" and r.fetched == 4 and len(r.entries) == 4
    assert {t: count(db, t) for t in before} == before


def test_kill_switch_stops_collection(db, monkeypatch):
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "true")
    with pytest.raises(CollectionRefused, match="KILL_SWITCH"):
        collect(db, "dawn", client=client_for(FakeNet()), dry_run=True)


def test_active_requires_approved_terms_in_database(db):
    with pytest.raises(DatabaseError, match="ACTIVE requires"):
        db.execute("UPDATE sources SET lifecycle_status='ACTIVE' WHERE source_id='thenews'")
    with pytest.raises(DatabaseError):
        db.execute("UPDATE sources SET enabled=1, lifecycle_status='ACTIVE', terms_status='approved' "
                   "WHERE source_id='psx'")  # access still restricted


OWNER_APPROVED_2026_11_08 = {"dawn", "dawn_pakistan", "dawn_world", "brecorder", "brecorder_markets",
                             "brecorder_pakistan", "tribune", "tribune_pakistan", "tribune_world", "pbs",
                             "scs_chart"}


def test_only_owner_approved_sources_are_active_or_enabled(db):
    rows = db.execute("SELECT * FROM sources WHERE enabled=1 OR lifecycle_status='ACTIVE'")
    assert {r["source_id"] for r in rows} == OWNER_APPROVED_2026_11_08
    for r in rows:
        assert (r["lifecycle_status"], r["enabled"], r["terms_status"], r["access_status"]) == (
            "ACTIVE", 1, "approved", "verified_permitted")
        assert "OWNER DECISION 2026-11-08" in r["review_notes"]
        assert r["retention_mode"] == "metadata_only"


# ---------------------------------------------------------------- engine: persistence
def test_collection_persists_items_with_provenance_and_audit(db):
    sid = make_active(db)
    hdrs = {"etag": '"v1"', "last-modified": "Sat, 07 Nov 2026 16:00:00 GMT"}
    net = FakeNet({FEED_URL: [(200, hdrs, RSS)]})
    r = collect(db, sid, client=client_for(net))
    assert (r.status, r.fetched, r.new, r.failed) == ("succeeded", 4, 4, 0)
    items = db.execute("SELECT * FROM source_items WHERE source_id=? ORDER BY source_item_id", (sid,))
    first = items[0]
    assert first["canonical_url"] == "https://news.example.com/story/1"
    assert first["original_url"] == "https://news.example.com/story/1/?utm_source=rss"
    assert first["retrieval_method"] == "rss" and first["http_status"] == 200
    assert first["collection_run_id"] == r.run_id
    assert first["published_at_raw"] == "Sat, 07 Nov 2026 20:26:16 +0500"
    assert first["permitted_excerpt"] is None  # metadata-only retention
    assert items[3]["published_at_utc"] is None and items[3]["publication_time_status"] == "unavailable"
    assert items[3]["collected_at_utc"] != items[3]["published_at_utc"]
    run = db.execute("SELECT * FROM collector_runs WHERE run_id=?", (r.run_id,))[0]
    assert run["status"] == "succeeded" and run["items_accepted"] == 4 and run["finished_at_utc"]
    cp = db.execute("SELECT * FROM collector_checkpoints WHERE source_id=?", (sid,))[0]
    assert cp["etag"] == '"v1"' and cp["last_seen_published_utc"] == "2026-11-07T15:26:16Z"
    src = db.execute("SELECT last_success_at_utc, consecutive_failures, last_content_at_utc "
                     "FROM sources WHERE source_id=?", (sid,))[0]
    assert src["last_success_at_utc"] and src["consecutive_failures"] == 0


def test_incremental_conditional_request_uses_checkpoint(db):
    sid = make_active(db)
    net = FakeNet({FEED_URL: [(200, {"etag": '"v1"'}, RSS), (304, {}, b"")]})
    c = client_for(net)
    collect(db, sid, client=c)
    r2 = collect(db, sid, client=c)
    assert r2.not_modified and r2.new == 0
    feed_calls = [h for u, h in net.calls if u == FEED_URL]
    assert feed_calls[1]["If-None-Match"] == '"v1"'


def test_rerun_with_same_content_is_idempotent(db):
    sid = make_active(db)
    net = FakeNet({FEED_URL: [(200, {}, RSS)]})
    collect(db, sid, client=client_for(net))
    n = count(db, "source_items")
    r2 = collect(db, sid, client=client_for(net))
    assert r2.unchanged == 4 and r2.new == 0 and count(db, "source_items") == n


def test_changed_article_becomes_new_version(db):
    sid = make_active(db)
    collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})))
    changed = RSS.replace(b"Synthetic headline one &amp; more", b"Synthetic headline one (corrected)")
    r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, changed)]})))
    assert r.new_versions == 1 and r.unchanged == 3
    item = db.execute("SELECT source_item_id, title FROM source_items WHERE canonical_url = "
                      "'https://news.example.com/story/1'")[0]
    assert item["title"] == "Synthetic headline one & more"  # original preserved
    vers = db.execute("SELECT version_no, title FROM source_item_versions WHERE source_item_id=? "
                      "ORDER BY version_no", (item["source_item_id"],))
    assert [v["version_no"] for v in vers] == [1, 2]
    assert vers[1]["title"] == "Synthetic headline one (corrected)"


def test_same_content_at_different_url_is_flagged(db):
    a = make_active(db, "feed_a", "https://a.example.com/feed")
    b = make_active(db, "feed_b", "https://b.example.com/feed")
    collect(db, a, client=client_for(FakeNet({"https://a.example.com/feed": [(200, {}, RSS)]})))
    # same story re-published at a different address by another outlet
    copy = RSS.replace(b"https://news.example.com/story/2</link>", b"https://mirror.example.net/s/2</link>")
    collect(db, a, client=client_for(FakeNet({"https://a.example.com/feed": [(200, {}, RSS)]})))
    collect(db, b, client=client_for(FakeNet({"https://b.example.com/feed": [(200, {}, RSS)]})))
    row = db.execute("SELECT duplicate_of_item_id FROM source_items WHERE source_id='feed_b' "
                     "AND canonical_url='https://news.example.com/story/2'")[0]
    assert row["duplicate_of_item_id"] is not None
    assert copy  # fixture variant constructed


def test_partial_failure_is_reported(db):
    sid = make_active(db)
    bad = RSS.replace(b"<link>https://news.example.com/story/4</link>", b"")
    r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, bad)]})))
    assert r.status == "partial" and r.failed == 1 and r.new == 3
    run = db.execute("SELECT status, items_failed, errors FROM collector_runs WHERE run_id=?", (r.run_id,))[0]
    assert run["status"] == "partial" and run["items_failed"] == 1 and "neither a link" in run["errors"]


def test_source_failure_is_visible_in_health(db):
    sid = make_active(db)
    for _ in range(2):
        r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [_http_error(500)]}), max_attempts=1))
        assert r.status == "failed"
    h = db.execute("SELECT * FROM source_health WHERE source_id=?", (sid,))[0]
    assert h["consecutive_failures"] == 2 and h["runs_failed"] == 2
    assert h["last_error"].startswith("FetchError")
    collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})))
    h = db.execute("SELECT consecutive_failures, failure_count FROM source_health "
                   "WHERE source_id=?", (sid,))[0]
    assert h["consecutive_failures"] == 0 and h["failure_count"] == 2


def test_malformed_feed_fails_cleanly(db):
    sid = make_active(db)
    r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, b"<rss><broken")]})))
    assert r.status == "failed" and "ParseError" in r.errors[0]
    assert count(db, "source_items") == 52  # only the Phase 1 seed items


def test_usage_budget_stops_run_early(db, monkeypatch):
    sid = make_active(db)
    calls = {"n": 0}
    real = engine.record_source_item

    def limited(*a, **kw):
        calls["n"] += 1
        if calls["n"] > 2:
            raise DatabaseBudgetError("per-run database budget exhausted")
        return real(*a, **kw)

    monkeypatch.setattr(engine, "record_source_item", limited)
    r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})))
    assert r.new == 2 and r.status == "partial" and "budget" in r.errors[-1]


def test_backfill_window_filters_by_publication_time(db):
    sid = make_active(db)
    r = collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})),
                since_utc="2026-11-07T10:00:00Z")
    assert r.new == 2  # 15:26Z and the undated item (undated items are kept, not guessed)


def test_excerpt_only_when_retention_permits(db):
    sid = make_active(db, retention="excerpt")
    collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})))
    row = db.execute("SELECT permitted_excerpt FROM source_items WHERE source_id=? "
                     "AND canonical_url='https://news.example.com/story/1'", (sid,))[0]
    assert row["permitted_excerpt"] == "Synthetic summary one ."


def test_provenance_fields_are_immutable(db):
    sid = make_active(db)
    collect(db, sid, client=client_for(FakeNet({FEED_URL: [(200, {}, RSS)]})))
    with pytest.raises(DatabaseError, match="immutable"):
        db.execute("UPDATE source_items SET original_url='https://evil.example/' WHERE source_id=?", (sid,))


def test_document_versions(db):
    sid = make_active(db)
    url = "https://official.example.org/notification.pdf"
    pdf = {"content-type": "application/pdf"}
    r1 = collect_document(db, sid, url, client=client_for(FakeNet({url: [(200, pdf, b"%PDF-1.4 v1")]})))
    r2 = collect_document(db, sid, url, client=client_for(FakeNet({url: [(200, pdf, b"%PDF-1.4 v2")]})))
    assert (r1.new, r2.new_versions) == (1, 1)
    row = db.execute("SELECT document_type, retrieval_method, source_metadata_json FROM source_items "
                     "WHERE canonical_url=?", (url,))[0]
    assert row["document_type"] == "pdf" and json.loads(row["source_metadata_json"])["is_pdf"] is True


def test_scheduler_respects_frequency(db):
    sid = make_active(db)
    assert sid in due_sources(db, "2026-11-07T12:00:00Z")
    db.execute("UPDATE sources SET last_attempt_at_utc='2026-11-07T11:30:00Z' WHERE source_id=?", (sid,))
    assert sid not in due_sources(db, "2026-11-07T12:00:00Z")  # 60-minute interval not elapsed
    assert sid in due_sources(db, "2026-11-07T12:31:00Z")
    # the market adapter is scheduled separately (collectors/market_ohlcv.py)
    assert "scs_chart" not in due_sources(db, "2026-11-07T12:31:00Z")


# ---------------------------------------------------------------- registry
def test_registry_keeps_all_phase1_sources_and_adds_universe(db):
    ids = {r["source_id"] for r in db.execute("SELECT source_id FROM sources")}
    phase1 = {"psx_dps", "psx", "sbp", "secp", "fbr", "ogra", "nepra", "mof", "ecc_cabinet", "pbs", "imf",
              "dawn", "brecorder", "profit", "mettis", "nukta", "investify", "scstrade", "reuters", "mufap",
              "x_platform", "youtube_platform"}
    assert phase1 <= ids
    assert {"commerce", "tribune", "thenews", "eia", "worldbank", "adb", "opec", "centcom"} <= ids


def test_watchlist_includes_new_accounts_exactly(db):
    rows = {r["handle"]: r for r in db.execute("SELECT * FROM media_accounts WHERE platform='x'")}
    for h in ("KhaqanNajeeb", "iabdullah278", "4xpakistan", "MarioNawfal", "ARNOfficiall"):
        assert rows[h]["supplied_url"] == f"https://x.com/{h}"
        assert rows[h]["monitoring_status"] == "disabled"
    pending = db.execute("SELECT display_name FROM media_accounts WHERE handle IS NULL ORDER BY display_name")
    assert [p["display_name"] for p in pending] == ["Donald Trump", "Reuters"]
    assert db.execute("SELECT COUNT(*) n FROM media_accounts WHERE platform='youtube'")[0]["n"] == 7


def test_restricted_sources_cannot_retain_content(db):
    for sid in ("psx", "psx_dps", "eia"):
        r = db.execute("SELECT lifecycle_status, enabled FROM sources WHERE source_id=?", (sid,))[0]
        assert r["lifecycle_status"] == "RESTRICTED" and r["enabled"] == 0


def test_source_register_document_is_in_sync():
    from scripts import build_source_register

    assert build_source_register.main(["x", "--check"]) == 0


# ---------------------------------------------------------------- registry review findings (F2-F4)
def test_registry_records_provider_findings_without_activation(db):
    rows = {r["source_id"]: r for r in db.execute("SELECT * FROM sources")}
    assert rows["investify"]["lifecycle_status"] == "RESTRICTED"
    assert rows["investify"]["terms_status"] == "prohibits_automation"
    assert rows["scstrade"]["lifecycle_status"] == "REVIEWED"
    assert "written clarification" in rows["scstrade"]["review_notes"]
    assert rows["mettis"]["licensing_status"] == "licence_required"
    expected = (("pucars", "REVIEWED"), ("capitalstake", "LICENCE REQUIRED"), ("sarmaaya", "RESTRICTED"))
    for sid, life in expected:
        assert rows[sid]["lifecycle_status"] == life and rows[sid]["enabled"] == 0
        assert rows[sid]["feed_url"] is None and rows[sid]["adapter"] is None
    never_active = ("investify", "scstrade", "mettis", "pucars", "capitalstake", "sarmaaya",
                    "psx", "psx_dps", "sbp")
    for sid in never_active:
        assert rows[sid]["lifecycle_status"] != "ACTIVE" and rows[sid]["enabled"] == 0, sid
    assert "reCAPTCHA" in rows["psx"]["review_notes"]


def test_stale_feed_is_shown_as_stale_not_as_working(db):
    h = db.execute("SELECT * FROM source_health WHERE source_id='thenews'")[0]
    assert h["lifecycle_status"] == "IMPLEMENTED" and h["freshness_status"] == "stale"
    assert h["last_test_result"] == "passed" and h["newest_item_at_utc"].startswith("2026-05")
    dawn = db.execute("SELECT freshness_status FROM sources WHERE source_id='dawn'")[0]
    assert dawn["freshness_status"] == "fresh"


def test_validation_refuses_tested_status_for_a_stale_feed():
    from database.validation import validate_source_registry
    src = {"source_id": "x1", "name": "X", "lifecycle_status": "TESTED", "adapter": "rss",
           "feed_url": "https://x.example/feed", "reviewed_at_utc": "2026-11-07T00:00:00Z",
           "review_notes": "n", "last_test_result": "passed", "last_test_at_utc": "2026-11-07T00:00:00Z",
           "freshness_status": "stale"}
    assert any("fresh feed" in e for e in validate_source_registry({"sources": [src]}))
    assert not validate_source_registry({"sources": [dict(src, freshness_status="fresh")]})
