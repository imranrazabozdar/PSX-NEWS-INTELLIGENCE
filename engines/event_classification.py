"""Deterministic headline classification, status stage, entity mentions and claim nature (Stage 2, batch 1).

Pure functions over one headline; no database writes. Every result carries the exact matched text as its
evidence, and nothing is inferred beyond the rules below. Rules are contextual: a type needs a subject term
AND (where listed) a context term, so "rate" alone or "oil" without a price/supply word does not classify.

Values used are the existing ones in engines/schema.py (EVENT_TYPES, STATUS_STAGES, ENTITY_TYPES).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from engines import schema

_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")
_UNIT = re.compile(
    r"(?i)(rs\.?\s?\d|\d\s?(%|pc|percent|bn|billion|mn|million|trillion|tr|bps|cents?|"
    r"per\s?(barrel|litre|liter|tonne|ton|mmbtu|unit|share)))|\$\s?\d|\d\s?usd"
)


def norm(text: str) -> str:
    return " " + " ".join(_WORD.findall((text or "").casefold())) + " "


def has(n: str, phrase: str) -> bool:
    return f" {' '.join(_WORD.findall(phrase.casefold()))} " in n


def _hits(n: str, phrases) -> list[str]:
    return [p for p in phrases if has(n, p)]


# (event_type, subject terms, context terms or None, needs_company). Order = priority for the primary type.
RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...] | None, bool], ...] = (
    (
        "corporate_dividend",
        ("dividend", "bonus shares", "bonus issue", "payout", "interim cash"),
        None,
        False,
    ),
    (
        "corporate_result",
        ("profit", "earnings", "eps", "net loss", "loss after tax", "results", "revenue", "sales"),
        (
            "posts",
            "reports",
            "announces",
            "quarter",
            "q1",
            "q2",
            "q3",
            "q4",
            "half-year",
            "annual",
            "1h",
            "9m",
            "fy",
            "jumps",
            "falls",
            "rises",
            "declines",
            "surges",
            "drops",
            "up",
            "down",
        ),
        True,
    ),
    (
        "corporate_action",
        (
            "merger",
            "acquisition",
            "acquire",
            "acquires",
            "takeover",
            "rights issue",
            "buyback",
            "buy-back",
            "delisting",
            "delist",
            "ipo",
            "stake",
            "amalgamation",
            "demerger",
        ),
        None,
        False,
    ),
    (
        "management_change",
        (
            "ceo",
            "chairman",
            "managing director",
            "cfo",
            "board of directors",
            "resigns",
            "appointed",
            "appoints",
        ),
        ("ceo", "chairman", "managing director", "cfo", "board", "director"),
        False,
    ),
    # a court or tribunal matter is a legal event even when it concerns a tariff, a tax or a company
    (
        "legal_court",
        (
            "court",
            "supreme court",
            "high court",
            "tribunal",
            "verdict",
            "petition",
            "lawsuit",
            "case",
            "nab",
            "stay order",
        ),
        None,
        False,
    ),
    (
        "monetary_policy",
        (
            "policy rate",
            "interest rate",
            "monetary policy",
            "kibor",
            "rate cut",
            "rate hike",
            "discount rate",
            "mpc",
        ),
        None,
        False,
    ),
    (
        "monetary_policy",
        ("fed", "federal reserve", "ecb", "bank of england"),
        ("rate", "rates", "hike", "hikes", "cut", "cuts", "holds", "pause"),
        False,
    ),
    ("imf_program", ("imf",), None, False),
    (
        "tax_policy",
        (
            "tax",
            "taxes",
            "sales tax",
            "income tax",
            "withholding",
            "customs duty",
            "regulatory duty",
            "excise",
            "sro",
            "fbr",
            "super tax",
            "levy",
            "petroleum levy",
        ),
        None,
        False,
    ),
    (
        "fiscal_policy",
        (
            "budget",
            "fiscal",
            "deficit",
            "privatisation",
            "privatization",
            "subsidy",
            "development spending",
            "psdp",
            "borrowing",
            "eurobond",
            "sukuk",
        ),
        None,
        False,
    ),
    (
        "energy_policy",
        (
            "circular debt",
            "tariff",
            "power tariff",
            "fuel adjustment",
            "fca",
            "nepra",
            "ogra",
            "gas price",
            "petrol price",
            "electricity price",
            "capacity payments",
            "ipps",
        ),
        None,
        False,
    ),
    (
        "commodity_price",
        (
            "oil",
            "crude",
            "brent",
            "gold",
            "coal",
            "urea",
            "cotton",
            "wheat",
            "sugar",
            "lng",
            "lpg",
            "steel",
            "copper",
        ),
        (
            "price",
            "prices",
            "rises",
            "falls",
            "surges",
            "slumps",
            "jumps",
            "drops",
            "per barrel",
            "per tonne",
            "rally",
            "plunge",
            "high",
            "low",
            "rate",
        ),
        False,
    ),
    (
        "commodity_supply",
        ("oil", "crude", "lng", "lpg", "gas", "coal", "wheat", "sugar", "cotton", "urea"),
        (
            "supply",
            "shortage",
            "imports",
            "import",
            "cargo",
            "shipment",
            "output",
            "production",
            "stocks",
            "curtailment",
            "disruption",
        ),
        False,
    ),
    (
        "economic_indicator",
        (
            "inflation",
            "cpi",
            "gdp",
            "current account",
            "remittances",
            "reserves",
            "trade deficit",
            "rupee",
            "pkr",
            "exchange rate",
            "lsm",
            "growth",
        ),
        None,
        False,
    ),
    (
        "trade_policy",
        ("exports", "export", "imports", "trade", "tariffs", "free trade", "fta", "quota"),
        (
            "policy",
            "ban",
            "agreement",
            "deal",
            "duty",
            "tariff",
            "tariffs",
            "restriction",
            "restrictions",
            "allowed",
            "allows",
            "bans",
            "lifts",
        ),
        False,
    ),
    (
        "credit_rating",
        ("rating", "ratings", "moody's", "moodys", "fitch", "s&p", "pacra", "vis"),
        ("upgrade", "upgrades", "downgrade", "downgrades", "affirms", "outlook", "rating"),
        False,
    ),
    (
        "regulatory_action",
        (
            "secp",
            "competition commission",
            "ccp",
            "pta",
            "regulator",
            "penalty",
            "fine",
            "licence",
            "license",
            "show-cause",
            "show cause",
        ),
        None,
        False,
    ),
    (
        "market_structure",
        ("psx", "kse-100", "kse 100", "kse100", "stock exchange", "bourse", "index", "shares", "stocks"),
        (
            "points",
            "closes",
            "gains",
            "loses",
            "trading",
            "rally",
            "slump",
            "record",
            "volume",
            "session",
            "halt",
        ),
        False,
    ),
    (
        "geopolitical",
        (
            "war",
            "conflict",
            "sanctions",
            "ceasefire",
            "border",
            "strike",
            "strikes",
            "missile",
            "tensions",
            "attack",
            "geopolitical",
        ),
        None,
        False,
    ),
    (
        "security_incident",
        ("blast", "explosion", "terror", "terrorist", "militant", "militants", "bomb"),
        None,
        False,
    ),
    (
        "infrastructure",
        (
            "pipeline",
            "port",
            "motorway",
            "railway",
            "power plant",
            "dam",
            "refinery",
            "grid",
            "outage",
            "breakdown",
            "shutdown",
        ),
        None,
        False,
    ),
    (
        "political",
        (
            "election",
            "by-election",
            "parliament",
            "senate",
            "national assembly",
            "cabinet",
            "prime minister",
            "president",
            "coalition",
            "protest",
            "pti",
            "pml-n",
            "ppp",
        ),
        None,
        False,
    ),
    (
        "corporate_announcement",
        ("contract", "order", "agreement", "mou", "expansion", "plant", "launches", "partnership", "deal"),
        None,
        True,
    ),
)

# status-stage cues (existing STATUS_STAGES values); the first cue that matches wins, in this order
STAGE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "reversal",
        (
            "reverses",
            "reversed",
            "withdraws",
            "withdrawn",
            "rolls back",
            "rolled back",
            "scraps",
            "scrapped",
            "cancels",
            "cancelled",
        ),
    ),
    ("suspension", ("suspends", "suspended", "halts", "halted")),
    ("delay", ("delays", "delayed", "postpones", "postponed", "deferred", "defers")),
    ("amendment", ("amends", "amended", "amendment", "revised", "revises")),
    (
        "implementation",
        ("takes effect", "comes into force", "implemented", "implements", "effective from", "enforced"),
    ),
    ("notification", ("notifies", "notified", "notification", "gazette", "sro issued")),
    (
        "approval",
        (
            "approves",
            "approved",
            "approval",
            "passes",
            "passed",
            "clears",
            "cleared",
            "signs",
            "signed",
            "ratifies",
        ),
    ),
    ("committee_recommendation", ("recommends", "recommended", "recommendation")),
    ("consultation", ("consultation", "seeks comments", "seeks input", "stakeholders")),
    (
        "proposal",
        (
            "proposes",
            "proposed",
            "proposal",
            "plans",
            "planned",
            "seeks",
            "moves to",
            "to introduce",
            "draft",
        ),
    ),
    ("discussion", ("mulls", "considers", "considering", "discusses", "talks", "weighs", "mulling")),
    (
        "rumour",
        ("reportedly", "sources say", "sources said", "rumour", "rumor", "speculation", "unconfirmed"),
    ),
)
DENIAL = (
    "denies",
    "denied",
    "refutes",
    "rejects reports",
    "no plan",
    "no plans",
    "dismisses reports",
    "baseless",
    "fake news",
    "clarifies",
)
OPINION = ("opinion", "editorial", "op-ed", "column", "comment:", "analysis:", "viewpoint")
PREDICTION = ("likely", "expected to", "may", "could", "forecast", "projected", "set to", "poised")

# non-company entities: exact phrases only (ENTITY_TYPES values), canonical name
ENTITIES: dict[str, tuple[tuple[str, str], ...]] = {
    "regulator": (
        ("sbp", "State Bank of Pakistan"),
        ("state bank", "State Bank of Pakistan"),
        ("secp", "SECP"),
        ("nepra", "NEPRA"),
        ("ogra", "OGRA"),
        ("pta", "PTA"),
        ("competition commission", "Competition Commission of Pakistan"),
        ("ccp", "Competition Commission of Pakistan"),
        ("psx", "Pakistan Stock Exchange"),
    ),
    "government_body": (
        ("fbr", "FBR"),
        ("finance ministry", "Ministry of Finance"),
        ("ministry of finance", "Ministry of Finance"),
        ("ecc", "ECC"),
        ("cabinet", "Federal Cabinet"),
        ("national assembly", "National Assembly"),
        ("senate", "Senate"),
        ("petroleum division", "Petroleum Division"),
        ("power division", "Power Division"),
        ("planning commission", "Planning Commission"),
        ("pbs", "Pakistan Bureau of Statistics"),
        ("supreme court", "Supreme Court"),
        ("nab", "NAB"),
    ),
    "organisation": (
        ("imf", "IMF"),
        ("world bank", "World Bank"),
        ("adb", "Asian Development Bank"),
        ("asian development bank", "Asian Development Bank"),
        ("opec", "OPEC"),
        ("moody's", "Moody's"),
        ("moodys", "Moody's"),
        ("fitch", "Fitch"),
        ("fatf", "FATF"),
    ),
    "country": (
        ("pakistan", "Pakistan"),
        ("china", "China"),
        ("india", "India"),
        ("iran", "Iran"),
        ("afghanistan", "Afghanistan"),
        ("saudi arabia", "Saudi Arabia"),
        ("uae", "UAE"),
        ("united states", "United States"),
        ("qatar", "Qatar"),
        ("russia", "Russia"),
        ("israel", "Israel"),
        ("turkey", "Turkey"),
        ("bangladesh", "Bangladesh"),
        ("uk", "United Kingdom"),
    ),
    "commodity": (
        ("crude", "crude oil"),
        ("brent", "Brent crude"),
        ("oil", "oil"),
        ("petrol", "petrol"),
        ("diesel", "diesel"),
        ("lng", "LNG"),
        ("lpg", "LPG"),
        ("gas", "natural gas"),
        ("gold", "gold"),
        ("coal", "coal"),
        ("urea", "urea"),
        ("wheat", "wheat"),
        ("cotton", "cotton"),
        ("sugar", "sugar"),
        ("steel", "steel"),
        ("copper", "copper"),
    ),
    "indicator": (
        ("policy rate", "policy rate"),
        ("interest rate", "interest rate"),
        ("kibor", "KIBOR"),
        ("inflation", "inflation"),
        ("cpi", "CPI"),
        ("gdp", "GDP"),
        ("current account", "current account"),
        ("remittances", "remittances"),
        ("reserves", "FX reserves"),
        ("rupee", "PKR"),
        ("pkr", "PKR"),
        ("dollar", "USD"),
        ("exchange rate", "exchange rate"),
        ("t-bills", "T-bill yields"),
        ("t-bill", "T-bill yields"),
        ("trade deficit", "trade deficit"),
        ("kse-100", "KSE-100"),
        ("kse 100", "KSE-100"),
        ("kse100", "KSE-100"),
        ("circular debt", "circular debt"),
    ),
}
# indirect, contextual entities implied by an explicit mention (relation = context, never a company)
IMPLIED: dict[str, tuple[str, str]] = {
    "NEPRA": ("indicator", "electricity tariff"),
    "OGRA": ("commodity", "petroleum products"),
    "State Bank of Pakistan": ("indicator", "policy rate"),
    "FBR": ("indicator", "tax revenue"),
    "OPEC": ("commodity", "crude oil"),
    "Brent crude": ("indicator", "international oil price"),
}
# company-like names that may not be in the company master (kept visible as unresolved, never assigned)
_COMPANY_LIKE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.\-]*\s){1,4}(?:Limited|Ltd\.?|Corporation|Corp\.?|Company|"
    r"Industries|Mills|Holdings|Group|Bank))\b"
)


def company_like_mentions(title: str) -> list[str]:
    """Capitalised names ending in a company suffix; known non-company entities (State Bank) excluded."""
    out = []
    known = [p for pairs in ENTITIES.values() for p, _ in pairs]
    for m in _COMPANY_LIKE.finditer(title or ""):
        name = m.group(1).strip()
        if not any(has(norm(name), k) for k in known if " " in k):
            out.append(name)
    return out


# "US" only as an upper-case token (never the word "us")
_US = re.compile(r"(?<![A-Za-z])U\.?S\.?(?![A-Za-z])")


@dataclass
class Classification:
    primary_type: str = "other"
    secondary_types: list[str] = field(default_factory=list)
    type_evidence: dict[str, list[str]] = field(default_factory=dict)
    stage: str | None = None  # None: no stage cue in the headline
    stage_evidence: str | None = None
    denial: list[str] = field(default_factory=list)
    claim_nature: str = (
        "news_report"  # existing claim types: news_report | rumour | personal_opinion | prediction
    )
    figures_with_units: list[str] = field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


def classify(title: str, *, company_mentioned: bool = False) -> Classification:
    n = norm(title)
    c = Classification()
    for etype, subjects, contexts, needs_company in RULES:
        subj = _hits(n, subjects)
        if not subj:
            continue
        ctx = _hits(n, contexts) if contexts else []
        if contexts and not ctx:
            continue
        if needs_company and not company_mentioned:
            continue
        c.type_evidence.setdefault(etype, []).extend(subj + [f"context:{x}" for x in ctx])
    matched = list(c.type_evidence)
    if matched:
        c.primary_type, c.secondary_types = matched[0], matched[1:]
    else:
        c.needs_review = True
        c.review_reasons.append("no contextual classification rule matched")
    for stage, cues in STAGE_CUES:
        hit = _hits(n, cues)
        if hit:
            c.stage, c.stage_evidence = stage, hit[0]
            break
    c.denial = _hits(n, DENIAL)
    rumour_cues = dict(STAGE_CUES)["rumour"]
    if _hits(n, OPINION):
        c.claim_nature = "personal_opinion"
    elif c.stage == "rumour" or _hits(n, rumour_cues):
        c.claim_nature = "rumour"
    elif _hits(n, PREDICTION):
        c.claim_nature = "prediction"
    c.figures_with_units = [m.group(0).strip() for m in _UNIT.finditer(title or "")]
    if c.primary_type not in schema.EVENT_TYPES or (c.stage and c.stage not in schema.STATUS_STAGES):
        raise RuntimeError("rule table uses a value outside engines/schema.py")  # programming error
    return c


def entity_mentions(title: str, sectors: list[str] | None = None) -> list[dict]:
    """Non-company entities: exact phrases, with relation 'direct'; implied ones with relation 'context'."""
    n = norm(title)
    out, seen = [], set()
    for etype, pairs in ENTITIES.items():
        for phrase, canonical in pairs:
            if has(n, phrase) and (etype, canonical) not in seen:
                if etype == "commodity" and canonical == "oil" and ("commodity", "crude oil") in seen:
                    continue
                seen.add((etype, canonical))
                out.append(
                    {"entity_type": etype, "name": canonical, "relation": "direct", "evidence": phrase}
                )
    if _US.search(title or "") and ("country", "United States") not in seen:
        seen.add(("country", "United States"))
        out.append(
            {"entity_type": "country", "name": "United States", "relation": "direct", "evidence": "US"}
        )
    for sector in sectors or []:
        if has(n, sector):
            out.append(
                {"entity_type": "sector", "name": sector, "relation": "direct", "evidence": sector.lower()}
            )
    for e in list(out):
        imp = IMPLIED.get(e["name"])
        if imp and (imp[0], imp[1]) not in seen:
            seen.add(imp)
            out.append(
                {
                    "entity_type": imp[0],
                    "name": imp[1],
                    "relation": "context",
                    "evidence": f"implied by {e['name']}",
                }
            )
    if any(e["entity_type"] not in schema.ENTITY_TYPES for e in out):
        raise RuntimeError("entity table uses a type outside engines/schema.py")  # programming error
    return out
