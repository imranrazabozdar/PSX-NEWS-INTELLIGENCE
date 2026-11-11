"""
document_router.py
==================

Pure (network-free) routing logic that decides WHERE each disclosed document
should be fetched from. Keeping this module side-effect free makes it trivially
unit-testable and keeps every fetch decision auditable.

Two tracks, as specified:

  Track.FLASH  -- lightweight PUCAR flash filings (< ~1 MB): dividend notices,
                  board-meeting outcomes, routine corporate actions.
  Track.HEAVY  -- audited annual / quarterly financial statements (15-30 MB).

Source preference, most-to-least desirable:

  1. OPEN_MIRROR   -- open investor broadcast channel (Pattern D). Preferred for
                      flash filings when a mirror URL is resolvable.
  2. CORPORATE_IR  -- the company's own IR portal (Pattern B). Required target
                      for heavy reports; these servers do not ASN-filter.
  3. EXCHANGE_EDGE -- dps.psx.com.pk canonical PDF. Last resort, flash-only,
                      and ONLY for a doc_id that came from the feed.

Hard rule enforced here: ``build_exchange_document_url`` will not fabricate an
id. There is deliberately no "next id" / enumeration helper -- the edge is only
ever addressed with ids the exchange itself disclosed.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from engines.psx_feed_parser import StatutoryAnnouncement

EXCHANGE_DOCUMENT_BASE = "https://dps.psx.com.pk/download/document"


class Track(enum.StrEnum):
    FLASH = "flash"
    HEAVY = "heavy"


class Source(enum.StrEnum):
    OPEN_MIRROR = "open_mirror"
    CORPORATE_IR = "corporate_ir"
    EXCHANGE_EDGE = "exchange_edge"
    UNRESOLVED = "unresolved"  # heavy report with no known IR base


# Category keywords that mark a heavy, full audited report BOOK (15-30 MB) that
# must leave the exchange edge and come from the company IR portal.
#
# Deliberately NARROW: quarterly-results PUCAR letterheads (1-3 pages, dividend
# + EPS figures) are statutory flash filings and MUST stay on Track.FLASH for
# real-time alerting, so "financial results" is intentionally NOT here.
# "quarterly account" is used (singular substring) so it also matches the plural
# "quarterly accounts".
_HEAVY_KEYWORDS = (
    "annual report",
    "annual audited",
    "quarterly account",
    "statement of accounts",
)


@dataclass(frozen=True)
class RouteDecision:
    track: Track
    source: Source
    symbol: str
    doc_id: int | None
    url: str | None
    # When True the caller must apply polite-fetch controls (rate limit,
    # robots.txt, honour 403/429) because the target is the protected edge.
    politeness_required: bool
    reason: str


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify_track(announcement: StatutoryAnnouncement) -> Track:
    haystack = f"{announcement.category or ''} {announcement.title or ''}".lower()
    if any(kw in haystack for kw in _HEAVY_KEYWORDS):
        return Track.HEAVY
    return Track.FLASH


def build_exchange_document_url(doc_id: int) -> str:
    """Return the canonical statutory PDF URL for a feed-sourced id.

    ``doc_id`` MUST originate from a parsed announcement. This function does no
    guessing; callers must never iterate ids to call it.
    """
    if isinstance(doc_id, bool) or not isinstance(doc_id, int) or doc_id < 1:
        raise ValueError("doc_id must be a positive integer disclosed by the feed")
    return f"{EXCHANGE_DOCUMENT_BASE}/{doc_id}.pdf"


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

# A mirror resolver maps an announcement to an open-channel URL, or None.
MirrorResolver = Callable[[StatutoryAnnouncement], str | None]


def route(
    announcement: StatutoryAnnouncement,
    ir_registry: Mapping[str, str],
    mirror_resolver: MirrorResolver | None = None,
) -> RouteDecision:
    """Decide the fetch target for one announcement.

    Parameters
    ----------
    ir_registry:
        ``symbol -> IR base URL`` (e.g. ``{"OGDC": "https://www.ogdcl.com/investor-relations"}``).
    mirror_resolver:
        Optional callable returning an open-channel URL for flash filings.
    """
    track = classify_track(announcement)
    symbol = announcement.symbol
    doc_id = announcement.doc_id

    if track is Track.HEAVY:
        ir_base = ir_registry.get(symbol)
        if ir_base:
            return RouteDecision(
                track=track,
                source=Source.CORPORATE_IR,
                symbol=symbol,
                doc_id=doc_id,
                url=ir_base,
                politeness_required=False,
                reason="heavy audited report -> company IR portal (no ASN filter)",
            )
        return RouteDecision(
            track=track,
            source=Source.UNRESOLVED,
            symbol=symbol,
            doc_id=doc_id,
            url=None,
            politeness_required=False,
            reason="heavy report but no IR base registered for symbol; "
            "resolve IR URL before fetching (do not fall back to edge)",
        )

    # Track.FLASH -------------------------------------------------------------
    if mirror_resolver is not None:
        mirror_url = mirror_resolver(announcement)
        if mirror_url:
            return RouteDecision(
                track=track,
                source=Source.OPEN_MIRROR,
                symbol=symbol,
                doc_id=doc_id,
                url=mirror_url,
                politeness_required=False,
                reason="flash filing available on open broadcast mirror",
            )

    if doc_id is None:
        return RouteDecision(
            track=track,
            source=Source.UNRESOLVED,
            symbol=symbol,
            doc_id=None,
            url=None,
            politeness_required=False,
            reason="flash filing carries no attachment id; metadata-only",
        )

    return RouteDecision(
        track=track,
        source=Source.EXCHANGE_EDGE,
        symbol=symbol,
        doc_id=doc_id,
        url=build_exchange_document_url(doc_id),
        politeness_required=True,
        reason="flash filing, no open mirror; edge fetch by disclosed id under polite controls",
    )
