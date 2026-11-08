"""Stage 2, Component 1: deterministic headline event builder.

Design: docs/STAGE_2_NEWS_INTELLIGENCE_DESIGN.md §3A and §10. Turns stored news headlines (RSS metadata:
title, link, timestamps; no article text) into events in the existing event layer, with no AI and no
schema change:

* Eligible input: `source_items` from `news_media` / `government` sources that have no processing record for
  this builder version yet, oldest first. Each eligible item gets exactly one `event_extractions` row
  (`schema_version = headline-event/1`, `model = deterministic`), which is also its "processed" marker.
* Outcome per item:
  * NEW: no matching recent event. One event (`event_type = other`, `verification_state = unverified`, stage
    not assessed) and its first revision, plus one evidence row.
  * UPDATE: same story as a recent event, and the headline adds a figure that none of the event's earlier
    headlines contain. Evidence is attached and a new event revision (`novelty = update`) is recorded.
  * REPEAT: a stored cross-feed duplicate, a near-identical headline, or the same story with nothing new.
    Evidence is attached; the event itself is unchanged.
  * SKIPPED: empty or too-short headline. Only the processing record (needs review), with no event.
* Evidence is the exact headline (claim and excerpt), `claim_type = news_report`, verification `unverified`,
  marked headline-only in the provenance. Independence: 0 for duplicates and near-identical copies; otherwise
  NULL (not assessed: corroboration is Component 4). It is never set to 1 here.
* Each item's writes are ONE transaction. The processing-record insert has no conflict clause, so a retry or a
  concurrent run that already processed the item rolls back completely and is counted as already done.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from database.canonical import now_utc
from database.connection import Database, DatabaseBudgetError, DatabaseError
from engines import similarity

SCHEMA_VERSION = "headline-event/1"
MODEL = "deterministic"
PROMPT_VERSION = "none"
RECORDED_BY = "headline-event-builder/1"
MIN_TOKENS = 3  # fewer meaningful words than this: too ambiguous to become an event
EXPLANATION = ("headline only: not verified against article text or a primary source; "
               "type, stage, direction and companies not assessed (later components)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")

ITEM_SQL = """SELECT i.source_item_id, i.source_id, i.title, i.original_url, i.canonical_url,
       i.published_at_utc, i.publication_time_status, i.collected_at_utc, i.duplicate_of_item_id,
       s.name AS publisher, s.owner, s.reliability_tier
FROM source_items i JOIN sources s USING(source_id)
WHERE s.source_type IN ('news_media', 'government')
  AND NOT EXISTS (SELECT 1 FROM event_extractions x WHERE x.source_item_id = i.source_item_id
                  AND x.schema_version = ? AND x.model = ? AND x.prompt_version = ?)
