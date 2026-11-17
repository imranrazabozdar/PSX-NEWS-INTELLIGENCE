"""Which news matters: seven importance rules, event de-duplication, source reliability and priority.

Pure Python, no model, no database. A headline becomes an EVENT (related headlines are clustered first, so one
story told by five outlets counts once), the event is tested against the seven rules, and the flagged events
are ordered by priority. The council (engines/council_news.py) only ever sees events this module flagged.

Rules (owner's list, 17 Nov 2026):
  1 company results, earnings and payouts
  2 SBP rates, FX, fiscal policy, inflation, energy and major index movements
  3 unusual news concentration about one company, against its own history
  4 three or more DISTINCT events (after de-duplication) naming one company in one Pakistan-local day
  5 government policy, IMF, regulatory and geopolitical developments
  6 unusual news concentration about one sector, against its own history
  7 material adverse company developments (litigation, shutdowns, defaults, cancelled contracts)

An event has an id that stays the same as related headlines arrive, and a VERSION that changes only when
the story
changes (a new figure, or a new rule now applies). The council assesses each (event id, version) once.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from engines import news_facts as nf

PKT = timezone(timedelta(hours=5))  # Pakistan has no daylight saving time

RULE_NAMES = {
    1: "company results, earnings and payouts",
    2: "SBP rates, FX, fiscal policy, inflation, energy or a major index move",
    3: "unusual news concentration about a company against its baseline",
    4: "three or more distinct events about one company in one day",
    5: "government policy, IMF, regulatory or geopolitical development",
    6: "unusual news concentration about a sector against its baseline",
    7: "material adverse company development",
}
# Higher is more urgent. Adverse developments first, then results, then the macro and policy backdrop.
RULE_WEIGHT = {7: 100, 1: 90, 2: 80, 5: 70, 3: 60, 6: 55, 4: 50}

# How far each outlet's reporting is trusted by default. These are the owner-editable starting values,
# ordered by
# how closely the outlet's business desk is tied to filings and its own reporters. An outlet not listed
# here is
# UNKNOWN (None), never assumed to be good or bad.
SOURCE_RELIABILITY: dict[str, float] = {
    "dawn_business": 0.90,
    "brecorder": 0.88,
    "tribune_business": 0.85,
    "mettis": 0.80,
    "profit": 0.80,
}
MATCH_HOURS = 48  # related headlines are published within this many hours of each other
JACCARD_MIN = 0.55
CONTAIN_MIN = 0.80  # one headline's content words almost all appear in the other
CONTAIN_MIN_WORDS = 4

STOPWORDS = frozenset(
    "a an the of to in on for at by with from as is are was were be been it its this that and or but "
    "after over amid into up down out says say said new more than will would may could not no per".split()
)

# --- rule patterns ------------------------------------------------------------------------------------------
MAJOR_POINTS = 500
MAJOR_PERCENT = 1.0
_POINTS = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*points?\b", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", re.I)
RULE2_TOPICS = {
    "market.rates",
    "market.fx",
    "market.fiscal",
    "market.inflation",
    "market.energy",
    "market.power",
}
_POLICY = re.compile(
    r"\b(imf|budget|finance bill|fbr|tariffs?|subsid\w+|cabinet|ecc|privati[sz]\w+|regulat\w+|secp|ogra|"
    r"nepra|pta|competition commission|ordinance|"
    r"(?:monetary|fiscal|energy|trade|tax|economic|industrial) polic(?:y|ies)|"
    r"bans? on|banned|tax (?:relief|exemptions?|measures?|proposals?|rates?)|"
    r"(?:raises?|cuts?|imposes?|abolish\w*|withdraws?|waives?) (?:\w+ ){0,2}"
    r"(?:tax|taxes|duty|duties|levy|levies)|sbp (?:directive|circular))\b",
    re.I,
)
# When a company is in the headline, macro words are about its own business unless a macro actor is named.
_MACRO_ACTOR = re.compile(
    r"\b(sbp|state bank|govt|government|federal|ministry|ecc|cabinet|imf|ogra|nepra|fbr|regulator|authority|"
    r"policy rate|interest rate|monetary|inflation|cpi|rupee|kibor|exchange rate|budget)\b",
    re.I,
)
# A fiscal-policy headline names a fiscal instrument. A bare "tax" is not enough ("profit after tax").
_FISCAL = re.compile(
    r"\b(imf|budget|finance bill|fbr|fiscal|subsid\w+|levy|levies|duty|duties|surcharge|"
    r"tax (?:relief|exemptions?|measures?|proposals?|rates?|polic(?:y|ies)|collection|targets?|hike)|"
    r"(?:raises?|cuts?|imposes?|abolish\w*|waives?|withdraws?) (?:\w+ ){0,2}(?:tax|taxes))\b",
    re.I,
)
# A results headline names profit, earnings or results themselves. "Sales" alone is not enough ("sales tax").
_RESULTS_STRICT = re.compile(
    r"\b(profits?|earnings?|eps|net loss|loss after|loss per share|"
    r"(?:annual|quarterly|half[- ]year|full[- ]year|nine[- ]month|financial) results?|"
    r"results? for the (?:quarter|year|period))\b",
    re.I,
)
_GEOPOLITICAL = re.compile(
    r"\b(war|ceasefire|cease-fire|sanctions?|missiles?|airstrikes?|invasion|border (?:clash\w*|tensions?)|"
    r"regional tensions?|geopolitic\w*|strait of hormuz|red sea|opec\+?|iran|israel|afghanistan|taliban|"
    r"india[- ]pakistan|kashmir)\b",
    re.I,
)
_ADVERSE = re.compile(
    r"\b(lawsuits?|litigation|sued|court (?:orders?|restrains?|fines?|rejects?)|fined|penalt(?:y|ies)|"
    r"show[- ]cause|shuts? down|shutdowns?|plant closure|suspends? (?:production|operations)|"
    r"halts? production|production halt|defaults?|defaulted|delist\w*|bankrupt\w*|insolven\w*|fraud|scam|"
    r"embezzl\w*|raided|licen[cs]e (?:suspended|cancel\w*|revoked)|contract (?:cancel\w*|terminat\w*)|"
    r"cancel(?:s|led)? (?:the )?(?:contract|agreement|order)|"
    r"terminat(?:es|ed) (?:the )?(?:contract|agreement)|"
    r"force majeure|explosion|fire (?:at|breaks))\b",
    re.I,
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PAKISTANI_OUTLETS = frozenset({"mettis", "tribune_business", "dawn_business", "profit"})


@dataclass(frozen=True)
class Headline:
    source: str
    url: str
    title: str
    published_at: str  # UTC, YYYY-MM-DDTHH:MM:SSZ
    snippet: str | None = None
    section: str | None = None

    def when(self) -> datetime:
        return datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))


@dataclass(frozen=True)
class RuleHit:
    rule: int
    detail: str  # what matched, in plain words
    entities: tuple[str, ...] = ()  # tickers, SECTOR:X, MACRO:PAKISTAN

    @property
    def name(self) -> str:
        return RULE_NAMES[self.rule]


@dataclass
class Event:
    """One story, however many outlets told it. `kind` is 'headline', 'concentration' or 'signal'."""

    event_id: str
    anchor: frozenset[str]  # content words of the first headline: what later headlines are compared with
    members: list[Headline] = field(default_factory=list)
    kind: str = "headline"
    title: str = ""
    hits: list[RuleHit] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    macro: list[str] = field(default_factory=list)
    day: str = ""  # Pakistan-local day of the first headline
    company_keys: set[str] = field(default_factory=set)  # companies the clustered headlines name (kept apart)
    words: list[frozenset[str]] = field(default_factory=list)  # content words of each member headline

    @property
    def sources(self) -> list[str]:
        return sorted({m.source for m in self.members})

    @property
    def first_seen(self) -> str:
        return min((m.published_at for m in self.members), default="")

    @property
    def version(self) -> str:
        """Changes only when the story changes: a new figure appears, or a different set of rules applies."""
        numbers = sorted({n.replace(",", "") for m in self.members for n in _NUMBER.findall(m.title)})
        basis = "|".join(numbers) + "#" + ",".join(str(r) for r in sorted({h.rule for h in self.hits}))
        return hashlib.sha256(basis.encode()).hexdigest()[:10]

    @property
    def key(self) -> str:
        return f"{self.event_id}:{self.version}"


# --- tokens and de-duplication ------------------------------------------------------------------------------


SYNONYMS = {
    "reduces": "cut",
    "reduce": "cut",
    "reduced": "cut",
    "cuts": "cut",
    "slashes": "cut",
    "slash": "cut",
    "lowers": "cut",
    "lower": "cut",
    "trims": "cut",
    "hikes": "raise",
    "hike": "raise",
    "raises": "raise",
    "increases": "raise",
    "increase": "raise",
    "jumps": "raise",
    "government": "govt",
}
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?")


def content_words(title: str) -> frozenset[str]:
    """The words that identify a story: lower-case, no stop words, plural 's' folded, similar verbs unified
    (cuts/reduces), numbers kept ('3.5-4.5%' becomes 3.5 and 4.5%)."""
    out = set()
    for w in _WORD.findall(title.lower().replace("\u2019", "'")):
        w = w.strip(".,")
        if not w or w in STOPWORDS:
            continue
        w = SYNONYMS.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w[:-1].isdigit():
            w = w[:-1]
        out.add(SYNONYMS.get(w, w))
    return frozenset(out)


def similar(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    shared = a & b
    if len(shared) / len(a | b) >= JACCARD_MIN:
        return True
    if min(len(a), len(b)) >= CONTAIN_MIN_WORDS and len(shared) / min(len(a), len(b)) >= CONTAIN_MIN:
        return True
    numbers = {w for w in shared if any(ch.isdigit() for ch in w)}  # the same figure plus the same subject
    return bool(numbers) and len(shared) - len(numbers) >= 3


def similar_same_company(a: frozenset[str], b: frozenset[str]) -> bool:
    """Two headlines that name the same company, share a figure and at least two other words are one story."""
    shared = a & b
    numbers = {w for w in shared if any(ch.isdigit() for ch in w)}
    return bool(numbers) and len(shared) - len(numbers) >= 2


def _event_id(anchor: frozenset[str]) -> str:
    return hashlib.sha256(" ".join(sorted(anchor)).encode()).hexdigest()[:16]


def pkt_day(stamp: str) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(PKT).strftime("%Y-%m-%d")


def cluster(
    headlines: Iterable[Headline],
    known: Iterable[dict[str, Any]] = (),
    vocab: nf.Vocabulary | None = None,
) -> list[Event]:
    """Group related headlines into events.

    `known` are events from earlier executions ({event_id, anchor, urls, companies}), so an event keeps its
    id as the window slides and a headline already attached to one is never counted again. Related means
    similar content words, within MATCH_HOURS, and never two different companies. A headline is compared with
    every member of an event, and when it bridges two events they are merged (unless both are already known:
    their ids are kept apart)."""
    events: dict[str, Event] = {}
    from_ledger: set[str] = set()
    by_url: dict[str, str] = {}
    for k in known:
        ev = Event(event_id=k["event_id"], anchor=frozenset(k["anchor"]), title=k.get("title", ""))
        ev.company_keys = set(k.get("companies", []))
        events[ev.event_id] = ev
        from_ledger.add(ev.event_id)
        for u in k.get("urls", []):
            by_url[u] = ev.event_id

    def matches(ev: Event, h: Headline, words: frozenset[str], cos: frozenset[str]) -> bool:
        both_name = bool(cos and ev.company_keys)
        if both_name and not (cos & ev.company_keys):
            return False  # "HBL profit rises 20%" and "MCB profit rises 20%" are two stories
        if ev.members and abs((h.when() - ev.members[0].when()).total_seconds()) > MATCH_HOURS * 3600:
            return False
        pool = [ev.anchor, *ev.words]
        return any(similar(words, w) or (both_name and similar_same_company(words, w)) for w in pool)

    for h in sorted(headlines, key=lambda x: (x.published_at, x.url)):
        words = content_words(h.title)
        cos = frozenset(nf.companies_in(vocab, h.title, h.snippet)) if vocab else frozenset()
        target = by_url.get(h.url)
        if target is None:
            hit = [e for e in events.values() if matches(e, h, words, cos)]
            if hit:
                primary = next((e for e in hit if e.event_id in from_ledger), hit[0])
                for other in hit:
                    if other is primary or other.event_id in from_ledger:
                        continue
                    primary.members += other.members  # the headline bridges two events: they are one story
                    primary.words += other.words
                    primary.company_keys |= other.company_keys
                    for m in other.members:
                        by_url[m.url] = primary.event_id
                    del events[other.event_id]
                target = primary.event_id
            else:
                anchor_id = _event_id(words)
                n = 2
                while anchor_id in events:  # a different story with the same words: keep both
                    anchor_id = _event_id(words | {f"#{n}"})
                    n += 1
                events[anchor_id] = Event(event_id=anchor_id, anchor=words, title=h.title)
                target = anchor_id
        ev = events[target]
        ev.company_keys |= cos
        if not any(m.url == h.url for m in ev.members):
            ev.members.append(h)
            ev.words.append(words)
        by_url[h.url] = target
    out = [e for e in events.values() if e.members]
    for e in out:
        e.members.sort(key=lambda m: m.published_at)
        e.title = e.members[0].title
        e.day = pkt_day(e.members[0].published_at)
    return sorted(out, key=lambda e: e.first_seen)


# --- rules --------------------------------------------------------------------------------------------------


def pakistan_context(h: Headline) -> bool:
    """Business Recorder's latest-news feed mixes world stories, so it needs an explicit Pakistan context;
    the other outlets are Pakistani business desks."""
    return bool(nf.PAKISTAN_CONTEXT.search(f"{h.title}. {h.snippet or ''}")) or h.source in _PAKISTANI_OUTLETS


def _index_is_major(title: str) -> tuple[bool, str]:
    pts = [float(m.group(1).replace(",", "")) for m in _POINTS.finditer(title)]
    pct = [float(m.group(1)) for m in _PERCENT.finditer(title)]
    if pts and max(pts) >= MAJOR_POINTS:
        return True, f"{max(pts):.0f} points"
    if pct and max(pct) >= MAJOR_PERCENT:
        return True, f"{max(pct):g}%"
    return False, "size not stated or below the threshold"


def scrub_company_names(vocab: nf.Vocabulary, title: str) -> str:
    """The headline with company names removed, so a word inside a name ('Oil' in 'Punjab Oil Mills') is not
    read as news about oil or policy."""
    text = title
    if vocab._phrase_re:  # noqa: SLF001
        text = vocab._phrase_re.sub(" ", text)  # noqa: SLF001
    if vocab._single_re:  # noqa: SLF001
        text = vocab._single_re.sub(" ", text)  # noqa: SLF001
    return text


def headline_hits(vocab: nf.Vocabulary, h: Headline) -> tuple[list[RuleHit], list[str], list[str]]:
    """Rules 1, 2, 5 and 7 for one headline, plus the companies and sectors it names."""
    title, snippet = h.title, h.snippet
    text = f"{title}. {snippet or ''}"
    companies = nf.companies_in(vocab, title, snippet)
    sectors = nf.sectors_in(vocab, title)
    hits: list[RuleHit] = []
    context = pakistan_context(h)
    if 0 < len(companies) <= nf.MAX_COMPANIES:
        if nf._DIVIDEND.search(title):  # noqa: SLF001
            hits.append(RuleHit(1, "company payout headline", tuple(companies)))
        elif _RESULTS_STRICT.search(title):
            hits.append(RuleHit(1, "company results headline", tuple(companies)))
        found = _ADVERSE.search(title)
        if found:
            hits.append(RuleHit(7, f"adverse term {found.group(0)!r}", tuple(companies)))
    elif not companies and sectors:
        found = _ADVERSE.search(title)
        if found:
            hits.append(
                RuleHit(
                    7, f"adverse term {found.group(0)!r} for a sector", tuple(f"SECTOR:{s}" for s in sectors)
                )
            )
    bare = scrub_company_names(vocab, title)
    # a Pakistani business desk's headline is Pakistan news even when it does not say the word
    ctx_text = text if nf.PAKISTAN_CONTEXT.search(text) else f"{text} Pakistan"
    market = nf.macro_topic(bare, ctx_text) if context else None
    if market == "market.fiscal" and not _FISCAL.search(bare):
        market = None
    if market and market != "market.index" and companies and not _MACRO_ACTOR.search(bare):
        market = None
    if market in RULE2_TOPICS:
        hits.append(RuleHit(2, market, ("MACRO:PAKISTAN",)))
    elif market == "market.index":
        major, size = _index_is_major(bare)
        if major:
            hits.append(RuleHit(2, f"major index move ({size})", ("MACRO:PAKISTAN",)))
    pol = _POLICY.search(bare) if context else None
    geo = _GEOPOLITICAL.search(bare)
    if pol or geo:
        word = (pol or geo).group(0)
        hits.append(
            RuleHit(5, f"{'policy/regulatory' if pol else 'geopolitical'} term {word!r}", ("MACRO:PAKISTAN",))
        )
    return hits, companies, [f"SECTOR:{s}" for s in sectors]


def classify(vocab: nf.Vocabulary, events: list[Event]) -> None:
    """Fill each event's hits, companies and sectors from its members (the first headline names the story)."""
    for e in events:
        if e.kind != "headline":
            continue
        e.hits, e.companies, e.sectors = [], [], []
        for h in e.members:
            hits, companies, sectors = headline_hits(vocab, h)
            for hit in hits:
                if not any(x.rule == hit.rule for x in e.hits):
                    e.hits.append(hit)
            for c in companies:
                if c not in e.companies:
                    e.companies.append(c)
            for s in sectors:
                if s not in e.sectors:
                    e.sectors.append(s)
        e.macro = ["MACRO:PAKISTAN"] if any(x.rule in (2, 5) for x in e.hits) else []


