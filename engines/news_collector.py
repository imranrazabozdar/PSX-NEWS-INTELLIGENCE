"""News collector: headlines from Mettis and Express Tribune (business) into psx-library `news_item`.

Only sources whose robots.txt allows it. Every request is checked against the site's stored robots.txt first
and a disallowed URL is never fetched; if robots.txt cannot be read and no copy is stored, nothing is fetched
(fail closed). Requests are spaced (GAP_SECONDS) and capped per run and per day. Only metadata is stored:
headline, publication date, link and a short snippet, never the article body.

Mettis: a one-year backfill plus new articles, discovered through its sitemaps, a few articles per run.
Express Tribune business: the site's business RSS feed, which carries title, date and description.
Runs are meant to be started every 30 minutes by the external trigger (see docs/ops/NEWS_COLLECTOR.md).
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from engines import autonomous_tick as tick
from engines import library_db

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0008_news_item.sql"
CUTOFF_DAYS = 365
PER_RUN_ARTICLES = 25
GAP_SECONDS = 8.0
ROBOTS_MAX_AGE = timedelta(hours=24)
FEED_MIN_INTERVAL = timedelta(minutes=55)  # feeds and listings that change slowly are read hourly
DAILY_CEILING = {"mettis": 300, "tribune_business": 160, "dawn_business": 60, "brecorder": 120, "profit": 200}
# The back-fill may never use the requests the live reading needs for the rest of the day: the Tribune feed
# is read every 30 minutes (48 a day) and Profit's front page every hour plus its new articles. Without this
# the back-fill spent the whole day's ceiling in the morning and the live feed went dark until the next UTC
# day (seen on 17 Nov).
LIVE_RESERVE = {"tribune_business": 60, "profit": 60}
MAX_BODY = 15_000_000  # Tribune's post sitemap is about 5.6 MB
BACKFILL_DAYS = 30  # owner-approved one-month back-fill (16 Nov 2026) for Profit and Tribune business
SNIPPET_CHARS = 300

METTIS = "https://mettisglobal.news"
TRIBUNE = "https://tribune.com.pk"
DAWN = "https://www.dawn.com"
BRECORDER = "https://www.brecorder.com"
PROFIT = "https://profit.pakistantoday.com.pk"
# kind "feed": RSS feeds that carry title, date and description (no article page is fetched).
# kind "mettis" / "profit": new articles found through a listing page, each article page read once.
SOURCES = {
    "mettis": {"kind": "mettis", "base": METTIS, "index": METTIS + "/sitemap_index.xml",
               "latest": METTIS + "/latest"},
    "tribune_business": {"kind": "feed", "base": TRIBUNE, "feeds": [TRIBUNE + "/feed/business"],
                         "min_interval": None, "sitemap": TRIBUNE + "/sitemap.xml", "business_only": True},
    "dawn_business": {"kind": "feed", "base": DAWN, "feeds": [DAWN + "/feeds/business"],
                      "min_interval": FEED_MIN_INTERVAL},
    "brecorder": {"kind": "feed", "base": BRECORDER,
                  "feeds": [BRECORDER + "/feeds/latest-news", BRECORDER + "/feeds/business-finance"],
                  "min_interval": FEED_MIN_INTERVAL},
    "profit": {"kind": "profit", "base": PROFIT, "latest": PROFIT + "/", "min_interval": FEED_MIN_INTERVAL,
               "sitemap": PROFIT + "/sitemap.xml"},
}
_CREATE = re.compile(
    r"^(?:CREATE TABLE IF NOT EXISTS [a-z_]+ \("
    r"|CREATE INDEX IF NOT EXISTS idx_news_item_published ON news_item \(published_at\)$)",
    re.IGNORECASE,
)

Fetch = Callable[[str], tuple["int | None", bytes]]


@dataclass(frozen=True)
class Item:
    source: str
    url: str
    title: str
    published_at: str  # UTC, 'YYYY-MM-DDTHH:MM:SSZ'
    section: str | None
    snippet: str | None


@dataclass
class Result:
    stored: int = 0
    requests: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- pure parsing

def clean_text(value: str | None, limit: int = SNIPPET_CHARS) -> str:
    """Plain text: tags removed, entities decoded, whitespace collapsed, cut at a word boundary."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(",;:- ")


