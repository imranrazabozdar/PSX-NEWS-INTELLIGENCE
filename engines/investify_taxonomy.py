"""Investify announcement taxonomy.

Groups: Financials, Material, Actions, Insiders, Meetings, Briefings, Other.

These are the seven filter groups on the company announcements page. Each record gets exactly one
group, from Investify's event type, with explicit subtype overrides. The mapping is total: every observed
(event type, subtype) pair maps to one group. An unknown pair maps to Other and is reported, never guessed.

The group is a classification of the PSX announcement's type. It is not an analytical judgement, and the
Investify sentiment tag is kept separately as Investify's own label.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

GROUPS = ("Financials", "Material", "Actions", "Insiders", "Meetings", "Briefings", "Other")

# event type (Investify's classification) -> group
BY_EVENT_TYPE: dict[str, str] = {
    "financials": "Financials",
    "material_disclosure": "Material",
    "corporate_action": "Actions",
    "insider_activity": "Insiders",
    "meeting_governance": "Meetings",
    "corporate_briefing": "Briefings",
    "other": "Other",
}
# subtype overrides where the event type alone would misplace the record
BY_SUBTYPE: dict[str, str] = {
    "report_transmission": "Financials",  # Transmission of a quarterly or annual report
    "auditor_certificate": "Other",  # an auditor's certificate is not a meeting
}


def classify(event_type: str | None, sub_type: str | None) -> str:
    if sub_type in BY_SUBTYPE:
        return BY_SUBTYPE[sub_type]
    return BY_EVENT_TYPE.get(event_type or "", "Other")


def is_known(event_type: str | None, sub_type: str | None) -> bool:
    return sub_type in BY_SUBTYPE or event_type in BY_EVENT_TYPE


def counts(items: Iterable[dict]) -> dict[str, int]:
    """Count per group, zero included. Completeness: the counts sum to the number of items."""
    c = Counter(classify(i.get("event_type"), i.get("sub_type")) for i in items)
    return {g: c.get(g, 0) for g in GROUPS}
