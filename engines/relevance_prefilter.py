"""Deterministic relevance pre-filter, run BEFORE any model call.

It saves model quota and raises signal-to-noise. No model is involved and every decision carries
its reasons, so each skip or pass can be audited. Entities come from the company master
(`company_identifiers`, `companies`, `company_aliases`) and the owner's watchlist; keyword
groups, weights and thresholds come from the versioned file `config/relevance_rules.json`.
Bump the rules `version` whenever a weight changes.

Score = entity points + the highest-weight matched term of each keyword group. An item passes
when the score reaches the threshold, with these guards:
* tickers match only as UPPERCASE whole words, and one entity hit is enough (tickers do not stack);
* company names match as whole phrases of at least two words and eight characters, after
  stripping legal suffixes;
* an ambiguous ticker (a ticker that is also a common word or an acronym) counts only when another
  substantive signal corroborates it;
* context-only signals (geography, small source bonuses) never make an item relevant alone.

Adapted under the owner-approved port recorded in ADR-0001 (2026-11-09).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from database.connection import Database

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "relevance_rules.json"
_SUFFIX = re.compile(r"\b(limited|ltd|company|co|corporation|corp|pvt|private|plc|inc)\b\.?", re.I)
_TICKER = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,15})(?![A-Za-z0-9])")
_CONTEXT_ONLY_GROUPS = ("geo", "foreign_noise")


def load_rules(path: Path | str = RULES_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalise(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]+", " ", (text or "").lower())).strip()


def company_phrase(legal_name: str | None) -> str | None:
    """'The Hub Power Company Limited' -> 'hub power'. Single-word or very short results are
    dropped because they are too ambiguous to match on their own."""
    name = normalise(_SUFFIX.sub(" ", legal_name or ""))
    name = re.sub(r"^the ", "", name).strip()
    return name if len(name.split()) >= 2 and len(name) >= 8 else None


class RelevancePrefilter:
    def __init__(self, tickers: Iterable[str] = (), names: Iterable[str] = (),
                 watchlist: Iterable[str] = (), rules: dict[str, Any] | None = None) -> None:
        self.rules = rules or load_rules()
        self.version: str = self.rules["version"]
        self.threshold: int = self.rules["threshold"]
        self.tickers = {t.upper() for t in tickers}
        self.watch = {t.upper() for t in watchlist}
        self.names = {n for n in names if n}
        self.ambiguous = {t.upper() for t in self.rules.get("ambiguous_tickers", [])}
        self.source_bonus: dict[str, int] = self.rules.get("source_bonus", {})
        self._keywords = {
            group: [(term, weight, re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"))
                    for term, weight in terms.items()]
            for group, terms in self.rules["groups"].items()}

    @classmethod
    def from_db(cls, db: Database, rules: dict[str, Any] | None = None) -> RelevancePrefilter:
        """Build from the company master: current tickers, legal names and short-name aliases,
        and the enabled ticker watchlist. Delisted and historical identifiers are not used."""
        tickers = [r["value"] for r in db.execute(
            "SELECT value FROM company_identifiers WHERE id_type = 'psx_ticker' AND valid_to IS NULL")]
        watch = [r["value"] for r in db.execute(
            "SELECT value FROM user_watchlist WHERE item_type = 'ticker' AND enabled = 1")]
        names: set[str] = set()
        for row in db.execute(
                "SELECT legal_name AS n FROM companies WHERE listing_status = 'listed' "
                "UNION SELECT a.alias AS n FROM company_aliases a JOIN companies c USING (company_id) "
                "WHERE c.listing_status = 'listed' AND a.alias_type IN ('legal_name', 'short_name') "
                "AND a.valid_to IS NULL"):
            phrase = company_phrase(row["n"])
            if phrase:
                names.add(phrase)
        return cls(tickers, names, watch, rules)

    def score(self, text: str, source_id: str | None = None) -> dict[str, Any]:
        points = self.rules["entity_points"]
        reasons: list[str] = []
        total = 0
        ambiguous_hit: str | None = None
        for ticker in sorted(set(_TICKER.findall(text or ""))):
            if ticker not in self.tickers:
                continue
            if ticker in self.ambiguous:
                ambiguous_hit = ticker  # counts only if something else corroborates it
                continue
            total += points["ticker"]
            reasons.append(f"ticker:{ticker}")
            if ticker in self.watch:
                total += points["watchlist_bonus"]
                reasons.append(f"watchlist:{ticker}")
            break  # one entity hit is enough; tickers do not stack
        low = normalise(text)
        corroborated = False
        for name in sorted(self.names, key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", low):
                total += points["company_name"]
                reasons.append(f"company:{name}")
                corroborated = True
                break
        for group, terms in self._keywords.items():
            best = max(((w, t) for t, w, rx in terms if rx.search(low)), default=None)
            if best:
                total += best[0]
                reasons.append(f"{group}:{best[1]}({best[0]})")
                corroborated = corroborated or (group not in _CONTEXT_ONLY_GROUPS and best[0] > 0)
        if ambiguous_hit and corroborated:
            total += points["ticker"]
            reasons.append(f"ticker(ambiguous, corroborated):{ambiguous_hit}")
        elif ambiguous_hit:
            reasons.append(f"ambiguous ticker {ambiguous_hit} ignored: no corroboration")
        bonus = self.source_bonus.get(source_id or "", 0)
        if bonus:
            total += bonus
            reasons.append(f"source:{source_id}(+{bonus})")
        substantive = corroborated or bonus >= 3 or any(r.startswith(("ticker:", "ticker(")) for r in reasons)
        if not substantive:  # context-only signals never make an item relevant on their own
            reasons.append("no substantive signal: context-only")
            total = 0
        return {"score": total, "pass": total >= self.threshold, "reasons": reasons,
                "version": self.version}
