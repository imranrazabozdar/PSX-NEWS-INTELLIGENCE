"""Stage 2, batch 1: event classification, entity mapping and evidence assessment for headline events.

Runs after engines/headline_events.py. Per stored item that the headline builder attached to an event (and not
yet processed here), in one transaction:

1. Classify the headline (engines/event_classification): primary type, secondary types, status-stage cue,
   claim nature, denial cues. All rule-based with matched text as evidence.
2. Map entities: companies only through the existing exact-match resolver (engines.news_tagging /
   entity_resolution: capital tickers or exact multi-word names; ambiguous and unresolved mentions are kept
   visible, never assigned); other entities (regulators, government bodies, institutions, countries,
   commodities, indicators, PSX sectors) from exact phrases. Relation: direct | context (implied) |
   ambiguous | unresolved. No company is inferred from a sector.
3. Assess the evidence: publisher group (sources.owner, else the registrable web domain, so feeds of one
   publisher form one group), source role from the reliability tier, and independence = not_independent
   (stored duplicate, near-identical copy, or same publisher group as earlier evidence) or unknown. It is
   NEVER "independent": headline metadata cannot establish that, so different domains are not treated as
   independent confirmation.
4. Update the event only through a new revision when something material changes: type (from "other"), status
   stage (a development), or verification state (primary_confirmed when a primary official source reports
   it; disputed when a denial or an opposing stage from another publisher group appears). Reports from media
   never make an event "corroborated" or "confirmed".
5. Record everything in one event_extractions row (schema_version event-intel/1, model deterministic). The
   insert has no conflict clause: a retry or concurrent run rolls back entirely.

event_evidence rows are append-only, so this stage's independence assessment lives in its processing
record (it never contradicts the builder's 0 values; it only adds 0 where the builder left NULL).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from database.canonical import now_utc
from database.connection import Database, DatabaseBudgetError, DatabaseError
from engines import headline_events as hb
from engines.entity_resolution import resolve
from engines.event_classification import classify, company_like_mentions, entity_mentions
from engines.verification import OPPOSED_STAGES

SCHEMA_VERSION = "event-intel/1"
MODEL = "deterministic"
PROMPT_VERSION = "none"
CHANGED_BY = "event-intel/1"
# types for which a development stage does not apply (assessed, not "unknown")
STAGELESS = {
    "corporate_result",
    "corporate_dividend",
    "commodity_price",
    "economic_indicator",
    "market_structure",
    "credit_rating",
    "security_incident",
}
CONFLICT_WINDOW_HOURS = 48
_SLD = (".com.pk", ".gov.pk", ".org.pk", ".net.pk", ".edu.pk", ".co.uk", ".com.au")

ITEM_SQL = """SELECT i.source_item_id, i.title, i.canonical_url, i.original_url, i.published_at_utc,
       i.collected_at_utc, i.duplicate_of_item_id, s.source_id, s.owner, s.reliability_tier, s.source_type,
       x.event_id, x.extracted_json AS builder_json, v.is_independent AS builder_independent
FROM event_extractions x
JOIN source_items i USING(source_item_id) JOIN sources s ON s.source_id = i.source_id
LEFT JOIN event_evidence v ON v.event_id = x.event_id AND v.source_item_id = x.source_item_id
     AND v.recorded_by = ?
WHERE x.schema_version = ? AND x.model = ? AND x.event_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM event_extractions y WHERE y.source_item_id = x.source_item_id
                  AND y.schema_version = ? AND y.model = ? AND y.prompt_version = ?)
