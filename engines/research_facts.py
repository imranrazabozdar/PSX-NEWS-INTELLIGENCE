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

    for key, val in fields.items():
        if key in ("symbol", "metric_count"):
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