ORDER BY i.source_item_id LIMIT ?"""


@dataclass
class Summary:
    processed: int = 0
    already_processed: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stopped_at_budget: bool = False


def _when(item: dict) -> str:
    return item["published_at_utc"] or item["collected_at_utc"]


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))


def _candidates(db: Database, when: str) -> dict[int, list[dict]]:
    """Recent events built by this builder (within the story window) with their evidence headlines."""
    t = datetime.fromisoformat(when.replace("Z", "+00:00"))
    lo = (t - timedelta(hours=similarity.WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hi = (t + timedelta(hours=similarity.WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.execute(
        """SELECT v.event_id, v.source_item_id, v.excerpt, si.published_at_utc
           FROM event_evidence v JOIN events e USING(event_id) JOIN source_items si USING(source_item_id)
           WHERE v.recorded_by = ? AND e.first_seen_at_utc BETWEEN ? AND ?
           ORDER BY v.event_id, v.evidence_id""",
        (RECORDED_BY, lo, hi),
    )
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["event_id"], []).append(r)
    return out


def decide(db: Database, item: dict) -> dict:
    """Pure decision (reads only): {outcome, event_id, similarity, independent, reason}."""
    title = (item["title"] or "").strip()
    if len(similarity.tokens(title)) < MIN_TOKENS:
        return {"outcome": "SKIPPED", "event_id": None, "similarity": None, "independent": None,
                "reason": "empty or too-short headline: too ambiguous to form an event"}
    if item["duplicate_of_item_id"] is not None:
        orig = db.execute(
            "SELECT event_id FROM event_extractions WHERE source_item_id = ? AND schema_version = ? "
            "AND model = ? AND event_id IS NOT NULL", (item["duplicate_of_item_id"], SCHEMA_VERSION, MODEL))
        if orig:
            return {"outcome": "REPEAT", "event_id": orig[0]["event_id"], "similarity": 1.0, "independent": 0,
                    "reason": f"stored duplicate of item {item['duplicate_of_item_id']}"}
    doc = similarity.Doc(item["source_item_id"], title, title, item["published_at_utc"])
    best = None
    for event_id, evidence in _candidates(db, _when(item)).items():
        for ev in evidence:
            score, near = similarity.similarity(doc, similarity.Doc(ev["source_item_id"], ev["excerpt"],
                                                                    ev["excerpt"], ev["published_at_utc"]))
            if (near or score >= similarity.SAME_STORY) and (best is None or (near, score) > best[:2]):
                best = (near, score, event_id, evidence)
    if best is None:
        return {"outcome": "NEW", "event_id": None, "similarity": None, "independent": None,
                "reason": "no matching recent event"}
    near, score, event_id, evidence = best
    if near:
        return {"outcome": "REPEAT", "event_id": event_id, "similarity": score, "independent": 0,
                "reason": "near-identical headline already recorded"}
    new_figures = _numbers(title) - set().union(*(_numbers(e["excerpt"]) for e in evidence))
    if new_figures:
        return {"outcome": "UPDATE", "event_id": event_id, "similarity": score, "independent": None,
                "reason": "same story; headline adds figure(s) " + ", ".join(sorted(new_figures))}
    return {"outcome": "REPEAT", "event_id": event_id, "similarity": score, "independent": None,
            "reason": "same story; no new figure in the headline"}


def _provenance(item: dict) -> str:
    return json.dumps({
        "evidence_basis": "headline_only", "article_text_available": False,
        "source_id": item["source_id"], "publisher": item["publisher"], "owner": item["owner"],
        "reliability_tier": item["reliability_tier"],
        "url": item["canonical_url"] or item["original_url"], "original_url": item["original_url"],
        "published_at_utc": item["published_at_utc"],
        "publication_time_status": item["publication_time_status"],
        "collected_at_utc": item["collected_at_utc"], "duplicate_of_item_id": item["duplicate_of_item_id"],
    }, sort_keys=True)


def _extraction(item: dict, d: dict, event_sql: str | None) -> tuple[str, list]:
    """INSERT of the processing record. No conflict clause: a second attempt aborts its whole transaction."""
    payload = json.dumps({"outcome": d["outcome"], "matched_event_id": d["event_id"],
                          "similarity": d["similarity"], "reason": d["reason"],
                          "evidence_basis": "headline_only"}, sort_keys=True)
    skipped = d["outcome"] == "SKIPPED"
    reasons = json.dumps([d["reason"]] if skipped else [])
    event_expr = "NULL" if event_sql is None else event_sql
    # event_expr is NULL, an integer id, or a fixed sub-select from this module: never external input
    sql = ("INSERT INTO event_extractions(source_item_id, event_id, call_id, schema_version, "  # noqa: S608
           "prompt_version, model, extracted_json, confidence, confidence_explanation, needs_human_review, "
           "review_reasons_json, provenance_json, created_at_utc) "
           f"VALUES (?, {event_expr}, NULL, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)")
    return sql, [item["source_item_id"], SCHEMA_VERSION, PROMPT_VERSION, MODEL, payload,
                 d["reason"] if skipped else EXPLANATION, int(skipped), reasons, _provenance(item), now_utc()]


def _evidence(item: dict, event_sql: str, independent) -> tuple[str, list]:
    title = item["title"].strip()[:1000]
    # event_sql is an integer id or last_insert_rowid(): never external input
    return ("INSERT INTO event_evidence(event_id, source_item_id, claim, claim_type, relation, "  # noqa: S608
            "excerpt, verification_state, is_independent, recorded_at_utc, recorded_by) "
            f"VALUES ({event_sql}, ?, ?, 'news_report', 'supports', ?, 'unverified', ?, ?, ?)",
            [item["source_item_id"], title, title, independent, now_utc(), RECORDED_BY])


def _statements(item: dict, d: dict) -> list[tuple[str, list]]:
    now = now_utc()
    if d["outcome"] == "SKIPPED":
        return [_extraction(item, d, None)]
    if d["outcome"] == "NEW":
        title = item["title"].strip()
        snapshot = json.dumps({"event_type": "other", "headline": title, "status_stage": "not_applicable",
                               "verification_state": "unverified", "novelty": "new"}, sort_keys=True)
        # last_insert_rowid() chains the new ids inside this one transaction: event -> evidence -> revision
        return [
            ("INSERT INTO events(event_type, headline, summary, event_date_precision, status_stage, "
             "verification_state, novelty, first_seen_at_utc, current_revision, created_at_utc, "
             "updated_at_utc) "
             "VALUES ('other', ?, ?, 'unknown', 'not_applicable', 'unverified', 'new', ?, 1, ?, ?)",
             [title, "Headline only; stage, type and impact not assessed.", _when(item), now, now]),
            _evidence(item, "last_insert_rowid()", d["independent"]),
            ("INSERT INTO event_revisions(event_id, revision_no, recorded_at_utc, status_stage, "
             "verification_state, headline, summary, snapshot_json, change_reason, changed_by, "
             "model_version, prompt_version) SELECT event_id, 1, ?, 'not_applicable', 'unverified', ?, ?, ?, "
             "'created from headline', ?, ?, ? "
             "FROM event_evidence WHERE evidence_id = last_insert_rowid()",
             [now, title, "Headline only; stage, type and impact not assessed.", snapshot, RECORDED_BY, MODEL,
              PROMPT_VERSION]),
            _extraction(item, d, "(SELECT event_id FROM event_revisions WHERE rowid = last_insert_rowid())"),
        ]
    eid = int(d["event_id"])
    stmts = [_evidence(item, str(eid), d["independent"])]
    if d["outcome"] == "UPDATE":
        stmts += [
            ("INSERT INTO event_revisions(event_id, revision_no, recorded_at_utc, status_stage, "
             "verification_state, headline, summary, snapshot_json, change_reason, changed_by, "
             "model_version, prompt_version) SELECT event_id, current_revision + 1, ?, status_stage, "
             "verification_state, headline, summary, "
             "json_object('novelty', 'update', 'update_item', ?), ?, ?, ?, ? FROM events WHERE event_id = ?",
             [now, item["source_item_id"], ("update from headline: " + d["reason"])[:900], RECORDED_BY, MODEL,
              PROMPT_VERSION, eid]),
            ("UPDATE events SET novelty = 'update', current_revision = current_revision + 1, "
             "updated_at_utc = ? WHERE event_id = ?", [now, eid]),
        ]
    return stmts + [_extraction(item, d, str(eid))]


def _done(db: Database, source_item_id: int) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM event_extractions WHERE source_item_id = ? AND schema_version = ? AND model = ? "
        "AND prompt_version = ?", (source_item_id, SCHEMA_VERSION, MODEL, PROMPT_VERSION)))


def process_item(db: Database, item: dict) -> str:
    """Process one item atomically. Returns the outcome, or 'ALREADY_PROCESSED'."""
    d = decide(db, item)
    try:
        db.batch(_statements(item, d))
    except DatabaseBudgetError:
        raise
    except DatabaseError:
        if _done(db, item["source_item_id"]):  # a concurrent run or an earlier retry got there first
            return "ALREADY_PROCESSED"
        raise
    return d["outcome"]


def run(db: Database, *, limit: int = 200) -> Summary:
    """Process up to `limit` eligible items, oldest first. Safe to re-run at any time."""
    s = Summary()
    for row in db.execute(ITEM_SQL, (SCHEMA_VERSION, MODEL, PROMPT_VERSION, limit)):
        item = dict(row)
        try:
            outcome = process_item(db, item)
        except DatabaseBudgetError:
            s.stopped_at_budget = True
            break
        except DatabaseError as exc:  # isolated: this item stays eligible for the next run
            s.errors.append(f"item {item['source_item_id']}: {str(exc)[:200]}")
            continue
        except (ValueError, TypeError) as exc:
            # A malformed stored value (e.g. an unparseable timestamp) fails before anything is written, so
            # nothing is recorded for this item: it stays eligible and is reported, and later items still
            # run. Other exceptions (programming errors) are not caught and stop the run.
            s.errors.append(f"item {item['source_item_id']}: invalid item data: {type(exc).__name__}: "
                            f"{str(exc)[:160]}")
            continue
        if outcome == "ALREADY_PROCESSED":
            s.already_processed += 1
            continue
        s.processed += 1
        s.outcomes[outcome] = s.outcomes.get(outcome, 0) + 1
    return s


def main(argv: list[str] | None = None) -> int:
    """Local only: runs against a SQLite file. No Turso path exists in this component."""
    import argparse

    from database.connection import SQLiteDatabase

    ap = argparse.ArgumentParser(description="Build headline events into a LOCAL SQLite database")
    ap.add_argument("--local-db", required=True, help="path to a local SQLite database file")
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