PKT = timezone(timedelta(hours=5))  # Pakistan has no daylight saving time
# Outlets whose article dates carry the Pakistan wall-clock time but are labelled UTC (or carry no zone).
# Found in the seven-day council evaluation (19 Nov 2026): every Mettis item was dated about five hours in
# the future. The wall-clock part of their date is read as Pakistan time. Forward-only: rows already stored
# are NOT rewritten (a historical correction needs a separate owner approval).
WALL_CLOCK_IS_PKT = frozenset({"mettis"})


def to_utc_iso(text: str | None, *, wall_clock: timezone | None = None) -> str | None:
    """An ISO-8601 or RFC-822 date as UTC 'YYYY-MM-DDTHH:MM:SSZ'. A date with no zone is read as UTC, unless
    `wall_clock` says the clock time in the text is in that zone whatever label it carries."""
    if not text:
        return None
    raw = text.strip()
    when: datetime | None = None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if wall_clock is not None:
        when = when.replace(tzinfo=wall_clock)  # keep the clock reading, replace the (wrong or missing) label
    elif when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_TRACKING = re.compile(r"^(?:v|utm_\w+|fbclid|gclid|ref|source)$", re.I)


def canonical_url(url: str) -> str:
    """The article URL without tracking parameters (the council evaluation found Business Recorder articles
    stored several times as '...?v=<token>'). Other query parameters are kept."""
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), ""))


