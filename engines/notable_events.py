"""Notable-events thread for a company: categorized disclosures and insider records, tagged by verification.

VERIFIED: a company or exchange disclosure (an announcement on the PSX record, or a stored insider
record). The fact that the disclosure exists is verified. Its content is read from the disclosure,
not from commentary.
UNVERIFIED: commentary (news, analyst takes, Investify's generated summaries). Commentary is never routed as
VERIFIED, and Investify's generated headline or summary text is never routed at all.

Pure functions: no fetch, no write. The thread is built from stored records and returned for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines import investify_insiders as ins
from engines import investify_taxonomy as tax

VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
ROUTED_GROUPS = ("Financials", "Material", "Actions", "Insiders", "Meetings", "Briefings")
SOURCE = "investify.pk"


@dataclass(frozen=True)
class NotableEvent:
    symbol: str
    event_date: str  # YYYY-MM-DD
    group: str  # the taxonomy group, or "Commentary"
    kind: str  # announcement | insider_transaction | image_disclosure | commentary
    title: str
    verification: str  # VERIFIED | UNVERIFIED
    source: str
    source_external_id: str | None
    detail: str | None = None  # structured detail only; never generated text


def from_announcements(symbol: str, items: list[dict[str, Any]]) -> list[NotableEvent]:
    out = []
    for it in items:
        group = tax.classify(it.get("event_type"), it.get("sub_type"))
        if group not in ROUTED_GROUPS:
            continue  # Other is kept on the record, not routed to the thread
        out.append(NotableEvent(
            symbol=symbol, event_date=it["announced_at_utc"][:10], group=group,
            kind="announcement", title=it.get("title") or "", verification=VERIFIED, source=SOURCE,
            source_external_id=it.get("external_id"), detail=it.get("sub_type")))
    return out


def from_insiders(records: list[ins.InsiderTransaction]) -> list[NotableEvent]:
    return [NotableEvent(
        symbol=r.symbol, event_date=r.date, group="Insiders", kind="insider_transaction",
        title=f"{r.insider_name} ({r.role}): {r.action}", verification=VERIFIED, source=SOURCE,
        source_external_id=r.source_external_id,
        detail=f"shares={r.shares}; price_or_value={r.price_or_value}") for r in ins.dedupe(records)]


def from_image_disclosure(symbol: str, date: str, external_id: str, title: str) -> NotableEvent:
    """A disclosure whose content is an image and not machine-readable. Only its existence is routed."""
    return NotableEvent(symbol=symbol, event_date=date, group="Insiders", kind="image_disclosure",
                        title=title,
                        verification=VERIFIED, source=SOURCE, source_external_id=external_id,
                        detail="machine_readable=false; fields not read")


def from_commentary(symbol: str, items: list[dict[str, Any]]) -> list[NotableEvent]:
    """Commentary is UNVERIFIED by construction. No commentary source is connected yet, so this is empty."""
    return [NotableEvent(symbol=symbol, event_date=i["date"], group="Commentary", kind="commentary",
                         title=i["title"], verification=UNVERIFIED,
                         source=i.get("source", "unknown"), source_external_id=i.get("external_id"))
            for i in items]


def thread(events: list[NotableEvent]) -> list[NotableEvent]:
    """Newest first. A source record appears once."""
    seen: set[tuple[str, str | None]] = set()
    out = []
    for e in sorted(events, key=lambda e: e.event_date, reverse=True):
        key = (e.kind, e.source_external_id)
        if e.source_external_id and key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out
