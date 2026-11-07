"""Corroboration, contradiction, source credibility and timelines across a story cluster.

All rules are deterministic. Independence: near-duplicates and items from the same owner do not
count as separate confirmations. A primary official source confirms; media reports corroborate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.extraction import TIER_WEIGHT

OPPOSED_STAGES = {frozenset({"approval", "reversal"}), frozenset({"approval", "suspension"}),
                  frozenset({"implementation", "delay"}), frozenset({"confirmed_fact", "rumour"}),
                  frozenset({"notification", "reversal"})}
STAGE_ORDER = ("rumour", "discussion", "proposal", "consultation", "committee_recommendation",
               "approval", "notification", "implementation", "amendment", "delay", "suspension",
               "reversal", "confirmed_fact", "not_applicable")


@dataclass
class Report:
    """One event candidate as reported by one item."""

    item_id: int
    source_id: str
    owner: str
    tier: str
    published_at_utc: str | None
    event: dict
    confidence: float
    duplicate_of: int | None = None


@dataclass
class Assessment:
    verification_state: str
    independent_sources: list[str]
    contradictions: list[str]
    confidence: float
    explanation: list[str]
    timeline: list[dict] = field(default_factory=list)
    needs_human_review: bool = False


def event_key(event: dict) -> tuple:
    names = sorted({e["name"].casefold() for e in event["entities"]
                    if e["entity_type"] in ("company", "government_body", "regulator", "commodity")})
    return (event["event_type"], tuple(names))


def _indicator_conflicts(reports: list[Report]) -> list[str]:
    seen: dict[tuple, tuple[float, int]] = {}
    out = []
    for r in reports:
        for ind in r.event["indicators"]:
            if ind["value"] is None:
                continue
            k = (ind["name"].casefold(), (ind["period"] or "").casefold(), (ind["unit"] or "").casefold())
            if k in seen and abs(seen[k][0] - ind["value"]) > 1e-9:
                out.append(f"indicator '{ind['name']}' {ind['period'] or ''}: item {seen[k][1]} says "
                           f"{seen[k][0]}, item {r.item_id} says {ind['value']}")
            seen.setdefault(k, (ind["value"], r.item_id))
    return out


def assess(reports: list[Report]) -> Assessment:
    if not reports:
        raise ValueError("no reports to assess")
    reports = sorted(reports, key=lambda r: (r.published_at_utc or "", r.item_id))
    independent: dict[str, Report] = {}
    for r in reports:
        if r.duplicate_of is None:
            independent.setdefault(r.owner or r.source_id, r)
    contradictions = []
    stages = {r.event["status_stage"] for r in reports}
    for pair in OPPOSED_STAGES:
        if pair <= stages:
            contradictions.append("reports disagree on stage: " + " vs ".join(sorted(pair)))
    directions = {r.event["direction"] for r in reports} - {"unknown", "mixed", "neutral"}
    if {"positive", "negative"} <= directions:
        contradictions.append("reports disagree on direction: positive vs negative")
    contradictions += _indicator_conflicts(reports)

    has_primary = any(r.tier == "primary_official" for r in independent.values())
    n = len(independent)
    if contradictions:
        state = "disputed"
    elif has_primary:
        state = "primary_confirmed"
    elif n >= 2:
        state = "corroborated"
    else:
        state = "single_source"
    best = max(r.confidence for r in reports)
    bonus = {"primary_confirmed": 0.15, "corroborated": min(0.1 * (n - 1), 0.2),
             "single_source": 0.0, "disputed": -0.25}[state]
    conf = round(max(0.0, min(1.0, best + bonus)), 3)
    why = [f"best single-report confidence {best}",
           f"{n} independent source(s): {', '.join(sorted(independent))}",
           f"{sum(r.duplicate_of is not None for r in reports)} near-duplicate(s) not counted",
           f"state {state} adjusts confidence by {bonus:+.2f}"]
    why += [f"credibility {o}: tier {r.tier} ({TIER_WEIGHT.get(r.tier, 0.3)})"
            for o, r in sorted(independent.items())]
    why += [f"contradiction: {c}" for c in contradictions]
    return Assessment(state, sorted(independent), contradictions, conf, why, timeline(reports),
                      needs_human_review=bool(contradictions) or state == "single_source")


def timeline(reports: list[Report]) -> list[dict]:
    """Chronological stages of a story with a flag where the stage changed."""
    out, last = [], None
    for r in sorted(reports, key=lambda r: (r.published_at_utc or "9999", r.item_id)):
        stage = r.event["status_stage"]
        out.append({"published_at_utc": r.published_at_utc, "item_id": r.item_id,
                    "source_id": r.source_id, "status_stage": stage,
                    "stage_changed": last is not None and stage != last,
                    "headline": r.event["headline"],
                    "time_known": r.published_at_utc is not None})
        last = stage
    return out