def parse_sitemap(xml: str) -> list[tuple[str, str | None]]:
    """(loc, lastmod) for every <url> or <sitemap> entry."""
    out = []
    for block in re.findall(r"<(?:url|sitemap)>(.*?)</(?:url|sitemap)>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            out.append((html.unescape(loc.group(1)), mod.group(1) if mod else None))
    return out


def mettis_is_article(url: str) -> bool:
    path = urlsplit(url).path.strip("/")
    if not path or "/" in path:
        return False
    return not path.startswith(("author", "category", "tag", "page", "wp-"))


def parse_mettis_listing(page: str) -> list[str]:
    """Article links on a Mettis listing page ('/latest'): newest first (higher trailing number = newer)."""
    found = {m for m in re.findall(r'href="(https://mettisglobal\.news/[A-Za-z0-9%._~-]+-\d{4,7})"', page)}
    return sorted(found, key=lambda u: int(u.rsplit("-", 1)[1]), reverse=True)


def _tag(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    if not m:
        return None
    value = m.group(1).strip()
    cdata = re.fullmatch(r"<!\[CDATA\[(.*?)\]\]>", value, re.S)
    return cdata.group(1) if cdata else value


def parse_rss(xml: str, source: str) -> list[Item]:
    items = []
    for block in re.findall(r"<item[\s>](.*?)</item>", xml, re.S):
        title, link = _tag(block, "title"), _tag(block, "link")
        when = to_utc_iso(html.unescape(_tag(block, "pubDate") or ""))
        if not (title and link and when):
            continue
        section = _tag(block, "category")
        items.append(Item(source, html.unescape(link).strip(), clean_text(title, 400), when,
                          clean_text(section, 80) or None,
                          clean_text(_tag(block, "description")) or None))
    return items


def _ld_nodes(page: str) -> list[dict]:
    nodes: list[dict] = []
    for raw in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        for node in stack:
            if isinstance(node, dict):
                nodes.extend(node["@graph"] if isinstance(node.get("@graph"), list) else [node])
    return [n for n in nodes if isinstance(n, dict)]


def _meta(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in re.findall(r"<meta\s[^>]*>", page):
        key = re.search(r'(?:property|name)=["\']([^"\']+)["\']', tag)
        val = re.search(r'content=["\'](.*?)["\']\s*/?>', tag, re.S)
        if key and val:
            out.setdefault(key.group(1), val.group(1))
    return out


def parse_article(page: str, url: str, source: str) -> Item | None:
    """Headline, date and snippet from the page's NewsArticle metadata; None if either is missing."""
    node = next((n for n in _ld_nodes(page)
                 if n.get("@type") in ("NewsArticle", "Article", "BlogPosting")), None)
    meta = _meta(page)
    title = (node or {}).get("headline") or meta.get("og:title")
    zone = PKT if source in WALL_CLOCK_IS_PKT else None
    raw_date = (node or {}).get("datePublished") or meta.get("article:published_time")
    when = to_utc_iso(raw_date, wall_clock=zone)
    if not title or not when:
        return None
    section = (node or {}).get("articleSection") or meta.get("article:section")
    snippet = meta.get("og:description") or (node or {}).get("description") or meta.get("description")
    return Item(source, url, clean_text(str(title), 400), when,
                clean_text(section, 80) or None if isinstance(section, str) else None,
                clean_text(snippet) or None if isinstance(snippet, str) else None)


def parse_mettis_article(page: str, url: str) -> Item | None:
    return parse_article(page, url, "mettis")


def parse_profit_listing(page: str) -> list[str]:
    """Dated article links (/YYYY/MM/DD/slug), relative or absolute, as absolute URLs in page order."""
    pattern = r'href=["\'](?:https://profit\.pakistantoday\.com\.pk)?(/\d{4}/\d{2}/\d{2}/[A-Za-z0-9%._~-]+)/?["\']'
    seen: dict[str, None] = {}
    for path in re.findall(pattern, page):
        seen.setdefault(PROFIT + path, None)
    return list(seen)


# Tribune's sitemap has no section, so a story is only fetched when its slug looks business-related;
# the page's own section then decides whether it is kept.
BUSINESS_SLUG = re.compile(
    r"psx|kse|stock|share|bank|sbp|rupee|dollar|inflation|econom|budget|tax|fbr|imf|gdp|oil|petrol|diesel|"
    r"gas|power|electric|cement|steel|fertili|sugar|textile|export|import|trade|profit|loss|dividend|earning|"
    r"revenue|price|market|invest|loan|debt|sukuk|bond|tariff|nepra|ogra|ecc|financ|business|compan|plant|"
    r"refiner|auto|sales|growth|reserve|remittance|privati|airline|pia|telecom|crypto|gold|wheat|cotton|rice|"
    r"fund|insurance|ipo|merger|acquisition|currency|forex|tbill|treasury|cpi|mpc|monetary|wage|salary|pension",
    re.IGNORECASE)


def profit_url_day(url: str) -> str | None:
    m = re.match(r"https://profit\.pakistantoday\.com\.pk/(\d{4})/(\d{2})/(\d{2})/", url)
    return "-".join(m.groups()) if m else None


def tribune_slug_is_business(url: str) -> bool:
    m = re.match(r"https://tribune\.com\.pk/story/\d+/([A-Za-z0-9%._~-]+)$", url)
    return bool(m and BUSINESS_SLUG.search(m.group(1)))


# ---------------------------------------------------------------- robots.txt

def _robots_pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = re.escape(path[:-1] if anchored else path).replace(r"\*", ".*")
    return re.compile("^" + body + ("$" if anchored else ""))


def robots_allows(text: str, url: str, agent: str = "psx-ni-news") -> bool:
    """robots.txt rules for this agent (else '*'): the longest matching rule wins, Allow wins a tie.
    Supports '*' and '$'. No rules, or no match, means allowed."""
    parts = urlsplit(url)
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent:
                agents, rules = [], []
                groups.append((agents, rules))
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            rules.append((key, value))
            last_was_agent = False
    mine = [r for a, r in groups if any(x != "*" and x in agent.lower() for x in a)]
    chosen = mine or [r for a, r in groups if "*" in a]
    best_len, best_allow = -1, True
    for rule_list in chosen:
        for kind, value in rule_list:
            if value and _robots_pattern(value).match(path):
                allow = kind == "allow"
                if len(value) > best_len or (len(value) == best_len and allow):
                    best_len, best_allow = len(value), allow
    return best_allow


# ---------------------------------------------------------------- state in psx-library

class Store:
    def __init__(self, db: Any) -> None:
        self.db = db

    def ensure_tables(self) -> None:
        body = "\n".join(line.split("--", 1)[0] for line in SCHEMA.read_text(encoding="utf-8").splitlines())
        for stmt in (s.strip() for s in body.split(";") if s.strip()):
            if not _CREATE.match(stmt):
                raise ValueError(f"refused: only the news tables and index may be created: {stmt[:50]!r}")
            self.db.execute(stmt)

    def known_among(self, source: str, urls: Iterable[str]) -> set[str]:
        """Which of these URLs are already stored or skipped. Two primary-key lookups per 200 candidates: the
        rows read are the matches, not every article the source has ever had (that grew without limit)."""
        wanted = sorted(set(urls))
        known: set[str] = set()
        for i in range(0, len(wanted), 200):
            part = wanted[i : i + 200]
            marks = ", ".join("?" for _ in part)
            known |= {r["url"] for r in self.db.execute(
                f"SELECT url FROM news_item WHERE source = ? AND url IN ({marks})",  # noqa: S608
                (source, *part))}
            keys = ["skip:" + u for u in part]
            known |= {r["key"][5:] for r in self.db.execute(
                f"SELECT key FROM news_progress WHERE source = ? AND key IN ({marks})",  # noqa: S608
                (source, *keys))}
        return known

    def progress(self, source: str, key: str) -> tuple[str, str] | None:
        rows = self.db.execute("SELECT value, updated_utc FROM news_progress WHERE source = ? AND key = ?",
                               (source, key))
        return (rows[0]["value"] or "", rows[0]["updated_utc"]) if rows else None

    def set_progress(self, source: str, key: str, value: str, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO news_progress (source, key, value, updated_utc) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(source, key) DO UPDATE SET value = excluded.value, "
            "updated_utc = excluded.updated_utc",
            (source, key, value, _stamp(now)))

    def add_item(self, item: Item, now: datetime) -> None:
        item = replace(item, url=canonical_url(item.url))  # one article, one row, whatever it tracks
        self.db.execute(
            "INSERT OR IGNORE INTO news_item "
            "(source, url, title, published_at, section, snippet, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.source, item.url, item.title, item.published_at, item.section, item.snippet, _stamp(now)))

    def log(self, event: str, detail: str, now: datetime) -> None:
        self.db.execute("INSERT INTO fetch_log (ts_utc, event, detail) VALUES (?, ?, ?)",
                        (_stamp(now), event, detail[:300]))


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- one run

class _Session:
    """Requests for one source in one run: robots check first, spacing, a request budget, a count."""

    def __init__(self, name: str, store: Store, fetch: Fetch, now: datetime, sleep: Callable[[float], None],
                 budget: int) -> None:
        self.name, self.store, self.fetch, self.now, self.sleep = name, store, fetch, now, sleep
        self.budget, self.count, self.robots, self._last = budget, 0, None, False

    def load_robots(self) -> bool:
        stored = self.store.progress(self.name, "robots")
        fresh = False
        if stored and stored[1]:
            fresh = self.now - datetime.fromisoformat(stored[1].replace("Z", "+00:00")) < ROBOTS_MAX_AGE
        if stored and fresh:
            self.robots = stored[0]
            return True
        status, body = self._get(SOURCES[self.name]["base"] + "/robots.txt")
        if status == 200:
            self.robots = body.decode("utf-8", "replace")
        elif status == 404:
            self.robots = ""  # no robots.txt: nothing is disallowed
        elif stored:
            self.robots = stored[0]  # keep the old copy if the refresh failed
            return True
        else:
            return False  # fail closed
        self.store.set_progress(self.name, "robots", self.robots, self.now)
        return True

    def _get(self, url: str) -> tuple[int | None, bytes]:
        if self._last:
            self.sleep(GAP_SECONDS)
        self._last = True
        self.count += 1
        return self.fetch(url)

    def get(self, url: str, reserve: int = 0) -> tuple[int | None, bytes] | None:
        """None means not fetched: robots disallows the URL, or the request budget is spent."""
        if self.robots is None or not robots_allows(self.robots, url) or self.count >= self.budget - reserve:
            return None
        return self._get(url)


def _run_mettis(s: _Session, result: Result, cutoff: datetime, per_run: int) -> None:
    fresh: list[str] = []
    listing = s.get(SOURCES["mettis"]["latest"])
    if listing and listing[0] == 200:
        fresh = parse_mettis_listing(listing[1].decode("utf-8", "replace"))
    got = s.get(SOURCES["mettis"]["index"])
    cut_day = cutoff.strftime("%Y-%m-%d")
    maps: list[str] = []
    if got and got[0] == 200:
        maps = [loc for loc, mod in parse_sitemap(got[1].decode("utf-8", "replace"))
                if "post-sitemap" in loc and (mod or "9999")[:10] >= cut_day]
    else:
        result.notes.append("sitemap index not read")
    pending: list[tuple[str, str]] = []
    for loc in maps:
        page = s.get(loc)
        if not page or page[0] != 200:
            result.notes.append(f"sitemap not read: {loc.rsplit('/', 1)[-1]}")
            continue
        for url, mod in parse_sitemap(page[1].decode("utf-8", "replace")):
            if mettis_is_article(url) and (mod or "9999")[:10] >= cut_day:
                pending.append((mod or "", url))
    known = s.store.known_among("mettis", fresh + [url for _mod, url in pending])
    fresh = [u for u in fresh if u not in known]
    pending = [(mod, url) for mod, url in pending if url not in known]
    pending.sort(reverse=True)  # newest first
    queue = fresh + [url for _mod, url in pending if url not in fresh]  # the listing's new articles go first
    for url in queue[:per_run]:
        got = s.get(url)
        if got is None:
            break
        if got[0] != 200:
            result.notes.append(f"article {got[0]}")
            continue
        item = parse_mettis_article(got[1].decode("utf-8", "replace"), url)
        if item is None:
            s.store.set_progress("mettis", "skip:" + url, "unparsed", s.now)
        elif datetime.fromisoformat(item.published_at.replace("Z", "+00:00")) < cutoff:
            s.store.set_progress("mettis", "skip:" + url, "older than the window", s.now)
        else:
            s.store.add_item(item, s.now)
            result.stored += 1
    result.notes.append(f"{max(len(queue) - per_run, 0)} article(s) still pending")


def _run_feeds(s: _Session, result: Result, per_run: int = PER_RUN_ARTICLES) -> None:
    """RSS sources: each item carries title, date and description, so no article page is fetched."""
    items: list[Item] = []
    for feed in SOURCES[s.name]["feeds"]:
        got = s.get(feed)
        if not got or got[0] != 200:
            result.notes.append(f"feed not read: {feed.rsplit('/', 1)[-1]}")
            continue
        items += parse_rss(got[1].decode("utf-8", "replace"), s.name)
    known = s.store.known_among(s.name, [i.url for i in items])
    for item in items:
        if item.url not in known:
            known.add(item.url)  # the same article can appear in two feeds of one source
            s.store.add_item(item, s.now)
            result.stored += 1
    if SOURCES[s.name].get("sitemap"):  # owner-approved one-month back-fill (business stories only)
        cutoff = s.now - timedelta(days=BACKFILL_DAYS)
        back = _backfill_queue(s, result, cutoff)
        _read_articles(s, result, back, cutoff, per_run)


def _run_profit(s: _Session, result: Result, cutoff: datetime, per_run: int) -> None:
    """New Profit articles: the front page lists them, each article page is read once for its metadata."""
    listing = s.get(SOURCES["profit"]["latest"])
    if not listing or listing[0] != 200:
        result.notes.append("front page not read")
        return
    listed = parse_profit_listing(listing[1].decode("utf-8", "replace"))
    known = s.store.known_among("profit", listed)
    queue = [u for u in listed if u not in known]
    for url in queue[:per_run]:
        got = s.get(url)
        if got is None:
            break
        if got[0] != 200:
            result.notes.append(f"article {got[0]}")
            continue
        item = parse_article(got[1].decode("utf-8", "replace"), url, "profit")
        if item is None:
            s.store.set_progress("profit", "skip:" + url, "unparsed", s.now)
        elif datetime.fromisoformat(item.published_at.replace("Z", "+00:00")) < cutoff:
            s.store.set_progress("profit", "skip:" + url, "older than the window", s.now)
        else:
            s.store.add_item(item, s.now)
            result.stored += 1
    result.notes.append(f"{max(len(queue) - per_run, 0)} article(s) still pending")
    if len(queue) < per_run:  # the live articles come first; the back-fill uses what is left of the run
        back = _backfill_queue(s, result, s.now - timedelta(days=BACKFILL_DAYS))
        _read_articles(s, result, back, s.now - timedelta(days=BACKFILL_DAYS), per_run - len(queue))


def _backfill_queue(s: _Session, result: Result, cutoff: datetime) -> list[str]:
    """Back-fill candidates from the site's sitemaps, newest first; read at most once an hour."""
    name = s.name
    day = s.now.astimezone(UTC).strftime("%Y-%m-%d")
    done = s.store.progress(name, "backfill_done")
    if done and done[0] == day:
        return []
    cfg = SOURCES[name]
    cut_day = cutoff.strftime("%Y-%m-%d")
    keep = LIVE_RESERVE.get(name, 0)
    index = s.get(cfg["sitemap"], reserve=keep)
    if not index or index[0] != 200:
        result.notes.append("sitemap index not read")
        return []
    key = "sitemap-articles" if name == "profit" else "/posts-"
    files = [loc for loc, _mod in parse_sitemap(index[1].decode("utf-8", "replace")) if key in loc]
    queue: list[str] = []
    for loc in files:
        page = s.get(loc, reserve=keep)
        if not page or page[0] != 200:
            result.notes.append(f"sitemap not read: {loc.rsplit('/', 1)[-1]}")
            break
        in_window, reached_older = 0, False
        for url, mod in parse_sitemap(page[1].decode("utf-8", "replace")):
            day_of = profit_url_day(url) if name == "profit" else (mod or "")[:10]
            if not day_of:
                continue
            if day_of < cut_day:
                reached_older = True
                continue
            in_window += 1
            if name == "profit" or tribune_slug_is_business(url):
                queue.append(url)
        if not in_window or reached_older:
            break  # the window ends in this file (or it is all older); later files are older still
    known = s.store.known_among(name, queue)
    fresh = {u for u in queue if u not in known}
    queue = sorted(fresh, key=lambda u: (profit_url_day(u) or "", u), reverse=True)
    if not queue:
        s.store.set_progress(name, "backfill_done", day, s.now)
    return queue


def _read_articles(s: _Session, result: Result, urls: list[str], cutoff: datetime,
                   per_run: int) -> None:
    business_only = bool(SOURCES[s.name].get("business_only"))
    for url in urls[:per_run]:
        got = s.get(url, reserve=LIVE_RESERVE.get(s.name, 0))
        if got is None:
            break
        if got[0] != 200:
            result.notes.append(f"article {got[0]}")
            continue
        item = parse_article(got[1].decode("utf-8", "replace"), url, s.name)
        if item is None:
            s.store.set_progress(s.name, "skip:" + url, "unparsed", s.now)
        elif datetime.fromisoformat(item.published_at.replace("Z", "+00:00")) < cutoff:
            s.store.set_progress(s.name, "skip:" + url, "older than the window", s.now)
        elif business_only and "business" not in (item.section or "").lower() \
                and "econom" not in (item.section or "").lower():
            s.store.set_progress(s.name, "skip:" + url, "not business", s.now)
        else:
            s.store.add_item(item, s.now)
            result.stored += 1
    result.notes.append(f"{max(len(urls) - per_run, 0)} back-fill article(s) still pending")


def _due(store: Store, name: str, now: datetime) -> bool:
    gap = SOURCES[name].get("min_interval")
    last = store.progress(name, "last_run") if gap else None
    return not (last and last[0] and now - datetime.fromisoformat(last[0].replace("Z", "+00:00")) < gap)


def run(db: Any, fetch: Fetch, now: datetime, *, sleep: Callable[[float], None] = time.sleep,
        per_run: int = PER_RUN_ARTICLES) -> dict[str, Result]:
    store = Store(db)
    store.ensure_tables()
    cutoff = now - timedelta(days=CUTOFF_DAYS)
    day = now.astimezone(UTC).strftime("%Y-%m-%d")
    results: dict[str, Result] = {}
    for name in SOURCES:
        result = results[name] = Result()
        used_row = store.progress(name, f"day:{day}")
        used = int(used_row[0]) if used_row else 0
        budget = DAILY_CEILING[name] - used
        if budget <= 0:
            result.notes.append("daily ceiling reached")
            continue
        if not _due(store, name, now):
            result.notes.append("not due yet (read hourly)")
            continue
        session = _Session(name, store, fetch, now, sleep, budget)
        if not session.load_robots():
            result.notes.append("robots.txt unreadable: nothing fetched")
        else:
            kind = SOURCES[name]["kind"]
            if kind == "mettis":
                _run_mettis(session, result, cutoff, per_run)
            elif kind == "profit":
                _run_profit(session, result, cutoff, per_run)
            else:
                _run_feeds(session, result, per_run)
            if SOURCES[name].get("min_interval"):
                store.set_progress(name, "last_run", _stamp(now), now)
        result.requests = session.count
        store.set_progress(name, f"day:{day}", str(used + session.count), now)
        store.log("news_stored" if result.stored else "news_noop",
                  f"{name}: {result.stored} new, {result.requests} request(s); "
                  + "; ".join(result.notes), now)
    return results


def fetch_http(ua: str) -> Fetch:
    def fetch(url: str) -> tuple[int | None, bytes]:
        if not url.startswith("https://"):
            return None, b""  # only https URLs from SOURCES are ever requested
        headers = {"User-Agent": ua, "Accept": "*/*", "Accept-Encoding": "identity"}
        req = request.Request(url, headers=headers)  # noqa: S310 - https only, checked above
        try:
            with request.urlopen(req, timeout=30) as resp:  # noqa: S310 - https URLs from SOURCES only
                return resp.status, resp.read(MAX_BODY)
        except error.HTTPError as exc:
            return exc.code, b""
        except Exception:  # noqa: BLE001 - a network failure is simply "not read"
            return None, b""

    return fetch


def main(environ: Mapping[str, str] | None = None) -> int:
    import os

    env = os.environ if environ is None else environ
    contact = tick.resolve_contact(env)
    if not contact:
        print("news collector REFUSED: the contact address is invalid; nothing was requested")
        return 2
    try:
        conn = library_db.get_library_connection(env)  # target guard runs here
    except library_db.LibraryConfigError as exc:
        print(f"news collector REFUSED: {exc}")
        return 2
    ua = f"PSX-NI-news/1.0 (private research; contact: {contact})"
    results = run(conn.db, fetch_http(ua), datetime.now(UTC))
    for name, r in results.items():
        print(f"{name}: {r.stored} new, {r.requests} request(s); {'; '.join(r.notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
