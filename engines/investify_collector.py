"""Investify announcement collector (news-side acquisition of material information and board meetings).

WHAT THIS MODULE DOES
    Parses the public Investify announcements page into announcement records, keeps only the symbols in
    config/coverage_watchlist.json, classifies each record by keyword, de-duplicates it and attaches
    provenance.
    It is a pure parser: it performs no network access and writes nothing.

WHAT LIVE COLLECTION WOULD DO (NOT ENABLED, NOT RUN HERE)
    A scheduled job would fetch the page, run this parser, and write announcement METADATA (symbol, date,
    title, category, source URL, PDF URL, hash) to the news database. That job runs in the owner's scheduler
    with the news-database credentials, not in this session. The PDF itself is not downloaded by this module.
    When pdf_access is "gated_dps" the PDF is on PSX's own host and must be fetched through a browser
    session the owner has authorised; it is never fetched by this module.

LEGAL STATUS (see config/sources_registry or database/seed/sources.json, entry investify_announcements)
    Investify's terms prohibit using automated means to systematically collect or store Market Information
    (which includes announcements) to build or feed a database without its express written consent. The source
    is therefore registered DISABLED. Enabling it requires that consent. PSX's own terms also prohibit
    systematic retrieval; the PDF links point to PSX's host.

The Investify summary paragraph is Investify's own generated text. It is NOT parsed or stored.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

SOURCE = "investify"
BASE_URL = "https://www.investify.pk"
PSX_HOST = "dps.psx.com.pk"
PKT = timezone(timedelta(hours=5))  # Pakistan Standard Time, UTC+5, no DST
WATCHLIST_PATH = Path(__file__).resolve().parents[1] / "config" / "coverage_watchlist.json"

# Ordered: the first category whose keyword appears in the title or Investify's label wins.
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("material_information", ("material information", "price sensitive", "price-sensitive")),
    ("board_meeting", ("board meeting", "board of directors meeting", "meeting of the board")),
    ("dividend", ("dividend",)),
    ("bonus_right", ("bonus", "right issue", "rights issue", "right shares", "right share",
                     "rights / bonus")),
    ("merger_acquisition", ("merger", "amalgamation", "acquisition", "scheme of arrangement",
                            "scheme / arrangement", "takeover", "restructuring")),
    ("directors_dealing", ("insider", "director reports", "director reported", "directors' dealing")),
    ("management_change", ("chief executive", "ceo", "cfo", "resign", "appoint", "company secretary")),
    ("corporate_briefing", ("briefing", "presentation")),
    ("financial_results", ("financial result", "half year", "half-year", "annual accounts", "interim",
                           "quarter ended", "quarterly results", "annual results", "net profit", "net loss",
                           "profit after tax", "earnings per share")),
    ("fund_report", ("fund manager", "fund's report", "net asset value")),
)
CATEGORIES = tuple(c for c, _ in CATEGORY_RULES) + ("other",)
# Categories an owner-facing material-information feed keeps by default.
MATERIAL_CATEGORIES = frozenset({"material_information", "board_meeting", "dividend", "bonus_right",
                                 "merger_acquisition", "financial_results", "management_change",
                                 "directors_dealing"})

_LD_ITEMLIST = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_COMPANY = re.compile(r'<a[^>]*href="/company/([A-Z0-9&-]+)/quote">\1</a>')
_TIME = re.compile(r'<time dateTime="([^"]+)"')
_HEADING = re.compile(r'<h3[^>]*><a[^>]*href="(/announcements/([A-Z0-9&-]+)/[^"]+)"[^>]*>([^<]*)</a></h3>')
_PSX_PDF = re.compile(r'href="(https://dps\.psx\.com\.pk/download/[^"]+)"')
_TEXT_SPAN = re.compile(r">([^<>]+)</span>")


@dataclass(frozen=True)
class AnnouncementRecord:
    symbol: str
    company_name: str
    announced_at_utc: str  # ISO-8601 UTC, from the page's <time dateTime>
    announced_on_pkt: str  # YYYY-MM-DD in Pakistan time
    title: str
    investify_label: str  # Investify's own category label on the card, e.g. "Report Transmission"
    category: str
    sentiment_label: str  # Investify's label, not our assessment
    source: str
    source_url: str
    pdf_url: str | None
    pdf_access: str  # "gated_dps" (PSX host, browser fetch only) | "none"
    retrieved_at_utc: str
    content_sha256: str


@dataclass(frozen=True)
class CollectionResult:
    records: tuple[AnnouncementRecord, ...]
    skipped_off_watchlist: int
    skipped_duplicates: int
    parse_problems: tuple[str, ...]


def load_watchlist_symbols(path: Path = WATCHLIST_PATH) -> frozenset[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return frozenset(c["symbol"] for c in data["companies"])


def classify(title: str, label: str = "") -> str:
    """Keyword classification. Heuristic: it reads the title and Investify's label, not the PDF."""
    text = f"{title} {label}".lower()
    for category, keywords in CATEGORY_RULES:
        if any(k in text for k in keywords):
            return category
    return "other"