def concentration_events(events: list[Event], min_events: int = 3) -> list[Event]:
    """Rule 4: one company named by `min_events` or more DISTINCT events (already de-duplicated) in one
    Pakistan-local
    day. Returns one synthetic event per company and day; the underlying events stay as they are."""
    per: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        if e.kind != "headline":
            continue
        for c in e.companies:
            per.setdefault((c, e.day), []).append(e)
    out = []
    for (company, day), group in sorted(per.items()):
        if len(group) < min_events:
            continue
        members = sorted((m for g in group for m in g.members), key=lambda m: m.published_at)
        ev = Event(
            event_id=f"conc-{company}-{day}",
            anchor=frozenset({f"concentration:{company}:{day}"}),
            members=members,
            kind="concentration",
            title=f"{company}: {len(group)} distinct news events on {day}",
            hits=[RuleHit(4, f"{len(group)} distinct events named {company} on {day}", (company,))],
            companies=[company],
            day=day,
        )
        out.append(ev)
    return out


def signal_events(signals: list[dict[str, Any]], day: str) -> list[Event]:
    """Rules 3 and 6 from news_rollup.signals(): an entity whose share of the news stands out against its own
    history. A company is rule 3, a SECTOR:* entity rule 6; MACRO and ALL are not flagged here."""
    out = []
    for s in signals:
        entity = s["company"]
        if entity.startswith("MACRO:") or entity == "ALL":
            continue
        rule = 6 if entity.startswith("SECTOR:") else 3
        link = s.get("source_url")
        members = [Headline("rollup", link, s["fact_text"], f"{day}T00:00:00Z")] if link else []
        out.append(
            Event(
                event_id=f"sig-{entity}-{day}",
                anchor=frozenset({f"signal:{entity}:{day}"}),
                members=members,
                kind="signal",
                title=s["fact_text"],
                hits=[RuleHit(rule, s["fact_text"][:160], (entity,))],
                companies=[] if rule == 6 else [entity],
                sectors=[entity] if rule == 6 else [],
                day=day,
            )
        )
    return out