ORDER BY x.source_item_id LIMIT ?"""


@dataclass
class Summary:
    processed: int = 0
    already_processed: int = 0
    revisions: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_at_budget: bool = False


def publisher_group(owner: str | None, url: str | None, source_id: str) -> str:
    """One group per publisher: the recorded owner, else the registrable domain of the item URL."""
    if owner:
        return "owner:" + owner.strip().casefold()
    host = (urlparse(url or "").hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if host:
        parts = host.split(".")
        keep = 3 if any(host.endswith(s) for s in _SLD) else 2
        return "domain:" + ".".join(parts[-keep:])
    return "source:" + source_id


def _role(tier: str | None) -> str:
    return {
        "primary_official": "primary_official",
        "established_media": "secondary_reporting",
        "specialist": "specialist",
    }.get(tier or "", "unrated")


def _hours(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    pa = datetime.fromisoformat(a.replace("Z", "+00:00"))
    pb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return abs((pa - pb).total_seconds()) / 3600


def _prior(db: Database, event_id: int, source_item_id: int) -> list[dict]:
    """Earlier items of this event already processed here, with their recorded assessment."""
    rows = db.execute(
        """SELECT x.source_item_id, x.extracted_json, i.published_at_utc, i.collected_at_utc
           FROM event_extractions x JOIN source_items i USING(source_item_id)
           WHERE x.event_id = ? AND x.schema_version = ? AND x.model = ? AND x.source_item_id < ?
           ORDER BY x.source_item_id""",
        (event_id, SCHEMA_VERSION, MODEL, source_item_id),
    )
    return [dict(r) | {"intel": json.loads(r["extracted_json"])} for r in rows]


def _companies(tagger, title: str, as_of: str | None) -> list[dict]:
    t = tagger.tag(title, as_of=as_of)
    out = [
        {
            "entity_type": "company",
            "company_id": c["company_id"],
            "ticker": c["ticker"],
            "name": c["legal_name"],
            "sector": c["sector"],
            "relation": "direct",
            "evidence": c["evidence"],
            "needs_review": bool(c["needs_review"]),
        }
        for c in t.companies
    ]
    for u in t.unresolved:
        out.append(
            {
                "entity_type": "company",
                "company_id": None,
                "name": u["mention"],
                "relation": "ambiguous" if u["status"] == "ambiguous" else "unresolved",
                "evidence": u["mention"],
                "reason": u["reason"],
            }
        )
    covered = " ".join(e["evidence"].casefold() for e in out)
    for name in company_like_mentions(title):
        if name.casefold() not in covered and not any(
            c["name"] and c["name"].casefold() in name.casefold() for c in out if c["relation"] == "direct"
        ):
            res = resolve(tagger.db, name)
            if res.status == "resolved":
                continue  # resolved by the master under this exact name: already covered by the tagger
            out.append(
                {
                    "entity_type": "company",
                    "company_id": None,
                    "name": name,
                    "relation": "ambiguous" if res.status == "ambiguous" else "unresolved",
                    "evidence": name,
                    "reason": "company-like name not in the company master (51 companies)"
                    if res.status != "ambiguous"
                    else "; ".join(res.reasons)[:200],
                }
            )
    return out


def analyse(db: Database, item: dict, *, tagger, sectors: list[str]) -> dict:
    """Pure decision (reads only): the item's intelligence record and the event changes it implies."""
    title = (item["title"] or "").strip()
    when = item["published_at_utc"] or item["collected_at_utc"]
    companies = _companies(tagger, title, (when or "")[:10] or None)
    # a company subject (resolved or not) enables corporate types; it never assigns the event to a company
    cls = classify(title, company_mentioned=bool(companies))
    entities = companies + entity_mentions(title, sectors)
    prior = _prior(db, item["event_id"], item["source_item_id"])
    group = publisher_group(item["owner"], item["canonical_url"] or item["original_url"], item["source_id"])
    prior_groups = {p["intel"]["evidence"]["publisher_group"] for p in prior}
    if item["builder_independent"] == 0 or item["duplicate_of_item_id"] is not None:
        independence, why = "not_independent", "duplicate or near-identical copy (headline builder)"
    elif group in prior_groups:
        independence, why = "not_independent", f"same publisher group as earlier evidence ({group})"
    else:
        independence, why = (
            "unknown",
            "different publisher group; independence cannot be established from a headline",
        )
    evidence = {
        "publisher_group": group,
        "source_role": _role(item["reliability_tier"]),
        "reliability_tier": item["reliability_tier"],
        "independence": independence,
        "independence_reason": why,
        "claim_nature": cls.claim_nature,
        "evidence_basis": "headline_only",
        "distinct_publisher_groups": len(prior_groups | {group}),
    }
    builder = json.loads(item["builder_json"] or "{}")
    figure_note = None
    if builder.get("outcome") == "UPDATE" and not cls.figures_with_units:
        figure_note = "builder UPDATE on a figure without a unit or context: not treated as material"
    return {
        "classification": vars(cls),
        "entities": entities,
        "evidence": evidence,
        "prior": prior,
        "when": when,
        "builder_outcome": builder.get("outcome"),
        "figure_note": figure_note,
    }


