"""News collector: parsing, robots.txt, ceilings and idempotence, all offline with a fake fetch."""

from __future__ import annotations

from datetime import UTC, datetime

from database.connection import SQLiteDatabase
from engines import news_collector as nc

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)

RSS = """<rss><channel>
<item><title><![CDATA[SBP holds rate &amp; outlook]]></title><link>https://tribune.com.pk/story/1/sbp</link>
<pubDate>Mon, 16 Nov 26 08:14:16 +0500</pubDate><category>Business</category>
<description><![CDATA[<p>The central bank kept the <b>policy rate</b> unchanged.</p>]]></description></item>
<item><title>No date here</title><link>https://tribune.com.pk/story/2/x</link></item>
</channel></rss>"""

SITEMAP_INDEX = """<sitemapindex>
<sitemap><loc>https://mettisglobal.news/post-sitemap.xml</loc><lastmod>2026-11-16T10:00:00+00:00</lastmod></sitemap>
<sitemap><loc>https://mettisglobal.news/post-sitemap9.xml</loc><lastmod>2017-04-30T10:00:00+00:00</lastmod></sitemap>
</sitemapindex>"""

POST_SITEMAP = """<urlset>
<url><loc>https://mettisglobal.news/author/MG%20News</loc><lastmod>2026-11-16T09:00:00+00:00</lastmod></url>
<url><loc>https://mettisglobal.news/new-story-1</loc><lastmod>2026-11-16T09:00:00+00:00</lastmod></url>
<url><loc>https://mettisglobal.news/old-story-2</loc><lastmod>2026-11-15T09:00:00+00:00</lastmod></url>
<url><loc>https://mettisglobal.news/blocked/story-3</loc><lastmod>2026-11-14T09:00:00+00:00</lastmod></url>
</urlset>"""


LATEST = """<html><body>
<a href="https://mettisglobal.news/Fresh-story-65036">a</a><a href="https://mettisglobal.news/Fresh-story-65036">dup</a>
<a href="https://mettisglobal.news/Another-fresh-65040">b</a><a href="https://mettisglobal.news/latest">nav</a>
</body></html>"""


def article(title: str, published: str) -> str:
    return ('<html><head><meta property="og:description" content="A short &amp; useful summary." />'
            '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"NewsArticle",'
            f'"headline":"{title}","datePublished":"{published}"}}]}}</script></head><body>x</body></html>')


class Site:
    """A fake network: path -> body, with a log of every URL asked for."""

    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self.pages, self.calls = pages, []

    def __call__(self, url: str) -> tuple[int | None, bytes]:
        self.calls.append(url)
        status, body = self.pages.get(url, (404, ""))
        return status, body.encode()


def pages(**extra: tuple[int, str]) -> dict[str, tuple[int, str]]:
    base = {
        "https://mettisglobal.news/robots.txt": (200, "User-agent: *\nAllow: /\n"),
        "https://tribune.com.pk/robots.txt": (200, "User-agent: *\n"),
        "https://mettisglobal.news/latest": (200, LATEST),
        "https://mettisglobal.news/Fresh-story-65036": (200, article("Fresh one", "2026-11-16T08:00:00Z")),
        "https://mettisglobal.news/Another-fresh-65040": (200, article("Fresh two", "2026-11-16T09:30:00Z")),
        "https://mettisglobal.news/sitemap_index.xml": (200, SITEMAP_INDEX),
        "https://mettisglobal.news/post-sitemap.xml": (200, POST_SITEMAP),
        "https://mettisglobal.news/new-story-1": (200, article("New story", "2026-11-16T09:00:00Z")),
        "https://mettisglobal.news/old-story-2": (200, article("Old story", "2024-01-01T09:00:00Z")),
        "https://tribune.com.pk/feed/business": (200, RSS),
    }
    base.update(extra)
    return base


def fresh_db() -> SQLiteDatabase:
    db = SQLiteDatabase()
    db.execute("CREATE TABLE fetch_log (ts_utc TEXT, event TEXT, detail TEXT)")
    return db


def count(db: SQLiteDatabase, table: str) -> int:
    return db.execute(f"SELECT count(*) AS n FROM {table}")[0]["n"]  # noqa: S608 - test helper, fixed names


def test_clean_text_and_dates():
    assert nc.clean_text("<p>Rates &amp; <b>prices</b>  rose</p>") == "Rates & prices rose"
    assert nc.clean_text("word " * 100, 20) == "word word word word"
    assert nc.to_utc_iso("Mon, 16 Nov 26 08:14:16 +0500") == "2026-11-16T03:14:16Z"
    assert nc.to_utc_iso("2025-12-01T16:24:59Z") == "2025-12-01T16:24:59Z"
    assert nc.to_utc_iso("not a date") is None


def test_parse_rss_keeps_dated_items_only():
    items = nc.parse_rss(RSS, "tribune_business")
    assert len(items) == 1
    assert items[0].title == "SBP holds rate & outlook" and items[0].section == "Business"
    assert items[0].snippet == "The central bank kept the policy rate unchanged."


def test_parse_mettis_article_and_missing_metadata():
    item = nc.parse_mettis_article(article("PMI back to growth", "2025-12-01T16:24:59Z"), "https://m/x")
    assert item and item.title == "PMI back to growth" and item.snippet == "A short & useful summary."
    assert nc.parse_mettis_article("<html><body>nothing</body></html>", "https://m/y") is None


