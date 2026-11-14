"""Insider transactions: the record model and its de-duplication. Built now; the payload mapping is pending.

An insider transaction is a distinct record linked to a company. Its identity is (symbol, insider, date,
action), so one transaction never appears twice. A record must carry every field below: a missing field
raises, and nothing is guessed from a page. Values are kept as Investify states them (price or value is
verbatim text).

The mapping from Investify's insider payload to these fields needs one fetched sample of an insider page,
taken inside the trading window. Until then no insider record is produced from a live page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

ACTIONS = ("buy", "sell", "other")
REQUIRED = ("symbol", "insider_name", "role", "action", "date", "shares", "price_or_value",
            "source_external_id")


@dataclass(frozen=True)
class InsiderTransaction:
    symbol: str
    insider_name: str
    role: str
    action: str  # buy | sell | other, as Investify states it
    date: str  # YYYY-MM-DD
    shares: int | None
    price_or_value: str | None  # verbatim text, if stated
    source_external_id: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.symbol, self.insider_name.strip().casefold(), self.date, self.action)


def transaction(fields: dict) -> InsiderTransaction:
    """Build a record from explicit fields only. A missing field, or an unknown action, is an error."""
    missing = [k for k in REQUIRED if k not in fields]
    if missing:
        raise ValueError(f"insider transaction is missing {missing}; nothing is guessed")
    if fields["action"] not in ACTIONS:
        raise ValueError(f"unknown insider action {fields['action']!r}")
    _date.fromisoformat(fields["date"])  # raises if malformed
    return InsiderTransaction(**{k: fields[k] for k in REQUIRED})


def dedupe(records: list[InsiderTransaction]) -> list[InsiderTransaction]:
    """Keep the first record for each (symbol, insider, date, action)."""
    seen: set[tuple[str, str, str, str]] = set()
    out = []
    for r in records:
        if r.key in seen:
            continue
        seen.add(r.key)
        out.append(r)
    return out
