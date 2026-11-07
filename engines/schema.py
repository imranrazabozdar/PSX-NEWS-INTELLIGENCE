"""Strict extraction schema and validator (stdlib only, no partial acceptance).

The LLM must return exactly this shape. Unknown keys, missing keys, wrong types or values
outside the controlled vocabularies make the whole output invalid. Nothing is repaired or
guessed: an invalid output is recorded and flagged for review, never stored as an event.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "event-extraction/1"

EVENT_TYPES = (
    "corporate_result", "corporate_dividend", "corporate_action", "corporate_announcement",
    "management_change", "regulatory_action", "monetary_policy", "fiscal_policy", "tax_policy",
    "trade_policy", "energy_policy", "economic_indicator", "commodity_price", "commodity_supply",
    "geopolitical", "security_incident", "political", "legal_court", "infrastructure",
    "credit_rating", "imf_program", "market_structure", "other",
)
STATUS_STAGES = (
    "rumour", "discussion", "proposal", "consultation", "committee_recommendation", "approval",
    "notification", "implementation", "amendment", "delay", "suspension", "reversal",
    "confirmed_fact", "not_applicable",
)
DIRECTIONS = ("positive", "negative", "mixed", "neutral", "unknown")
MAGNITUDES = ("low", "medium", "high", "unknown")
HORIZONS = ("immediate", "days_weeks", "quarterly", "annual", "long_term", "unknown")
CLAIM_TYPES = (
    "verified_fact", "official_statement", "news_report", "analyst_interpretation",
    "personal_opinion", "prediction", "rumour", "advertisement", "model_inference", "unclear",
)
ENTITY_TYPES = ("company", "sector", "government_body", "regulator", "person", "country",
                "commodity", "organisation", "indicator", "other")
DATE_PRECISIONS = ("exact", "day", "month", "quarter", "year", "unknown")

_STR, _OPT_STR, _NUM_OR_NULL, _LIST = "str", "str|null", "num|null", "list"

ENTITY = {"name": _STR, "entity_type": ENTITY_TYPES, "quote": _STR}
INDICATOR = {"name": _STR, "value": _NUM_OR_NULL, "unit": _OPT_STR, "period": _OPT_STR, "quote": _STR}
CLAIM = {"claim": _STR, "claim_type": CLAIM_TYPES, "quote": _STR}
EVENT = {
    "event_type": EVENT_TYPES,
    "headline": _STR,
    "summary": _STR,
    "status_stage": STATUS_STAGES,
    "event_date": _OPT_STR,
    "event_date_precision": DATE_PRECISIONS,
    "geography": _OPT_STR,
    "direction": DIRECTIONS,
    "magnitude": MAGNITUDES,
    "horizon": HORIZONS,
    "entities": ("list_of", ENTITY),
    "indicators": ("list_of", INDICATOR),
    "claims": ("list_of", CLAIM),
    "uncertainties": ("list_of_str",),
}
TOP = {"is_relevant": "bool", "relevance_reason": _STR, "events": ("list_of", EVENT)}

MAX_EVENTS = 5
MAX_ITEMS = 25
MAX_STR = 1000
_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class SchemaError(ValueError):
    """The model output does not match the schema. Carries every problem found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems[:10]))
        self.problems = problems


def _check(value: Any, spec: Any, path: str, out: list[str]) -> None:
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            out.append(f"{path}: expected object")
            return
        extra = set(value) - set(spec)
        missing = set(spec) - set(value)
        out.extend(f"{path}.{k}: unexpected key" for k in sorted(extra))
        out.extend(f"{path}.{k}: missing" for k in sorted(missing))
        for k in spec:
            if k in value:
                _check(value[k], spec[k], f"{path}.{k}", out)
    elif isinstance(spec, tuple) and spec and spec[0] in ("list_of", "list_of_str"):
        if not isinstance(value, list):
            out.append(f"{path}: expected list")
            return
        limit = MAX_EVENTS if path.endswith("events") else MAX_ITEMS
        if len(value) > limit:
            out.append(f"{path}: more than {limit} items")
        for i, item in enumerate(value):
            _check(item, spec[1] if spec[0] == "list_of" else _STR, f"{path}[{i}]", out)
    elif isinstance(spec, tuple):
        if value not in spec:
            out.append(f"{path}: {value!r} not in controlled vocabulary")
    elif spec == "bool":
        if not isinstance(value, bool):
            out.append(f"{path}: expected boolean")
    elif spec in (_STR, _OPT_STR):
        if value is None and spec == _OPT_STR:
            return
        if not isinstance(value, str) or not value.strip():
            out.append(f"{path}: expected non-empty string")
        elif len(value) > MAX_STR:
            out.append(f"{path}: longer than {MAX_STR} characters")
    elif spec == _NUM_OR_NULL:
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            out.append(f"{path}: expected number or null")
    else:  # pragma: no cover - schema programming error
        raise AssertionError(spec)


def validate_extraction(payload: Any) -> dict:
    """Return the payload unchanged if it matches the schema exactly, else raise SchemaError."""
    problems: list[str] = []
    _check(payload, TOP, "$", problems)
    if not problems and not payload["is_relevant"] and payload["events"]:
        problems.append("$.events: must be empty when is_relevant is false")
    if not problems:
        for i, ev in enumerate(payload["events"]):
            if ev["event_date"] is not None and not _DATE.match(ev["event_date"]):
                problems.append(f"$.events[{i}].event_date: must be YYYY, YYYY-MM or YYYY-MM-DD")
            if ev["event_date"] is None and ev["event_date_precision"] != "unknown":
                problems.append(f"$.events[{i}].event_date_precision: must be unknown when date is null")
    if problems:
        raise SchemaError(problems)
    return payload


def json_schema() -> dict:
    """The same schema as JSON Schema, for providers that support constrained output."""

    def conv(spec: Any) -> dict:
        if isinstance(spec, dict):
            return {"type": "object", "additionalProperties": False, "required": list(spec),
                    "properties": {k: conv(v) for k, v in spec.items()}}
        if isinstance(spec, tuple) and spec[0] == "list_of":
            return {"type": "array", "items": conv(spec[1])}
        if isinstance(spec, tuple) and spec[0] == "list_of_str":
            return {"type": "array", "items": {"type": "string"}}
        if isinstance(spec, tuple):
            return {"type": "string", "enum": list(spec)}
        return {"bool": {"type": "boolean"}, _STR: {"type": "string"},
                _OPT_STR: {"type": ["string", "null"]}, _NUM_OR_NULL: {"type": ["number", "null"]}}[spec]

    return conv(TOP)
