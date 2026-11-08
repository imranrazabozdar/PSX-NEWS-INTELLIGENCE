"""Stale-assessment revalidation and the human review workflow (Stage 2, final batch).

Revalidation (system, deterministic): an impact assessment is *stale* when its event has a newer revision than
the one it was assessed against. Each stale assessment is recomputed with the same T1-T9 rules
(engines.impact_intel) and, in ONE transaction:
* the result is unchanged: the assessment moves to the new event revision (scenario_only / 'revalidated'),
  with its steps and scenarios recorded again for that revision;
* the event is now disputed: it moves to needs_review / 'event_disputed';
* the result would change: it moves to needs_revalidation / 'evidence_superseded'. The PROPOSED values are
  recorded in the change reason, and the earlier conclusion is kept. Migration 0009 allows a substantive
  change only with a new human review, so the system never rewrites a conclusion on its own.
History is preserved by 0009's revision rows. Nothing is promoted beyond scenario_only.

Review (human, explicit): decisions are written only by record_impact_review / record_exposure_review with a
named reviewer and notes. Viewing never writes. 0009 and 0008 triggers re-check every rule: one review per
transition, newest review only, accept only from provisional, no repeated use.
"""

from __future__ import annotations

import json

from database.canonical import now_utc
from database.connection import Database, DatabaseBudgetError, DatabaseError
from engines import event_intel as ei
from engines import exposure_mapping
from engines import impact_intel as ii

ACTIVE = ("scenario_only", "needs_review", "provisional")
SUBSTANTIVE = (
    "direction",
    "magnitude_level",
    "horizon",
    "evidence_confidence",
    "exposure_confidence",
    "direction_confidence",
    "magnitude_confidence",
    "scenario_uncertainty",
)
CHANGED_BY = "revalidation/1"


def stale_assessments(db: Database) -> list[dict]:
    return [
        dict(r)
        for r in db.execute(
            "SELECT a.*, e.current_revision AS event_current_revision, e.verification_state "
            "FROM impact_assessments a JOIN events e USING(event_id) "
            "WHERE a.event_revision_no < e.current_revision AND a.assessment_status IN ('scenario_only', "
            "'needs_review', 'provisional') ORDER BY a.assessment_id"
        )
    ]


def _candidate(db: Database, assessment_id: int) -> dict | None:
    r = db.execute(
        "SELECT c.* FROM impact_assessment_inputs i JOIN exposure_candidates_current c "
        "ON c.candidate_id = i.exposure_candidate_id WHERE i.assessment_id = ? "
        "AND i.input_kind = 'exposure_candidate' ORDER BY i.input_id LIMIT 1",
        (assessment_id,),
    )
    return dict(r[0]) if r else None


def _recompute(db: Database, a: dict) -> dict | None:
    event = db.execute("SELECT * FROM events WHERE event_id = ?", (a["event_id"],))[0]
    cand = _candidate(db, a["assessment_id"])
    if cand is None:
        return None
    new = ii._assessment(db, event, cand, a["mechanism_id"], ei.event_intel(db, a["event_id"]))
    return {"event": event, "cand": cand, "new": new}


def _update(a: dict, status: tuple[str, str], reason: str, *, revision_no: int | None) -> tuple[str, list]:
    sets = (
        "assessment_status = ?, status_reason = ?, current_revision = current_revision + 1, "
        "change_reason = ?, changed_by = ?, actor_type = 'system', updated_at_utc = ?"
    )
    params = [status[0], status[1], reason[:900], CHANGED_BY, now_utc()]
    if revision_no is not None:
        sets += ", event_revision_no = ?"
        params.append(revision_no)
    return (
        f"UPDATE impact_assessments SET {sets} WHERE assessment_id = ? AND current_revision = ?",  # noqa: S608
        [*params, a["assessment_id"], a["current_revision"]],
    )