def test_sitemap_and_article_filter():
    entries = nc.parse_sitemap(POST_SITEMAP)
    assert len(entries) == 4
    kept = [u for u, _ in entries if nc.mettis_is_article(u)]
    assert kept == ["https://mettisglobal.news/new-story-1", "https://mettisglobal.news/old-story-2"]


def test_robots_rules_wildcards_longest_match_and_default():
    text = "User-agent: *\nDisallow: /newspaper/*/20*\nDisallow: /archive/\nAllow: /archive/open\n"
    assert not nc.robots_allows(text, "https://x.com/newspaper/business/2025-01-01")
    assert not nc.robots_allows(text, "https://x.com/archive/a")
    assert nc.robots_allows(text, "https://x.com/archive/open")  # longer Allow wins
    assert nc.robots_allows(text, "https://x.com/business")
    assert nc.robots_allows("", "https://x.com/anything")
    own = "User-agent: psx-ni-news\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert not nc.robots_allows(own, "https://x.com/a")  # a rule naming this crawler beats '*'


def test_run_stores_new_items_skips_old_and_never_fetches_disallowed():
    db, site = fresh_db(), Site(pages(**{
        "https://mettisglobal.news/robots.txt": (200, "User-agent: *\nDisallow: /blocked/\n"),
        "https://mettisglobal.news/blocked/story-3": (200, article("Blocked", "2026-11-14T09:00:00Z"))}))
    results = nc.run(db, site, NOW, sleep=lambda _s: None)
    assert results["mettis"].stored == 3 and results["tribune_business"].stored == 1
    titles = {r["title"] for r in db.execute("SELECT title FROM news_item")}
    assert titles == {"New story", "Fresh one", "Fresh two", "SBP holds rate & outlook"}
    assert "https://mettisglobal.news/blocked/story-3" not in site.calls  # robots.txt disallows it
    assert "https://mettisglobal.news/post-sitemap9.xml" not in site.calls  # outside the one-year window
    skipped = db.execute("SELECT key FROM news_progress WHERE key LIKE 'skip:%'")
    assert [r["key"] for r in skipped] == ["skip:https://mettisglobal.news/old-story-2"]


def test_second_run_is_idempotent_and_does_not_refetch_articles():
    db, site = fresh_db(), Site(pages())
    nc.run(db, site, NOW, sleep=lambda _s: None)
    first_total = count(db, "news_item")
    site.calls.clear()
    again = nc.run(db, site, NOW, sleep=lambda _s: None)
    assert count(db, "news_item") == first_total
    assert again["mettis"].stored == 0 and again["tribune_business"].stored == 0
    assert not any("story-1" in c or "story-2" in c for c in site.calls if "tribune" not in c)
    assert not any(c.endswith("robots.txt") for c in site.calls)  # stored robots.txt is fresh


def test_daily_ceiling_stops_requests(monkeypatch):
    monkeypatch.setitem(nc.DAILY_CEILING, "mettis", 3)
    db, site = fresh_db(), Site(pages())
    result = nc.run(db, site, NOW, sleep=lambda _s: None)["mettis"]
    assert result.requests == 3  # robots.txt + /latest + sitemap index, then the budget is spent
    site.calls.clear()
    again = nc.run(db, site, NOW, sleep=lambda _s: None)["mettis"]
    assert again.notes == ["daily ceiling reached"] and again.requests == 0
    assert not [c for c in site.calls if "mettisglobal" in c]


def test_unreadable_robots_fails_closed():
    db = fresh_db()
    site = Site({"https://mettisglobal.news/robots.txt": (500, ""),
                 "https://tribune.com.pk/robots.txt": (500, "")})
    results = nc.run(db, site, NOW, sleep=lambda _s: None)
    assert all(r.stored == 0 for r in results.values())
    assert all(r.notes == ["robots.txt unreadable: nothing fetched"] for r in results.values())
    assert site.calls == ["https://mettisglobal.news/robots.txt", "https://tribune.com.pk/robots.txt"]


def test_requests_are_spaced_and_log_rows_written():
    db, site, waits = fresh_db(), Site(pages()), []
    nc.run(db, site, NOW, sleep=waits.append)
    assert waits and all(w == nc.GAP_SECONDS for w in waits)
    events = {r["event"] for r in db.execute("SELECT event FROM fetch_log")}
    assert events == {"news_stored"}


def test_listing_parser_orders_newest_first_and_ignores_navigation():
    urls = nc.parse_mettis_listing(LATEST)
    assert urls == ["https://mettisglobal.news/Another-fresh-65040", "https://mettisglobal.news/Fresh-story-65036"]


def test_new_articles_come_first_and_survive_an_unreadable_sitemap_index():
    db = fresh_db()
    site = Site(pages(**{"https://mettisglobal.news/sitemap_index.xml": (500, "")}))
    result = nc.run(db, site, NOW, sleep=lambda _s: None, per_run=2)["mettis"]
    assert "sitemap index not read" in result.notes and result.stored == 2
    assert {r["title"] for r in db.execute("SELECT title FROM news_item WHERE source = 'mettis'")} == {
        "Fresh one", "Fresh two"}
