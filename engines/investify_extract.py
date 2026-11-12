"""Structured-field extractors for Investify company pages.

Covers profile, competitors, fundamentals and announcements.

Pure functions: they take a page body (bytes or str) and return plain dicts. They never store anything and
never return the raw body. Investify renders these pages with Next.js. Where a field exists only as rendered
text, the extractor reads the labelled text (label-based parsing); where a per-symbol record exists in the
embedded flight payload (for example the sector of each listed company), it reads that record.

Numbers are returned as a value in base units plus the printed text, so a reader can check them:
  "Rs 268.23B" -> {"text": "Rs 268.23B", "value": 268230000000.0}

Company descriptions are NOT extracted: they may be Investify-generated text, which the owner has excluded.
"""

from __future__ import annotations

import html as htmlmod
import json
import re
from decimal import Decimal
from typing import Any

_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_MULT = {"": 1, "K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12}
_NUM = r"[\d][\d,]*(?:\.\d+)?[KMBT]?"


def _text_of(body: bytes | str) -> str:
    raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    return _SPACE.sub(" ", htmlmod.unescape(_TAGS.sub(" ", raw))).strip()


def _flight(body: bytes | str) -> str:
    raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    chunks = _FLIGHT.findall(raw)
    return "".join(json.loads('"' + c + '"') for c in chunks)


def amount(token: str) -> dict[str, Any]:
    """'Rs 268.23B' / '1.3B' / '972.87M' / '206.78' -> {text, value}. Keeps the printed text."""
    m = re.search(r"(" + _NUM + r")", token)
    if not m:
        return {"text": token, "value": None}
    num = m.group(1)
    unit = num[-1] if num[-1] in _MULT and num[-1] != "" and not num[-1].isdigit() else ""
    digits = num[:-1] if unit else num
    value = Decimal(digits.replace(",", "")) * _MULT[unit]
    return {"text": token.strip(), "value": float(value)}


def sector_for(body: bytes | str, symbol: str) -> str | None:
    """The sector printed for this symbol in the page's embedded company index (structured, not rendered)."""
    pattern = (r'"' + re.escape(symbol) + r'":\{"symbol":"' + re.escape(symbol)
               + r'","name":"[^"]*","logo":"[^"]*","sector":"([^"]+)"\}')
    m = re.search(pattern, _flight(body))
    return m.group(1) if m else None


def parse_profile(body: bytes | str, symbol: str) -> dict[str, Any]:
    text = _text_of(body)
    out: dict[str, Any] = {"symbol": symbol, "sector": sector_for(body, symbol)}
    m = re.search(r"Leadership Chairperson (.+?) CEO (.+?) Company Secretary (.+?) Market Structure", text)
    if m:
        out["leadership"] = {"chairperson": m.group(1).strip(), "ceo": m.group(2).strip(),
                             "company_secretary": m.group(3).strip()}
    m = re.search(r"Market Cap (Rs " + _NUM + r") Price (" + _NUM + r") Total Shares (" + _NUM
                  + r") Free Float (" + _NUM + r")", text)
    if m:
        out["market_structure"] = {"market_cap": amount(m.group(1)), "price": amount(m.group(2)),
                                   "total_shares": amount(m.group(3)),
                                   "free_float_shares": amount(m.group(4))}
    m = re.search(r"(\d+)% free Locked / strategic (\d+)% (" + _NUM
                  + r") Free float (\d+)% (" + _NUM + r")", text)
    if m:
        out["share_float_split"] = {
            "free_float_pct": float(m.group(1)), "locked_pct": float(m.group(2)),
            "locked_shares": amount(m.group(3)), "free_float_pct_check": float(m.group(4)),
            "free_float_shares": amount(m.group(5)),
        }
    m = re.search(r"Registered Address (.+?) Website (\S+)", text)
    if m:
        out["registered_address"] = m.group(1).strip()
        out["website"] = m.group(2).strip()
    return out
