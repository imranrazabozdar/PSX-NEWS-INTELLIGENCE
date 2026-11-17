"""The names a company is known by: its official name and every alias on file. Used to tell which side of a
deal a company is on. Reads the two committed name files; no network, no database."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _index() -> dict[str, list[str]]:
    listing = json.loads((ROOT / "docs/research/psx_listed_companies.json").read_text("utf-8"))
    aliases = json.loads((ROOT / "docs/research/arn/entity_aliases.json").read_text("utf-8"))["aliases"]
    out: dict[str, list[str]] = {}
    for symbol, name in listing["companies"].items():
        out.setdefault(symbol, []).append(name)
        for suffix in (" Limited", " Ltd", " Ltd."):
            if name.endswith(suffix):
                out[symbol].append(name[: -len(suffix)])
    for phrase, symbol in aliases.items():
        out.setdefault(symbol, []).append(phrase)
    return {s: sorted(set(v)) for s, v in out.items()}


def names_for(symbol: str) -> list[str]:
    return list(_index().get(symbol, []))


@lru_cache(maxsize=1)
def _official() -> dict[str, str]:
    listing = json.loads((ROOT / "docs/research/psx_listed_companies.json").read_text("utf-8"))
    return dict(listing["companies"])


def official_name(symbol: str) -> str:
    """The listed company name ('' when the symbol is not in the committed listing)."""
    return _official().get(symbol, "")
