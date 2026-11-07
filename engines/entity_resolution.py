"""Company entity resolution against the company master (Phase 4).

Every mention resolves to an existing company record or is reported as unresolved or ambiguous.
Nothing is ever created from a news mention, and a PSX symbol is never invented.

Order of evidence, strongest first:
1. A PSX ticker written in capitals (``LUCK``), resolved point-in-time via company_identifiers.
   Lower-case words never match tickers ("good luck" is not Lucky Cement).
2. An exact alias (legal, short, former name, abbreviation, brand), valid at the event date.
3. Anything weaker (a prefix shared by several companies, such as "Engro") is ambiguous: the
   candidates are listed for human review and no company is chosen.

Delisted companies resolve only for events dated before delisting (historical mapping). Otherwise
the result is unresolved, with the recorded successor (for example FFBL merged into FFC) listed
for review. It is never silently re-pointed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from database.canonical import normalise_name, short_name

ALIAS_CONFIDENCE = {"verified": 0.95, "derived": 0.8, "candidate": 0.5}
REVIEW_BELOW = 0.85
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


@dataclass
class Resolution:
    mention: str
    status: str  # resolved | historical | ambiguous | unresolved
    company: dict | None = None
    method: str = ""
    confidence: float = 0.0
    candidates: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return (self.status != "resolved" or self.confidence < REVIEW_BELOW
                or self.method == "alias:former_name")


def _valid(row: dict, as_of: str | None) -> bool:
    if as_of is None:
        return row.get("valid_to") is None
    return ((row.get("valid_from") is None or row["valid_from"] <= as_of)
            and (row.get("valid_to") is None or row["valid_to"] >= as_of))


def _delisting(db, company_id: str) -> tuple[str | None, str | None]:
    rows = db.execute("SELECT status, effective_date, related_company_id FROM company_status_history "
                      "WHERE company_id = ? AND status IN ('delisted','merged_into') "
                      "ORDER BY status_event_id", (company_id,))
    date = next((r["effective_date"] for r in rows if r["effective_date"]), None)
    successor = next((r["related_company_id"] for r in rows if r["related_company_id"]), None)
    return date, successor


def _company(db, company_id: str) -> dict:
    row = db.execute("SELECT c.company_id, c.legal_name, c.listing_status, "
                     "(SELECT value FROM company_identifiers i WHERE i.company_id = c.company_id "
                     " AND i.id_type = 'psx_ticker' ORDER BY i.valid_to IS NULL DESC LIMIT 1) AS psx_symbol "
                     "FROM companies c WHERE c.company_id = ?", (company_id,))
    return row[0]


def _finalise(db, mention: str, matches: dict[str, tuple[float, str]], as_of: str | None) -> Resolution:
    usable, historical, reasons = {}, {}, []
    for cid, (conf, method) in matches.items():
        comp = _company(db, cid)
        if comp["listing_status"] == "listed":
            usable[cid] = (comp, conf, method)
            continue
        date, successor = _delisting(db, cid)
        if as_of and date and as_of <= date:
            historical[cid] = (comp, conf, method)
        else:
            note = f"{comp['legal_name']} is {comp['listing_status']}"
            if date:
                note += f" since {date}"
            if successor:
                note += f"; recorded successor {successor} (not applied automatically)"
            reasons.append(note)
    if len(usable) == 1 and not historical:
        comp, conf, method = next(iter(usable.values()))
        return Resolution(mention, "resolved", comp, method, conf, reasons=reasons)
    if len(historical) == 1 and not usable:
        comp, conf, method = next(iter(historical.values()))
        return Resolution(mention, "historical", comp, method, conf,
                          reasons=reasons + ["resolved to a company that was listed at the event date"])
    every = list(usable.values()) + list(historical.values())
    if every:
        return Resolution(mention, "ambiguous", None, "multiple", 0.0,
                          [dict(c, match_method=m) for c, _, m in every],
                          reasons + [f"{len(every)} companies match '{mention}'"])
    return Resolution(mention, "unresolved", None, "", 0.0, reasons=reasons or ["no company master match"])


def resolve(db, mention: str, *, as_of: str | None = None) -> Resolution:
    """Resolve one company mention. ``as_of`` is the event date (YYYY-MM-DD) for point-in-time use."""
    text = (mention or "").strip()
    if not text:
        return Resolution(mention, "unresolved", reasons=["empty mention"])
    if _TICKER.match(text):
        rows = db.execute("SELECT company_id, valid_from, valid_to FROM company_identifiers "
                          "WHERE id_type = 'psx_ticker' AND value = ?", (text,))
        current = [r for r in rows if _valid(r, as_of)]
        # a ticker no longer valid is still reported (delisted/historical) unless another holder has it
        hits = {r["company_id"]: (0.97, "psx_ticker") for r in (current or rows)}
        if hits:
            return _finalise(db, text, hits, as_of)
    norm, short = normalise_name(text), short_name(text)
    rows = db.execute("SELECT company_id, alias_type, confidence, valid_from, valid_to FROM company_aliases "
                      "WHERE alias_normalized IN (?, ?) AND alias_type <> 'ticker'", (norm, short))
    hits: dict[str, tuple[float, str]] = {}
    for r in rows:
        if as_of is not None and not _valid(r, as_of):
            continue
        conf = ALIAS_CONFIDENCE[r["confidence"]] - (0.1 if r["alias_type"] == "former_name" else 0.0)
        if conf > hits.get(r["company_id"], (0.0, ""))[0]:
            hits[r["company_id"]] = (round(conf, 2), f"alias:{r['alias_type']}")
    if hits:
        res = _finalise(db, text, hits, as_of)
        if res.status == "resolved" and res.method == "alias:former_name":
            res.reasons.append("matched a former name; confirm the event refers to the same entity")
        return res
    # Weak evidence only: a partial name shared by several companies. Never auto-selected.
    if len(short) >= 3:
        rows = db.execute("SELECT DISTINCT company_id FROM company_aliases WHERE alias_type = 'short_name' "
                          "AND (alias_normalized = ? OR alias_normalized LIKE ?)", (short, short + " %"))
        if rows:
            cands = [dict(_company(db, r["company_id"]), match_method="partial_name") for r in rows]
            return Resolution(text, "ambiguous", None, "partial_name", 0.0, cands,
                              [f"'{text}' is only part of {len(cands)} company name(s); "
                               "human review required"])
    return Resolution(text, "unresolved", reasons=["no company master match"])