def revalidate(db: Database) -> dict:
    """Revalidate every stale assessment once. Idempotent: an assessment already awaiting a human decision
    (needs_revalidation) is not touched again."""
    out = {"unchanged": 0, "needs_review": 0, "needs_revalidation": 0, "skipped": [], "errors": []}
    for a in stale_assessments(db):
        try:
            r = _recompute(db, a)
            if r is None:
                out["skipped"].append(f"assessment {a['assessment_id']}: no exposure input")
                continue
            event, new = r["event"], r["new"]
            if event["verification_state"] == "disputed" and a["assessment_status"] != "needs_review":
                stmts = [
                    _update(
                        a,
                        ("needs_review", "event_disputed"),
                        f"revalidation: event {event['event_id']} is now disputed (revision "
                        f"{event['current_revision']})",
                        revision_no=event["current_revision"],
                    )
                ]
                kind = "needs_review"
            else:
                proposed = {
                    "direction": new["direction"],
                    "magnitude_level": new["magnitude"],
                    "horizon": new["horizon"],
                    "evidence_confidence": new["evidence_conf"],
                    "exposure_confidence": new["exposure_conf"],
                    "direction_confidence": new["direction_conf"],
                    "magnitude_confidence": new["magnitude_conf"],
                    "scenario_uncertainty": new["uncertainty"],
                }
                diff = {k: (a[k], proposed[k]) for k in SUBSTANTIVE if a[k] != proposed[k]}
                if diff:
                    stmts = [
                        _update(
                            a,
                            ("needs_revalidation", "evidence_superseded"),
                            "revalidation: a newer event revision would change "
                            + json.dumps(diff, sort_keys=True)
                            + "; earlier conclusion kept for review",
                            revision_no=None,
                        )
                    ]
                    kind = "needs_revalidation"
                else:
                    status = (
                        ("needs_review", "event_disputed")
                        if event["verification_state"] == "disputed"
                        else ("scenario_only", "revalidated")
                    )
                    stmts = [
                        _update(
                            a,
                            status,
                            f"revalidated against event revision {event['current_revision']}"
                            ": result unchanged",
                            revision_no=event["current_revision"],
                        )
                    ]
                    # steps and scenarios for the new revision, identical rules
                    stmts += ii.detail_statements(
                        a["event_id"],
                        a["company_id"],
                        a["mechanism_id"],
                        new,
                        revision_no=a["current_revision"] + 1,
                    )
                    kind = "unchanged"
            db.batch(stmts)
            out[kind] += 1
        except DatabaseBudgetError:
            raise
        except (DatabaseError, ValueError, TypeError, KeyError) as exc:
            out["errors"].append(f"assessment {a['assessment_id']}: {type(exc).__name__}: {str(exc)[:200]}")
    return out


# ------------------------------------------------------------------ review queue (read-only)
def review_queue(db: Database, *, limit: int = 200) -> list[dict]:
    """Everything awaiting a human: why, what evidence exists, what a decision would change, and who or what
    produced the current state."""
    q: list[dict] = []
    for r in db.execute(
        "SELECT assessment_id, event_id, company_id, mechanism_id, assessment_status, status_reason, "
        "direction, exposure_confidence, change_reason, changed_by, actor_type FROM "
        "impact_assessments WHERE assessment_status IN ('needs_review', 'needs_revalidation') "
        "ORDER BY assessment_id LIMIT ?",
        (limit,),
    ):
        q.append(
            {
                "kind": "impact_assessment",
                "ref": r["assessment_id"],
                "subject": f"event {r['event_id']} / {r['company_id']} / {r['mechanism_id']}",
                "why": f"{r['assessment_status']} ({r['status_reason']}): {r['change_reason']}",
                "decision_changes": "reject -> rejected_by_review; needs_more_evidence -> needs_review; "
                "request_revalidation -> needs_revalidation; accept only from provisional",
                "previous_actor": f"{r['actor_type']}: {r['changed_by']}",
            }
        )
    for r in db.execute(
        "SELECT candidate_id, event_id, company_id, exposure_level, origin, evidence_status, "
        "explanation FROM exposure_candidates_current WHERE review_status IN ('pending', 'needs_review') "
        "AND effective_status <> 'rejected' ORDER BY candidate_id LIMIT ?",
        (limit,),
    ):
        q.append(
            {
                "kind": "exposure_candidate",
                "ref": r["candidate_id"],
                "subject": f"event {r['event_id']} / {r['company_id']} "
                f"({r['exposure_level']}, {r['origin']})",
                "why": f"exposure {r['evidence_status']}: {r['explanation']}",
                "decision_changes": "accept (only strongly_supported) -> confirmed; reject -> rejected; "
                "needs_more_evidence keeps it pending",
                "previous_actor": "system: exposure rules",
            }
        )
    for r in db.execute(
        "SELECT source_item_id, event_id, review_reasons_json FROM event_extractions WHERE "
        "schema_version = ? AND needs_human_review = 1 ORDER BY source_item_id LIMIT ?",
        (ei.SCHEMA_VERSION, limit),
    ):
        q.append(
            {
                "kind": "event_item",
                "ref": r["source_item_id"],
                "subject": f"event {r['event_id']}",
                "why": "; ".join(json.loads(r["review_reasons_json"])),
                "decision_changes": "record a correction label (data/validation/labels.json); stored records "
                "are append-only and are not rewritten",
                "previous_actor": f"system: {ei.CHANGED_BY}",
            }
        )
    for r in db.execute(
        "SELECT event_id, headline FROM events WHERE verification_state = 'disputed' "
        "ORDER BY event_id LIMIT ?",
        (limit,),
    ):
        q.append(
            {
                "kind": "disputed_event",
                "ref": r["event_id"],
                "subject": r["headline"],
                "why": "conflicting reports",
                "decision_changes": "needs a primary source or a correction label",
                "previous_actor": f"system: {ei.CHANGED_BY}",
            }
        )
    return q