def _event_changes(event: dict, a: dict) -> tuple[dict, list[str], list[str]]:
    """Material changes to the event (existing columns only), the reasons, and any conflicts."""
    cls, ev, prior = a["classification"], a["evidence"], a["prior"]
    changes, reasons, conflicts = {}, [], []
    if event["event_type"] == "other" and cls["primary_type"] != "other":
        changes["event_type"] = cls["primary_type"]
        reasons.append(
            f"classified as {cls['primary_type']} ({', '.join(cls['type_evidence'][cls['primary_type']])})"
        )
    etype = changes.get("event_type", event["event_type"])
    unassessed = not prior  # the first item processed here: the builder's stage was never an assessment
    if cls["denial"]:
        conflicts.append(f"denial in headline: {', '.join(cls['denial'])}")
    stage = cls["stage"]
    if stage and stage != event["status_stage"]:
        for p in prior:
            pstage = p["intel"]["classification"]["stage"]
            if (
                pstage
                and frozenset({pstage, stage}) in OPPOSED_STAGES
                and p["intel"]["evidence"]["publisher_group"] != ev["publisher_group"]
                and _hours(p["published_at_utc"] or p["collected_at_utc"], a["when"]) <= CONFLICT_WINDOW_HOURS
            ):
                conflicts.append(
                    f"opposing stages {pstage} vs {stage} from different publishers within "
                    f"{CONFLICT_WINDOW_HOURS} h"
                )
        if not conflicts:
            changes["status_stage"] = stage
            reasons.append(
                ("stage assessed: " if unassessed else "development: ")
                + f"{event['status_stage']} -> {stage} ('{cls['stage_evidence']}')"
            )
    elif not stage and unassessed and etype in STAGELESS and event["status_stage"] != "not_applicable":
        changes["status_stage"] = "not_applicable"
    if conflicts and event["verification_state"] != "disputed":
        changes["verification_state"] = "disputed"
        reasons.append("conflicting reports: " + "; ".join(conflicts))
    elif (
        not conflicts
        and event["verification_state"] not in ("disputed", "primary_confirmed")
        and ev["source_role"] == "primary_official"
        and cls["claim_nature"] == "news_report"
    ):
        changes["verification_state"] = "primary_confirmed"
        reasons.append(f"reported by a primary official source ({ev['publisher_group']})")
    return changes, reasons, conflicts


def _statements(item: dict, event: dict, a: dict) -> tuple[list, dict, list]:
    changes, reasons, conflicts = _event_changes(event, a)
    now = now_utc()
    stmts = []
    if changes:
        new = {k: event[k] for k in ("event_type", "status_stage", "verification_state")} | changes
        secondary = sorted(
            set(a["classification"]["secondary_types"])
            | {t for p in a["prior"] for t in p["intel"]["classification"]["secondary_types"]}
            - {new["event_type"]}
        )
        snapshot = json.dumps(
            new | {"secondary_types": secondary, "source_item_id": item["source_item_id"]}, sort_keys=True
        )
        stmts += [
            (
                "INSERT INTO event_revisions(event_id, revision_no, recorded_at_utc, status_stage, "
                "verification_state, headline, summary, snapshot_json, change_reason, changed_by, "
                "model_version, prompt_version) "
                "SELECT event_id, current_revision + 1, ?, ?, ?, headline, summary, ?, ?, ?, ?, ? "
                "FROM events WHERE event_id = ?",
                [
                    now,
                    new["status_stage"],
                    new["verification_state"],
                    snapshot,
                    "; ".join(reasons)[:900],
                    CHANGED_BY,
                    MODEL,
                    PROMPT_VERSION,
                    event["event_id"],
                ],
            ),
            (
                "UPDATE events SET event_type = ?, status_stage = ?, verification_state = ?, "
                "current_revision = current_revision + 1, updated_at_utc = ? WHERE event_id = ?",
                [new["event_type"], new["status_stage"], new["verification_state"], now, event["event_id"]],
            ),
        ]
    record = {
        "event_id": event["event_id"],
        "classification": a["classification"],
        "entities": a["entities"],
        "evidence": a["evidence"],
        "event_changes": changes,
        "change_reasons": reasons,
        "conflicts": conflicts,
        "builder_outcome": a["builder_outcome"],
        "figure_note": a["figure_note"],
    }
    cls = a["classification"]
    review = (
        list(cls["review_reasons"])
        + [
            f"entity {e['relation']}: {e['name']}"
            for e in a["entities"]
            if e["relation"] in ("ambiguous", "unresolved")
        ]
        + conflicts
    )
    stmts.append(
        (
            "INSERT INTO event_extractions(source_item_id, event_id, call_id, schema_version, "
            "prompt_version, model, "
            "extracted_json, confidence, confidence_explanation, needs_human_review, review_reasons_json, "
            "provenance_json, created_at_utc) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
            [
                item["source_item_id"],
                event["event_id"],
                SCHEMA_VERSION,
                PROMPT_VERSION,
                MODEL,
                json.dumps(record, sort_keys=True),
                "rule-based classification of a headline; no confidence score; verification is separate",
                int(bool(review)),
                json.dumps(review),
                json.dumps({"evidence_basis": "headline_only", "builder_schema": hb.SCHEMA_VERSION}),
                now,
            ],
        )
    )
    return stmts, changes, review