# --- priority -----------------------------------------------------------------------------------------------


def reliability(source: str) -> float | None:
    return SOURCE_RELIABILITY.get(source)


def provenance(e: Event) -> list[dict[str, Any]]:
    """Every outlet that carried the story, with its link, time and default reliability (None when
    unknown)."""
    return [
        {
            "source": m.source,
            "url": m.url,
            "published_at": m.published_at,
            "reliability": reliability(m.source),
        }
        for m in e.members
    ]


def priority(e: Event, now: datetime | None = None) -> float:
    """Higher runs first. The strongest rule sets the base; extra rules, trusted outlets, corroboration
    by several
    outlets and recency add a little. An unknown source counts as neutral (0.8) in the score but is reported
    as unknown, never as a number."""
    if not e.hits:
        return 0.0
    base = max(RULE_WEIGHT[h.rule] for h in e.hits)
    extra = 3 * min(len({h.rule for h in e.hits}) - 1, 3)
    rel = [reliability(m.source) for m in e.members]
    best = max((r for r in rel if r is not None), default=0.8)
    outlets = len({m.source for m in e.members if m.source != "rollup"})
    score = base + extra + 10 * (best - 0.8) + 4 * min(max(outlets - 1, 0), 3)
    if now and e.members:
        age_h = (now - e.members[-1].when()).total_seconds() / 3600
        score += max(0.0, 5.0 - age_h / 6)  # up to 5 points for news under about 30 minutes old
    return round(score, 2)


def flagged(events: list[Event]) -> list[Event]:
    return [e for e in events if e.hits]


def prioritised(events: list[Event], now: datetime | None = None) -> list[Event]:
    return sorted(flagged(events), key=lambda e: (-priority(e, now), e.first_seen, e.event_id))


def local_day(now: datetime) -> str:
    return now.astimezone(PKT).strftime("%Y-%m-%d")


def utc_now() -> datetime:
    return datetime.now(UTC)