# ------------------------------------------------------------------ explicit human decisions
_DECISION = {
    "reject": ("rejected_by_review", "reviewer_rejected"),
    "needs_more_evidence": ("needs_review", "reviewer_needs_more_evidence"),
    "request_revalidation": ("needs_revalidation", "reviewer_requested_revalidation"),
    "accept": ("confirmed_conclusion", "reviewer_accepted"),
}


def record_impact_review(
    db: Database, assessment_id: int, decision: str, *, reviewer: str, notes: str
) -> dict:
    """Record one explicit human decision on an assessment: review row and transition, one transaction."""
    if decision not in _DECISION:
        raise ValueError(f"decision must be one of {sorted(_DECISION)}")
    if len((reviewer or "").strip()) < 2:
        raise ValueError("an explicit reviewer identity is required")
    if not (notes or "").strip():
        raise ValueError("review notes are required")
    rows = db.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?", (assessment_id,))
    if not rows:
        raise ValueError(f"assessment {assessment_id} not found")
    a = rows[0]
    if decision == "accept" and a["assessment_status"] != "provisional":
        raise ValueError(
            f"cannot accept a '{a['assessment_status']}' assessment: only provisional assessments "
            "with eligible evidence can be accepted"
        )
    status, reason = _DECISION[decision]
    now = now_utc()
    db.batch(
        [
            (
                "INSERT INTO impact_reviews(assessment_id, decision, reviewer, notes, decided_at_utc, "
                "status_at_decision) "
                "VALUES (?,?,?,?,?,?)",
                (assessment_id, decision, reviewer.strip(), notes.strip(), now, a["assessment_status"]),
            ),
            (
                "UPDATE impact_assessments SET assessment_status = ?, status_reason = ?, "
                "actor_type = 'human', "
                "changed_by = ?, change_reason = ?, current_revision = current_revision + 1, "
                "updated_at_utc = ?, "
                "last_review_id = (SELECT MAX(review_id) FROM impact_reviews WHERE assessment_id = ?) "
                "WHERE assessment_id = ? AND current_revision = ?",
                (
                    status,
                    reason,
                    reviewer.strip(),
                    f"human review: {decision}: {notes.strip()}"[:900],
                    now,
                    assessment_id,
                    assessment_id,
                    a["current_revision"],
                ),
            ),
        ]
    )
    return dict(db.execute("SELECT * FROM impact_assessments WHERE assessment_id = ?", (assessment_id,))[0])


def record_exposure_review(
    db: Database, candidate_id: int, decision: str, *, reviewer: str, notes: str
) -> dict:
    """Explicit human decision on an exposure candidate (existing Phase 4 review, unchanged rules)."""
    return exposure_mapping.review(db, candidate_id, decision, reviewer=reviewer, notes=notes)


def review_history(db: Database, assessment_id: int) -> list[dict]:
    return [
        dict(r)
        for r in db.execute(
            "SELECT revision_no, recorded_at_utc, previous_status, new_status, status_reason, actor_type, "
            "actor, "
            "review_id FROM impact_assessment_revisions WHERE assessment_id = ? ORDER BY revision_no",
            (assessment_id,),
        )
    ]