def _done(db: Database, source_item_id: int) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM event_extractions WHERE source_item_id = ? AND schema_version = ? "
            "AND model = ? AND prompt_version = ?",
            (source_item_id, SCHEMA_VERSION, MODEL, PROMPT_VERSION),
        )
    )


def process_item(db: Database, item: dict, *, tagger, sectors: list[str]) -> tuple[str, bool]:
    a = analyse(db, item, tagger=tagger, sectors=sectors)
    event = db.execute("SELECT * FROM events WHERE event_id = ?", (item["event_id"],))[0]
    stmts, changes, _ = _statements(item, event, a)
    try:
        db.batch(stmts)
    except DatabaseBudgetError:
        raise
    except DatabaseError:
        if _done(db, item["source_item_id"]):
            return "ALREADY_PROCESSED", False
        raise
    return "PROCESSED", bool(changes)


def run(db: Database, *, limit: int = 200) -> Summary:
    """Process up to `limit` eligible items, oldest first. Safe to re-run."""
    from engines.news_tagging import NewsTagger

    s = Summary()
    tagger = NewsTagger(db)
    sectors = [r["name"] for r in db.execute("SELECT name FROM sectors ORDER BY name")]
    rows = db.execute(
        ITEM_SQL, (hb.RECORDED_BY, hb.SCHEMA_VERSION, hb.MODEL, SCHEMA_VERSION, MODEL, PROMPT_VERSION, limit)
    )
    for row in rows:
        item = dict(row)
        try:
            outcome, revised = process_item(db, item, tagger=tagger, sectors=sectors)
        except DatabaseBudgetError:
            s.stopped_at_budget = True
            break
        except DatabaseError as exc:
            s.errors.append(f"item {item['source_item_id']}: {str(exc)[:200]}")
            continue
        except (ValueError, TypeError, KeyError) as exc:  # malformed stored data: nothing written, retried
            s.errors.append(
                f"item {item['source_item_id']}: invalid item data: {type(exc).__name__}: {str(exc)[:160]}"
            )
            continue
        if outcome == "ALREADY_PROCESSED":
            s.already_processed += 1
            continue
        s.processed += 1
        s.revisions += int(revised)
    return s


def classification_status(db: Database, event_id: int) -> str:
    """'assessed' once any item of the event was processed here; otherwise 'not_assessed'. The builder's
    status_stage 'not_applicable' must be displayed as Not assessed until then."""
    rows = db.execute(
        "SELECT 1 FROM event_extractions WHERE event_id = ? AND schema_version = ? LIMIT 1",
        (event_id, SCHEMA_VERSION),
    )
    return "assessed" if rows else "not_assessed"


def event_intel(db: Database, event_id: int) -> dict:
    """Aggregated view for later components: entities by relation, evidence breadth and conflicts."""
    recs = [
        json.loads(r["extracted_json"])
        for r in db.execute(
            "SELECT extracted_json FROM event_extractions WHERE event_id = ? AND schema_version = ? "
            "ORDER BY source_item_id",
            (event_id, SCHEMA_VERSION),
        )
    ]
    ents: dict[tuple, dict] = {}
    for r in recs:
        for e in r["entities"]:
            ents.setdefault((e["entity_type"], e.get("company_id") or e["name"], e["relation"]), e)
    return {
        "status": "assessed" if recs else "not_assessed",
        "items": len(recs),
        "entities": list(ents.values()),
        "publisher_groups": sorted({r["evidence"]["publisher_group"] for r in recs}),
        "independent_reports_confirmed": 0,  # never established from headlines
        "not_independent_items": sum(r["evidence"]["independence"] == "not_independent" for r in recs),
        "conflicts": [c for r in recs for c in r["conflicts"]],
        "secondary_types": sorted({t for r in recs for t in r["classification"]["secondary_types"]}),
    }


def main(argv: list[str] | None = None) -> int:
    """Local only: runs against a SQLite file. No Turso path exists in this component."""
    import argparse

    from database.connection import SQLiteDatabase

    ap = argparse.ArgumentParser(description="Classify headline events in a LOCAL SQLite database")
    ap.add_argument("--local-db", required=True)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args(argv)
    db = SQLiteDatabase(args.local_db)
    try:
        s = run(db, limit=args.limit)
    finally:
        db.close()
    print(json.dumps(vars(s), indent=1))
    return 1 if s.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
