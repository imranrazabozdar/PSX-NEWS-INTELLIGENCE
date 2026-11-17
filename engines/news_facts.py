"""News headlines to dated research_fact rows. Pure Python, no model: the rules are visible and testable.

Each news_item (headline, snippet, link, published time) becomes zero or more fact rows:
- a COMPANY row for every listed company the text names (a company name or its PSX ticker), at most three;
- a SECTOR row when the text is about a sector the library already has;
- a MACRO:PAKISTAN row (market.*) for index moves and for policy, rates, FX, inflation, energy, fiscal and
  trade news, only when the text has a Pakistan context (so world news in a general feed is not stored as
  Pakistan fact).
A headline that names nothing and has no context becomes no row. Every row carries the outlet, the link and
the publication date as source_date; "today" and "yesterday" are rewritten as dates so an old row never
reads as current.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from engines import freshness

MAX_FACT_CHARS = 300
MAX_COMPANIES = 3
OUTLETS = {
    "mettis": "Mettis",
    "tribune_business": "Express Tribune Business",
    "dawn_business": "Dawn Business",
    "brecorder": "Business Recorder",
    "profit": "Profit (Pakistan Today)",
}
_LEGAL = re.compile(
    r"\((?:pvt\.?|private)\)|\b(?:private|pvt\.?|limited|ltd\.?|company|corporation|corp\.?)\b", re.I
)
# Listed symbols that are also common acronyms or words in the news; never matched as a bare ticker.
# One-word company names that are also ordinary words; never matched as a company on their own.
COMMON_SINGLES = {
    "Systems",
    "Industries",
    "Packages",
    "Pakistan",
    "National",
    "Power",
    "Bank",
    "Mills",
    "Textile",
    "Insurance",
    "Services",
    "Foods",
    "Pharma",
    "Cement",
    "Fertilizer",
    "Sugar",
    "Steel",
    "Energy",
    "Motors",
    "Chemicals",
    "General",
    "Global",
    "United",
    "Allied",
    "Standard",
}
TICKER_STOPLIST = {
    "PPP",  # the political party, as often as Pakistan Paper Products
    "PSX",
    "KSE",
    "IMF",
    "SBP",
    "FBR",
    "CPI",
    "GDP",
    "USD",
    "PKR",
    "SECP",
    "OGRA",
    "NEPRA",
    "CCP",
    "ECC",
    "UAE",
    "CEO",
    "CFO",
    "IPO",
    "EPS",
    "ETF",
    "LNG",
    "AI",
    "PMI",
    "PPI",
    "LSM",
    "CPEC",
    "ADB",
    "WTO",
    "OPEC",
    "FATF",
    "EV",
    "SPI",
    "WPI",
    "CNG",
    "LPG",
    "FOB",
    "NAB",
    "PIDE",
    "ICCI",
    "SAFA",
    "PACRA",
    "VIS",
    "FPCCI",
    "THE",
    "AND",
    "FOR",
    "NEW",
}
PAKISTAN_CONTEXT = re.compile(
    r"\b(pakistan\w*|psx|kse[- ]?\d*|sbp|state bank|rupee|pkr|karachi|lahore|islamabad|fbr|nepra|ogra|secp|"
    r"federal government|punjab|sindh|balochistan|khyber|isi|national assembly|ecc|cabinet)\b",
    re.I,
)
_SPONSOR = re.compile(r"\s+(?:manufacturing\s+)?(?:pmi|psl|super league)\b", re.I)
_RESULTS = re.compile(
    r"\b(profit|earnings?|eps|net loss|loss after|revenue|sales|results?|quarter|q[1-4]|"
    r"half[- ]year|nine[- ]month|full[- ]year|fy\d{2,4})\b",
    re.I,
)
_DIVIDEND = re.compile(r"\b(dividend|payout|bonus shares?|right shares?|interim cash)\b", re.I)
_RESERVES = re.compile(r"\b((forex|foreign exchange|fx) reserves?|current account|trade deficit)\b", re.I)
_INDEX = re.compile(r"\b(kse[- ]?(?:100|all|30)?|psx|benchmark index|bourse|stocks?|equities)\b", re.I)
MARKET_TOPIC = {
    "interest_rate": "market.rates",
    "exchange_rate": "market.fx",
    "inflation": "market.inflation",
    "oil_energy": "market.energy",
    "power_tariff": "market.power",
    "coal_fuel_cost": "market.energy",
    "imf_fiscal": "market.fiscal",
    "global_demand": "market.trade",
    "regulation": "market.regulation",
    "politics_security": "market.politics",
    "construction_cycle": "market.construction",
    "agri_cycle": "market.agriculture",
}
SECTOR_WORDS = {
    "CEMENT": ("cement",),
    "BANKS": ("bank", "banks", "banking", "lenders"),
    "FERTILIZER": ("fertilizer", "fertiliser", "urea", "dap"),
    "AUTOS": (
        "automobile",
        "automobiles",
        "auto sector",
        "car sales",
        "motorcycle",
        "vehicle sales",
        "assemblers",
    ),
    "TEXTILE": ("textile", "textiles", "cotton yarn", "garment", "apparel", "spinning"),
    "SUGAR": ("sugar",),
    "STEEL": ("steel", "rebar"),
    "POWER": ("power sector", "power plant", "ipps", "independent power"),
    "OIL_GAS": ("oil marketing", "omcs", "exploration and production", "e&p", "gas utility", "lng"),
    "REFINERY": ("refinery", "refineries", "refining"),
    "PHARMA": ("pharma", "pharmaceutical", "drug prices"),
    "TECH": ("software", "it exports", "technology sector"),
    "TELECOM": ("telecom", "mobile operators", "5g"),
    "REAL_ESTATE": ("real estate", "housing", "reit", "property market"),
    "INSURANCE": ("insurance", "takaful"),
    "FOOD": ("food companies", "dairy", "edible oil"),
    "GLASS": ("glass",),
    "AIRLINES": ("airline", "airlines", "pia"),
    "CHEMICALS": ("chemicals", "polyester", "pta"),
    "TOBACCO": ("tobacco", "cigarette"),
}


@dataclass(frozen=True)
class Vocabulary:
    phrases: dict[str, str]  # lower-case multi-word name -> ticker
    singles: dict[str, str]  # exact-case one-word name -> ticker
    tickers: frozenset[str]
    sectors: frozenset[str]  # sector entity names that exist in the library, e.g. 'CEMENT'

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_phrase_re",
            re.compile(
                r"\b(?:"
                + "|".join(re.escape(p) for p in sorted(self.phrases, key=len, reverse=True))
                + r")\b",
                re.I,
            )
            if self.phrases
            else None,
        )
        object.__setattr__(
            self,
            "_single_re",
            re.compile(
                r"\b(?:"
                + "|".join(re.escape(s) for s in sorted(self.singles, key=len, reverse=True))
                + r")\b"
            )
            if self.singles
            else None,
        )


def _name_phrase(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9&' -]+", " ", _LEGAL.sub(" ", name))
    return re.sub(r"\s+", " ", text).strip()


def build_vocabulary(listing: dict[str, str], aliases: dict[str, str], sectors: Iterable[str]) -> Vocabulary:
    """The company names and tickers the matcher knows: listed names (legal suffixes dropped) and aliases."""
    phrases: dict[str, str] = {}
    singles: dict[str, str] = {}
    symbols = set(listing)
    listed = [(name, sym) for sym, name in listing.items()]
    aliased = [
        (alias, target)
        for alias, target in aliases.items()
        if target in symbols or (target.isalnum() and target.upper() == target and ":" not in target)
    ]
    for name, sym in listed + aliased:
        if sym in TICKER_STOPLIST:
            continue  # the exchange itself, an index or an acronym: market news, not a company
        phrase = _name_phrase(name)
        if len(phrase) < 5 or phrase.upper() == sym:
            continue
        if " " in phrase:
            phrases.setdefault(phrase.lower(), sym)
        elif (name, sym) in aliased and phrase[0].isupper() and phrase not in COMMON_SINGLES:
            # a one-word name counts only when it is a confirmed alias: "Tariq Corporation Limited" must not
            # make every "Tariq" in the news a company
            singles.setdefault(phrase, sym)
    all_tickers = symbols | {t for t in aliases.values() if t.isalnum() and t.upper() == t and ":" not in t}
    return Vocabulary(phrases, singles, frozenset(all_tickers - TICKER_STOPLIST), frozenset(sectors))


def _mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.6


def companies_in(vocab: Vocabulary, title: str, snippet: str | None = None) -> list[str]:
    """Tickers named in the HEADLINE, in order of first appearance (the snippet is not used: a company
    mentioned in passing is not what the story is about). A bare ticker counts only in an ordinary-case
    headline, and a sponsor mention ("HBL PMI", "HBL PSL") is not news about the company."""
    found: list[tuple[int, int, str]] = []
    if vocab._phrase_re:  # noqa: SLF001
        for m in vocab._phrase_re.finditer(title):  # noqa: SLF001
            found.append((m.start(), m.end(), vocab.phrases[m.group(0).lower()]))
    if vocab._single_re:  # noqa: SLF001
        for m in vocab._single_re.finditer(title):  # noqa: SLF001
            found.append((m.start(), m.end(), vocab.singles[m.group(0)]))
    if not _mostly_upper(title):
        for m in re.finditer(r"\b[A-Z]{3,7}\b", title):
            if m.group(0) in vocab.tickers:
                found.append((m.start(), m.end(), m.group(0)))
    out: list[str] = []
    for _start, end, sym in sorted(found):
        if sym not in out and not _SPONSOR.match(title[end:]):
            out.append(sym)
    return out


def sectors_in(vocab: Vocabulary, text: str) -> list[str]:
    low = text.lower()
    return [
        s
        for s, words in SECTOR_WORDS.items()
        if s in vocab.sectors and any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)
    ]


def absolute_dates(text: str, published: date) -> str:
    """'today' / 'yesterday' / 'tomorrow' as dates, so the sentence still means the same thing later."""

    def fmt(d: date) -> str:
        return f"on {d.day} {d.strftime('%b %Y')}"

    text = re.sub(r"\btoday\b", fmt(published), text, flags=re.I)
    text = re.sub(r"\byesterday\b", fmt(published - timedelta(days=1)), text, flags=re.I)
    return re.sub(r"\btomorrow\b", fmt(published + timedelta(days=1)), text, flags=re.I)


def _confidence(section: str | None, title: str) -> str:
    if re.search(r"editorial|opinion|analysis|view|column", section or "", re.I):
        return "analyst_view"
    return (
        "analyst_view"
        if re.search(r"\b(expects?|expected to|forecasts?|projects?|outlook)\b", title, re.I)
        else "fact"
    )


def fact_text(title: str, snippet: str | None, published: date, limit: int = MAX_FACT_CHARS) -> str:
    """The headline, plus the first sentence of the snippet when there is room, as plain dated text."""
    head = absolute_dates(" ".join(title.split()), published).rstrip(" .")
    stop = "" if head.endswith(("?", "!")) else "."
    extra = ""
    if snippet:
        first = re.split(r"(?<=[.!?])\s", absolute_dates(" ".join(snippet.split()), published), maxsplit=1)[0]
        if first and first.rstrip(" .").lower() not in head.lower():
            extra = " " + first
    text = head + stop + extra
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "..."


def topic_for_company(title: str, snippet: str | None) -> str:
    """The kind of company news, from the HEADLINE (a snippet that mentions a payout does not make it one)."""
    if _DIVIDEND.search(title):
        return "news.dividend"
    return "news.results" if _RESULTS.search(title) else "news.company"


MACRO_PRIORITY = (
    "interest_rate",
    "exchange_rate",
    "inflation",
    "oil_energy",
    "power_tariff",
    "imf_fiscal",
    "global_demand",
)


def macro_topic(title: str, context_text: str) -> str | None:
    """market.* for an index move or one macro factor named in the HEADLINE, when the text has a Pakistan
    context. The first factor in MACRO_PRIORITY wins, so the same headline always gets the same topic."""
    if not PAKISTAN_CONTEXT.search(context_text):
        return None
    moves = r"\b(points?|gains?|falls?|drops?|surges?|rall(?:y|ies)|settles?|closes?|slips?|slides?)\b"
    if _INDEX.search(title) and re.search(moves, title, re.I):
        return "market.index"
    if _RESERVES.search(title):
        return "market.fx"
    found = freshness.factors_in(title)
    for factor in MACRO_PRIORITY:
        if factor in found:
            return MARKET_TOPIC[factor]
    return None


def rows_for_item(vocab: Vocabulary, item: dict, *, created_at: str, macro_copy: bool = True) -> list[dict]:
    """Fact rows (research_fact columns) for one news_item row; [] when it names nothing relevant.

    macro_copy (owner decision, 16 Nov 2026): a headline that already gets a company or sector row is also
    filed once under MACRO:PAKISTAN as market.news, so the macro entity holds the full Pakistan news flow."""
    title, snippet = item["title"], item.get("snippet")
    published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
    day = published.date()
    outlet = OUTLETS.get(item["source"], item["source"])
    text = f"{title}. {snippet or ''}"
    tickers = companies_in(vocab, title, snippet)
    targets: list[tuple[str, str]] = []
    if 0 < len(tickers) <= MAX_COMPANIES:
        topic = topic_for_company(title, snippet)
        targets += [(t, topic) for t in tickers]
    if not targets or len(tickers) > MAX_COMPANIES:
        context = bool(PAKISTAN_CONTEXT.search(text)) or item["source"] != "brecorder"
        for sector in sectors_in(vocab, title):
            if context:
                targets.append((f"SECTOR:{sector}", "news.sector"))
    market = macro_topic(title, text)
    if market:
        targets.append(("MACRO:PAKISTAN", market))
    elif macro_copy and targets and (PAKISTAN_CONTEXT.search(text) or item["source"] != "brecorder"):
        targets.append(("MACRO:PAKISTAN", "market.news"))
    rows = []
    for company, topic in dict.fromkeys(targets):
        rows.append(
            {
                "company": company,
                "topic": topic,
                "fact_text": fact_text(title, snippet, day),
                "value": None,
                "unit": None,
                "period": None,
                "source_name": f"{outlet} news, {day.isoformat()}",
                "source_url": item["url"],
                "source_date": day.isoformat(),
                "as_of": day.isoformat(),
                "confidence": _confidence(item.get("section"), title),
                "created_at": created_at,
            }
        )
    return rows
