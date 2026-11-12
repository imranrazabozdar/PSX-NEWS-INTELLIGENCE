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
from datetime import timezone
from decimal import Decimal
from typing import Any

from engines import investify_taxonomy as taxonomy

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
    sector = out.get("sector")
    if sector and f"PSX {sector} " in text:
        start = text.index(f"PSX {sector} ") + len(f"PSX {sector} ")
        end = text.find(" Leadership", start)
        if end > start:
            out["description"] = text[start:end].strip()
    m = re.search(r"Registered Address (.+?) Website (\S+)", text)
    if m:
        out["registered_address"] = m.group(1).strip()
        out["website"] = m.group(2).strip()
    return out


# ---------------------------------------------------------------- announcements (structured records)

_CATEGORY = {
    "financial_result": "financial_results",
    "report_transmission": "report_transmission",
    "board_meeting": "board_meeting",
    "dividend": "dividend",
    "mna_public_offer": "merger_acquisition",
    "agm_egm": "agm_egm",
}
QUALIFYING_CATEGORIES = frozenset({"financial_results", "report_transmission"})


def _object_at(flight: str, index: int) -> dict[str, Any] | None:
    start = flight.rfind("{", 0, index)
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(flight, start)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_announcements(body: bytes | str, symbol: str) -> dict[str, Any]:
    """Announcement metadata for one company page.

    Investify's headline, summary and key findings are generated text and are NOT returned. The PSX title,
    date, classification and document links are."""
    flight = _flight(body)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'"externalId":"([^"]+)","symbol":"' + re.escape(symbol) + '"', flight):
        if m.group(1) in seen:
            continue
        obj = _object_at(flight, m.start())
        if not obj or obj.get("symbol") != symbol:
            continue
        seen.add(m.group(1))
        cls = obj.get("classification") or {}
        sub = cls.get("subType")
        items.append({
            "external_id": obj.get("externalId"),
            "announced_at_utc": obj.get("announcedAt"),
            "title": obj.get("title"),
            "event_type": cls.get("eventType"),
            "sub_type": sub,
            "category": _CATEGORY.get(sub, "other"),
            "taxonomy": taxonomy.classify(cls.get("eventType"), sub),
            "materiality": cls.get("materiality"),
            "sentiment": cls.get("sentiment"),
            "pdf_url": obj.get("pdfUrl"),
            "image_url": obj.get("imageUrl"),
        })
    page = re.search(r"Page (\d+) of (\d+)", _text_of(body))
    return {
        "symbol": symbol,
        "page": int(page.group(1)) if page else None,
        "pages_total": int(page.group(2)) if page else None,
        "items": items,
    }


def to_announcement_records(parsed: dict[str, Any], retrieved_at_utc: str) -> list[Any]:
    """Build the announcement records the trigger queue reads. Metadata only."""
    from datetime import datetime, timedelta

    from engines import investify_collector as ic
    pkt = timezone(timedelta(hours=5))
    records = []
    for it in parsed["items"]:
        at = datetime.fromisoformat(it["announced_at_utc"].replace("Z", "+00:00"))
        at_utc = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        source_url = f"https://www.investify.pk/company/{parsed['symbol']}/announcements#{it['external_id']}"
        records.append(ic.AnnouncementRecord(
            symbol=parsed["symbol"], company_name="", announced_at_utc=at_utc,
            announced_on_pkt=at.astimezone(pkt).date().isoformat(), title=it["title"] or "",
            investify_label=it["sub_type"] or "", category=it["category"],
            sentiment_label=it["sentiment"] or "",
            source="investify.pk", source_url=source_url, pdf_url=it["pdf_url"],
            pdf_access="gated_dps" if it["pdf_url"] and "dps.psx.com.pk" in it["pdf_url"] else "none",
            retrieved_at_utc=retrieved_at_utc,
            content_sha256=ic._content_hash(parsed["symbol"], at_utc, it["title"] or "", source_url,
                                            it["pdf_url"]),
        ))
    return records


# ---------------------------------------------------------------- fundamentals (metric cards)