def _pdf_access(pdf_url: str | None) -> str:
    if not pdf_url:
        return "none"
    return "gated_dps" if f"//{PSX_HOST}/" in pdf_url else "downloadable"


def _content_hash(symbol: str, announced_at_utc: str, title: str, source_url: str,
                  pdf_url: str | None) -> str:
    canonical = json.dumps([symbol, announced_at_utc, title, source_url, pdf_url], ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_cards(page: str, retrieved_at_utc: str, problems: list[str]) -> list[AnnouncementRecord]:
    records: list[AnnouncementRecord] = []
    times = list(_TIME.finditer(page))
    for i, tm in enumerate(times):
        end = times[i + 1].start() if i + 1 < len(times) else len(page)
        company = [m for m in _COMPANY.finditer(page) if m.start() < tm.start()]
        if not company:
            problems.append(f"card {i}: no company link before its timestamp")
            continue
        symbol = company[-1].group(1)
        segment = page[company[-1].end():tm.start()]
        spans = [html.unescape(s).strip() for s in _TEXT_SPAN.findall(segment)]
        spans = [s for s in spans if s]
        if len(spans) < 3:
            problems.append(f"card {i} ({symbol}): expected name, label and sentiment spans")
            continue
        company_name, label, sentiment = spans[0], spans[1], spans[2]
        heading = _HEADING.search(page, tm.end(), end)
        if not heading or heading.group(2) != symbol:
            problems.append(f"card {i} ({symbol}): no matching announcement heading")
            continue
        href, title = heading.group(1), html.unescape(heading.group(3)).strip()
        pdf_match = _PSX_PDF.search(page, heading.end(), end)
        pdf_url = html.unescape(pdf_match.group(1)) if pdf_match else None
        try:
            when = datetime.fromisoformat(tm.group(1).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            problems.append(f"card {i} ({symbol}): unreadable timestamp {tm.group(1)!r}")
            continue
        at_utc = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        source_url = BASE_URL + href
        records.append(AnnouncementRecord(
            symbol=symbol,
            company_name=company_name,
            announced_at_utc=at_utc,
            announced_on_pkt=when.astimezone(PKT).date().isoformat(),
            title=title,
            investify_label=label,
            category=classify(title, label),
            sentiment_label=sentiment,
            source=SOURCE,
            source_url=source_url,
            pdf_url=pdf_url,
            pdf_access=_pdf_access(pdf_url),
            retrieved_at_utc=retrieved_at_utc,
            content_sha256=_content_hash(symbol, at_utc, title, source_url, pdf_url),
        ))
    return records


def collect(page: str, *, watchlist: Iterable[str], retrieved_at_utc: str,
            categories: Iterable[str] | None = None) -> CollectionResult:
    """Parse an Investify announcements page. Pure: no network, no writes.

    `watchlist` is the set of symbols to keep. `categories`, if given, restricts output to those categories.
    De-duplication key is (symbol, announced_on_pkt, title); the first occurrence is kept.
    """
    watch = frozenset(watchlist)
    problems: list[str] = []
    parsed = _parse_cards(page, retrieved_at_utc, problems)
    wanted = None if categories is None else frozenset(categories)

    kept: list[AnnouncementRecord] = []
    seen: set[tuple[str, str, str]] = set()
    off_watchlist = duplicates = 0
    for rec in parsed:
        if rec.symbol not in watch:
            off_watchlist += 1
            continue
        if wanted is not None and rec.category not in wanted:
            continue
        key = (rec.symbol, rec.announced_on_pkt, rec.title)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        kept.append(rec)
    return CollectionResult(records=tuple(kept), skipped_off_watchlist=off_watchlist,
                            skipped_duplicates=duplicates, parse_problems=tuple(problems))


def collect_from_file(path: Path, *, retrieved_at_utc: str, watchlist: Iterable[str] | None = None,
                      categories: Iterable[str] | None = None) -> CollectionResult:
    """Offline convenience for fixtures and reviews. Reads a saved file; never fetches."""
    watch = load_watchlist_symbols() if watchlist is None else watchlist
    page = Path(path).read_text(encoding="utf-8", errors="replace")
    return collect(page, watchlist=watch, retrieved_at_utc=retrieved_at_utc, categories=categories)
