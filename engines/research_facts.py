"""Distilled research facts: validation before any row is written to psx-library.

A row is one sourced, dated fact in our own words. A row without a source name and a source date is refused.
Forward-looking or analyst-view items must be labelled confidence = "analyst_view", never "fact".
"""

from __future__ import annotations

from typing import Any

COLUMNS = ("company", "topic", "fact_text", "value", "unit", "period", "source_name", "source_url",
           "source_date", "as_of", "confidence", "created_at")
CONFIDENCE = ("fact", "analyst_view")
MAX_FACT_CHARS = 300


class ResearchFactError(ValueError):
    pass


def validate_fact(row: dict[str, Any]) -> dict[str, Any]:
    """Return the row with only the known columns, or raise. Refuses anything unsourced or undated."""
    unknown = set(row) - set(COLUMNS)
    if unknown:
        raise ResearchFactError(f"unknown column(s): {sorted(unknown)}")
    for key in ("company", "topic", "fact_text", "source_name", "source_date", "confidence", "created_at"):
        if not str(row.get(key) or "").strip():
            raise ResearchFactError(f"{key} is required: no source name or date means no row")
    if len(row["fact_text"]) > MAX_FACT_CHARS:
        raise ResearchFactError(f"fact_text is over {MAX_FACT_CHARS} characters: distil it, do not copy it")
    if row["confidence"] not in CONFIDENCE:
        raise ResearchFactError(f"confidence must be one of {CONFIDENCE}")
    return {k: row.get(k) for k in COLUMNS}


SOURCE_NAME = "Investify fundamentals (investify.pk)"
_INSERT = ("INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name, "
           "source_url, source_date, as_of, confidence, created_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_FACT_CHARS else text[: MAX_FACT_CHARS - 3] + "..."


def rows_from_fields(*, company: str, endpoint: str, fields: dict[str, Any], url: str,
                     fetched_at_utc: str) -> list[dict[str, Any]]:
    """Distilled rows from one extracted page. Investify description text is never copied: a metric keeps
    its label, value, unit and period basis only. Each row carries the source name, URL and fetch date."""
    day = fetched_at_utc[:10]
    created = fetched_at_utc
    rows: list[dict[str, Any]] = []

    def add(topic: str, text: str, value: Any = None, unit: Any = None, period: Any = None) -> None:
        rows.append(validate_fact({
            "company": company, "topic": f"{endpoint}.{topic}", "fact_text": _clip(text),
            "value": _number(value),
            "unit": unit or None, "period": period or None, "source_name": SOURCE_NAME, "source_url": url,
            "source_date": day, "as_of": day, "confidence": "fact", "created_at": created}))

    if endpoint == "announcements":
        for item in fields.get("items") or []:
            title = str(item.get("title") or "").strip()
            when = str(item.get("announced_at_utc") or "")[:10]
            if not title or not when:
                continue
            group = str(item.get("taxonomy") or "Other").strip() or "Other"
            # facts only: date, title, taxonomy group and filing link; Investify's materiality and sentiment
            # labels are their judgements and are not stored
            rows.append(validate_fact({
                "company": company, "topic": f"announcements.{group}", "fact_text": _clip(f"{when}: {title}"),
                "value": None, "unit": None, "period": when, "source_name": SOURCE_NAME,
                "source_url": item.get("pdf_url") or url, "source_date": day, "as_of": when,
                "confidence": "fact", "created_at": created}))
        return rows
    if endpoint == "profile":
        _profile_rows(fields, add)
        return rows
    if endpoint == "competitors":
        _competitor_rows(fields, add)
        return rows
    for key, val in fields.items():
        if key in ("symbol", "metric_count", "description"):  # description: Investify's own text
            continue
        if isinstance(val, (str, int, float)) and not isinstance(val, bool) and str(val).strip():
            add(key, f"{key}: {val}")
        elif isinstance(val, list):
            for item in val:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                value = item.get("value")
                text = value.get("text") if isinstance(value, dict) else value
                if not label or text in (None, ""):
                    continue
                period = item.get("period_basis")
                num = value.get("value") if isinstance(value, dict) else None
                unit = value.get("unit") if isinstance(value, dict) else None
                shown = f"{label}: {text}" + (f" ({period})" if period else "")
                add(key, shown, num, unit, period)
    return rows


def insert_rows(db: Any, rows: list[dict[str, Any]]) -> int:
    for row in rows:
        db.execute(_INSERT, tuple(row[c] for c in COLUMNS))
    return len(rows)


_ROLE = {"ceo": "CEO", "chairperson": "Chairperson", "company_secretary": "Company secretary", "cfo": "CFO"}


def _text_value(entry: Any) -> tuple[str, Any]:
    if isinstance(entry, dict):
        return str(entry.get("text") or entry.get("value") or ""), entry.get("value")
    return str(entry), entry


def _profile_rows(fields: dict[str, Any], add: Any) -> None:
    """Facts from the profile page. The company description is Investify's own text and is never stored."""
    plain = (("sector", "Sector"), ("website", "Website"), ("registered_address", "Registered address"))
    for key, label in plain:
        val = fields.get(key)
        if isinstance(val, str) and val.strip():
            add(key, f"{label}: {val.strip()}")
    for role, name in (fields.get("leadership") or {}).items():
        if isinstance(name, str) and name.strip():
            add("leadership", f"{_ROLE.get(role, role.replace('_', ' ').capitalize())}: {name.strip()}")
    market = fields.get("market_structure") or {}
    for key, label, unit in (("market_cap", "Market cap", "PKR"), ("price", "Price", "PKR"),
                             ("total_shares", "Total shares", "shares"),
                             ("free_float_shares", "Free-float shares", "shares")):
        if key in market:
            text, value = _text_value(market[key])
            if text:
                add("market_structure", f"{label}: {text}", value, unit)
    split = fields.get("share_float_split") or {}
    for key, label in (("free_float_pct", "Free float"), ("locked_pct", "Locked shares")):
        value = split.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            add("share_float", f"{label}: {value}%", value, "percent")


def _competitor_rows(fields: dict[str, Any], add: Any) -> None:
    """Sector, the same-sector count and one row per peer. The extractor's own note is not stored."""
    sector = fields.get("sector")
    if isinstance(sector, str) and sector.strip():
        add("sector", f"Sector: {sector.strip()}")
    count = fields.get("same_sector_count")
    if isinstance(count, int) and not isinstance(count, bool):
        add("peer_count", f"Same-sector listed companies: {count} ({fields.get('peer_source') or 'sector'})",
            count, "companies")
    for peer in fields.get("peers") or []:
        if isinstance(peer, dict) and peer.get("ticker"):
            name = str(peer.get("name") or "").strip()
            add("peers", f"Peer: {peer['ticker']}" + (f" ({name})" if name else ""))