_VALUE = r"(?:Rs\. [\d,.]+[BMK]?|-?[\d,.]+%|[\d.]+ : [\d.]+|-?[\d,.]+[BMKx]?)"
_PERIOD = r"(?:BASED ON [A-Z0-9 ]+?|CURRENT|\d{4} FY|\d{4} [1-4]Q|LATEST[A-Z ]*?)"
_CARD = re.compile(
    r"(?P<title>[A-Z][A-Za-z&/ .'\-]{2,50}?) (?P=title) (?P<body>.+?) (?P<value>" + _VALUE + r") (?P<period>"
    + _PERIOD + r")(?: (?P<sent>positive|negative|neutral|mixed))?(?= [A-Z]|$)")


def _metric_value(token: str) -> dict[str, Any]:
    """Number and unit of a metric value. Exact decimal arithmetic; the printed text is kept."""
    t = token.strip()
    if t.startswith("Rs."):
        out = amount(t)
        return {"text": t, "value": out["value"], "unit": "PKR"}
    if t.endswith("%"):
        return {"text": t, "value": float(Decimal(t[:-1].replace(",", ""))), "unit": "percent"}
    if " : " in t:
        num, den = t.split(" : ")
        return {"text": t, "value": float(Decimal(num)) / float(Decimal(den)), "unit": "ratio",
                "numerator": float(Decimal(num)), "denominator": float(Decimal(den))}
    if t[-1] in "BMK":
        return dict(amount(t), unit="number")
    if t.endswith("x"):
        return {"text": t, "value": float(Decimal(t[:-1].replace(",", ""))), "unit": "x"}
    return {"text": t, "value": float(Decimal(t.replace(",", ""))), "unit": "number"}


def parse_fundamentals(body: bytes | str, symbol: str) -> dict[str, Any]:
    """Every metric card on the page, generically (the catalog is not hardcoded). Each card keeps its label,
    the card's description text, the value (number and unit), the period basis verbatim and the sentiment."""
    text = _text_of(body)
    nav = text.find("Competitors")
    if nav >= 0:
        text = text[nav + len("Competitors"):]  # skip the page navigation, which repeats some labels
    metrics = []
    for m in _CARD.finditer(text):
        metrics.append({
            "label": m.group("title"),
            "description": m.group("body").strip(),
            "value": _metric_value(m.group("value")),
            "period_basis": m.group("period"),
            "sentiment": m.group("sent"),
        })
    return {"symbol": symbol, "metric_count": len(metrics), "metrics": metrics}


# ---------------------------------------------------------------- competitors (sector-derived)

# Investify's displayed peer tab curates to 14 companies; two same-sector companies are excluded by Investify.
# Recorded as an owner observation (2026-11-12), so the derived set can be read against the displayed one.
DISPLAYED_PEER_COUNT = 14
DISPLAYED_EXCLUDED_SAME_SECTOR = ("GEMMEL", "NGLEL")


def company_index(body: bytes | str) -> dict[str, dict[str, str]]:
    """Every listed company in the embedded index: symbol -> name and sector (structured, not rendered)."""
    pattern = (r'"([A-Z0-9&-]+)":\{"symbol":"\1","name":"([^"]*)","logo":"[^"]*",'
               r'"sector":"([^"]+)"\}')
    return {m.group(1): {"name": m.group(2), "sector": m.group(3)}
            for m in re.finditer(pattern, _flight(body))}


def parse_competitors(body: bytes | str, symbol: str) -> dict[str, Any]:
    """Peers = every listed company in the same sector, from the embedded index.

    Derived, not displayed: the peer cards render client-side. The derived set is a superset of the displayed
    tab by two."""
    index = company_index(body)
    me = index.get(symbol)
    if me is None:
        return {"symbol": symbol, "peer_source": "sector-derived", "sector": None, "peer_count": 0,
                "peers": []}
    peers = [{"ticker": t, "name": v["name"], "sector": v["sector"]}
             for t, v in sorted(index.items()) if v["sector"] == me["sector"] and t != symbol]
    return {
        "symbol": symbol,
        "peer_source": "sector-derived",
        "sector": me["sector"],
        "peer_count": len(peers),
        "same_sector_count": len(peers),
        "displayed_peer_count_reported": DISPLAYED_PEER_COUNT,
        "displayed_excluded_same_sector": list(DISPLAYED_EXCLUDED_SAME_SECTOR),
        "note": (f"Derived from the sector index: {len(peers)} same-sector companies. Investify's displayed "
                 f"peer tab curates to {DISPLAYED_PEER_COUNT}; the derived set is a superset by "
                 f"{len(peers) - DISPLAYED_PEER_COUNT}."),
        "peers": peers,
    }
