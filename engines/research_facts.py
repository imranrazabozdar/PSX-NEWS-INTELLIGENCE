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
