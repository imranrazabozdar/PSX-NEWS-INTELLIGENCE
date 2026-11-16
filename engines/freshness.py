"""Freshness of a stored fact, and which macro factors a piece of text is about. Pure Python, no model.

A view from two years ago must not weigh the same as one from last month, so every fact shown to the
council carries its age. Factor tags are keyword matches only: they rank which facts are most relevant
to an event, they never invent a fact.
"""

from __future__ import annotations

import re
from datetime import date

BANDS = ((90, "current"), (365, "recent"), (730, "dated"))

FACTORS: dict[str, tuple[str, ...]] = {
    "interest_rate": ("policy rate", "interest rate", "sbp", "kibor", "monetary", "rate cut", "rate hike"),
    "exchange_rate": ("rupee", "exchange rate", "devaluation", "dollar", "pkr parity", "currency"),
    "inflation": ("inflation", "cpi", "price index"),
    "oil_energy": ("oil", "crude", "brent", "gas price", "lng", "furnace", "petrol", "diesel"),
    "power_tariff": ("electricity", "power tariff", "circular debt", "ipp", "capacity payment", "nepra"),
    "coal_fuel_cost": ("coal", "afghan coal", "fuel cost", "freight"),
    "imf_fiscal": ("imf", "budget", "tax", "taxation", "fbr", "levy", "subsidy", "fiscal",
                   "tariff duty"),
    "global_demand": ("export", "global demand", "china", "us tariff", "remittance"),
    "construction_cycle": ("cement", "construction", "housing", "psdp", "steel", "building"),
    "agri_cycle": ("wheat", "cotton", "sugar", "crop", "fertilizer", "urea", "dap"),
    "regulation": ("regulator", "secp", "ogra", "ban", "policy change", "approval"),
    "politics_security": ("election", "political", "security", "border", "protest"),
}


def label(source_date: str, today: date | None = None) -> str:
    """'current' | 'recent' | 'dated' | 'old' | 'undated' for a YYYY-MM-DD string."""
    try:
        age = ((today or date.today()) - date.fromisoformat(str(source_date)[:10])).days
    except ValueError:
        return "undated"
    for limit, name in BANDS:
        if age <= limit:
            return name
    return "old"


def age_text(source_date: str, today: date | None = None) -> str:
    tag = label(source_date, today)
    return f"{str(source_date)[:10]} [{tag}]" if tag != "undated" else f"{source_date} [undated]"


def _word_regex(word: str) -> str:
    """A keyword as a pattern. Longer words also match their endings ("taxation", "devaluations"); words
    under five letters must be whole words (a plural s is allowed), so "ban" does not match "bank"."""
    stem = re.escape(word)
    return rf"\b{stem}(?:s|es)?\b" if len(word.replace(" ", "")) < 5 else rf"\b{stem}"


def factors_in(text: str) -> set[str]:
    low = text.lower()
    return {name for name, words in FACTORS.items()
            if any(re.search(_word_regex(w), low) for w in words)}
