"""Deterministic tagging of collected news headlines: companies, sectors, themes, market-moving flags.

Works only from stored metadata: headline, link, publisher and timestamps. Article text is never
stored. Every tag carries the exact matched text as evidence, and nothing is inferred beyond it:
* Companies: a PSX ticker written in capitals, or an exact company-master name or short name, both
  confirmed with engines.entity_resolution.resolve. Ambiguous or unresolved mentions are never
  assigned to a company.
* Sectors come from the resolved company's PSX classification, never guessed from the headline.
* Themes and "potentially market-moving" flags are keyword matches. They are labelled as such and are
  never presented as verified impact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from database.canonical import normalise_name
from engines.entity_resolution import resolve

THEMES: dict[str, tuple[str, ...]] = {
    "monetary_policy": (
        "sbp",
        "state bank",
        "policy rate",
        "interest rate",
        "monetary policy",
        "inflation",
        "cpi",
        "t-bill",
        "t-bills",
        "kibor",
    ),
    "fiscal_and_tax": (
        "budget",
        "tax",
        "taxes",
        "fbr",
        "imf",
        "fiscal",
        "deficit",
        "revenue",
        "customs duty",
        "levy",
        "subsidy",
    ),
    "energy": (
        "oil",
        "petrol",
        "petroleum",
        "diesel",
        "lng",
        "gas",
        "power",
        "electricity",
        "nepra",
        "ogra",
        "circular debt",
        "refinery",
        "crude",
        "opec",
        "energy",
        "solar",
    ),
    "banking_and_finance": (
        "bank",
        "banks",
        "banking",
        "loan",
        "loans",
        "deposit",
        "deposits",
        "islamic banking",
        "microfinance",
        "secp",
        "insurance",
    ),
    "technology_and_it": (
        "it exports",
        "software",
        "technology",
        "tech",
        "telecom",
        "digital",
        "startup",
        "pta",
        "internet",
        "fintech",
    ),
    "psx_market": (
        "psx",
        "kse-100",
        "kse100",
        "kse 100",
        "stock exchange",
        "shares",
        "bourse",
        "stocks",
        "equities",
    ),
    "external_sector": (
        "current account",
        "remittances",
        "exports",
        "imports",
        "trade deficit",
        "reserves",
        "rupee",
        "exchange rate",
        "dollar",
    ),
    "politics_and_geopolitics": (
        "election",
        "by-election",
        "by-polls",
        "parliament",
        "senate",
        "national assembly",
        "india",
        "afghanistan",
        "iran",
        "china",
        "war",
        "sanctions",
        "ceasefire",
        "border",
        "protest",
    ),
    "corporate_results_and_actions": (
        "dividend",
        "profit",
        "earnings",
        "results",
        "merger",
        "acquisition",
        "board meeting",
        "rights issue",
        "delisting",
        "ipo",
        "bonus shares",
    ),
}
MARKET_MOVING: tuple[str, ...] = (
    "policy rate",
    "rate cut",
    "rate hike",
    "imf tranche",
    "imf programme",
    "imf program",
    "imf review",
    "default",
    "devaluation",
    "circular debt",
    "petrol price",
    "dividend",
    "merger",
    "acquisition",
    "suspension",
    "delisting",
    "record high",
    "record low",
    "crash",
    "plunge",
    "surge",
    "downgrade",
    "upgrade",
    "sanctions",
    "war",
    "ceasefire",
    "budget",
    "tariff",
)
_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")
_TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")


@dataclass
class Tagging:
    companies: list[dict] = field(default_factory=list)  # {ticker, company_id, legal_name, sector, evidence,
    #                                                           confidence, needs_review}
    unresolved: list[dict] = field(default_factory=list)  # {mention, status, reason}
    themes: list[dict] = field(default_factory=list)  # {theme, evidence}
    market_moving: list[str] = field(default_factory=list)  # matched terms (keyword match, unverified)

    @property
    def potentially_market_moving(self) -> bool:
        return bool(self.market_moving)


def _norm(text: str) -> str:
    return " " + " ".join(_WORD.findall(text.casefold())) + " "


def _contains(norm_text: str, phrase: str) -> bool:
    return f" {' '.join(_WORD.findall(phrase.casefold()))} " in norm_text


class NewsTagger:
    """Loads the company master once; tags headlines without further database writes."""

    def __init__(self, db):
        self.db = db
        self.tickers = {
            r["value"]
            for r in db.execute("SELECT DISTINCT value FROM company_identifiers WHERE id_type = 'psx_ticker'")
        }
        # exact multi-word names only: single short words ("engro", "lucky") are too ambiguous for headlines
        self.aliases = sorted(
            {
                r["alias_normalized"]
                for r in db.execute(
                    "SELECT alias_normalized FROM company_aliases "
                    "WHERE alias_type IN ('legal_name','short_name') "
                    "AND length(alias_normalized) >= 6 AND alias_normalized LIKE '% %'"
                )
            },
            key=len,
            reverse=True,
        )
        self.sectors = {
            r["company_id"]: r["name"]
            for r in db.execute(
                "SELECT cc.company_id, s.name FROM company_classifications cc "
                "JOIN sectors s USING(sector_id) "
                "WHERE cc.valid_to IS NULL"
            )
        }
        self.tickers_by_company = {
            r["company_id"]: r["value"]
            for r in db.execute(
                "SELECT company_id, value FROM company_identifiers "
                "WHERE id_type = 'psx_ticker' AND valid_to IS NULL"
            )
        }

    def tag(self, title: str, *, as_of: str | None = None) -> Tagging:
        out = Tagging()
        if not title:
            return out
        norm = _norm(title)
        mentions: list[tuple[str, str]] = [
            (t, f"ticker '{t}'") for t in dict.fromkeys(_TICKER_TOKEN.findall(title)) if t in self.tickers
        ]
        plain = normalise_name(title)
        for alias in self.aliases:
            if f" {alias} " in f" {plain} ":
                mentions.append((alias, f"name '{alias}'"))
        seen = set()
        for mention, evidence in mentions:
            res = resolve(self.db, mention, as_of=as_of)
            if res.status == "resolved" and res.company:
                cid = res.company["company_id"]
                if cid in seen:
                    continue
                seen.add(cid)
                out.companies.append(
                    {
                        "company_id": cid,
                        "ticker": self.tickers_by_company.get(cid),
                        "legal_name": res.company.get("legal_name"),
                        "sector": self.sectors.get(cid),
                        "evidence": evidence,
                        "method": res.method,
                        "confidence": res.confidence,
                        "needs_review": res.needs_review,
                    }
                )
            else:
                out.unresolved.append(
                    {"mention": mention, "status": res.status, "reason": "; ".join(res.reasons)[:200]}
                )
        for theme, words in THEMES.items():
            hits = [w for w in words if _contains(norm, w)]
            if hits:
                out.themes.append({"theme": theme, "evidence": hits})
        out.market_moving = [w for w in MARKET_MOVING if _contains(norm, w)]
        return out


def recent_news(
    db, *, limit: int = 200, source_types: tuple[str, ...] = ("news_media", "government")
) -> list[dict]:
    """Most recent collected headlines with provenance (metadata only)."""
    marks = ",".join("?" * len(source_types))
    return db.execute(
        f"""SELECT si.source_item_id, si.source_id, s.name AS publisher, si.title, si.canonical_url AS url,
                   si.published_at_utc, si.collected_at_utc, s.terms_status, s.retention_mode
            FROM source_items si JOIN sources s USING(source_id)
            WHERE s.source_type IN ({marks}) AND si.title IS NOT NULL
            ORDER BY COALESCE(si.published_at_utc, si.collected_at_utc) DESC LIMIT ?""",  # noqa: S608
        (*source_types, limit),
    )
