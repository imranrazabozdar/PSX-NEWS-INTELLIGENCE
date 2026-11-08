"""Run Phase 3 over stored source items and persist results with full provenance.

Writes are additive: extractions and LLM calls are append-only, events are created through the
Phase 1 repository (which records revision 1), and each verified claim gets an evidence row
with its verbatim excerpt. Clusters link items that report the same story.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from database import repositories as repo
from database.canonical import now_utc
from engines import schema, similarity, verification
from engines.extraction import ExtractionResult, extract
from engines.llm import LLMGateway

ITEM_SQL = """SELECT i.source_item_id, i.source_id, i.title, i.permitted_excerpt AS text,
       i.original_url, i.canonical_url, i.retrieval_method, i.published_at_utc, i.published_at_raw,
       i.published_tz_offset, i.publication_time_status, i.collected_at_utc, i.access_status,
       i.duplicate_of_item_id, s.reliability_tier, s.owner, s.name AS source_name,
       s.licensing_status AS licence_status, s.lifecycle_status AS data_status
FROM source_items i JOIN sources s USING(source_id)
WHERE s.access_status NOT IN ('restricted','licence_required','blocked')
  AND i.permitted_excerpt IS NOT NULL
  AND i.source_item_id NOT IN (SELECT source_item_id FROM event_extractions
                              WHERE schema_version = 'event-extraction/1')
ORDER BY i.source_item_id LIMIT ?"""


@dataclass
class RunSummary:
    processed: int = 0
    events_created: int = 0
    review_flags: int = 0
    statuses: dict = field(default_factory=dict)
    clusters: int = 0


def _resolver(db):
    def resolve(name: str) -> list[dict]:
        return repo.resolve_alias(db, name)
    return resolve


def _store_extraction(db, res: ExtractionResult, event_id: int | None, cand=None) -> None:
    reasons = list(res.review_reasons) + (cand.review_reasons if cand else [])
    db.execute(
        """INSERT INTO event_extractions(source_item_id, event_id, call_id, schema_version,
               prompt_version, model, extracted_json, confidence, confidence_explanation,
               needs_human_review, review_reasons_json, provenance_json, created_at_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_item_id, schema_version, prompt_version, model) DO NOTHING""",
        (res.source_item_id, event_id, res.call_id, schema.SCHEMA_VERSION,
         res.prompt.version if res.prompt else "none", res.model or "none",
         json.dumps({"status": res.status, "event": cand.event if cand else None,
                     "raw": res.raw}, sort_keys=True),
         cand.confidence if cand else None,
         "; ".join(cand.confidence_explanation) if cand else res.status,
         int(bool(reasons)), json.dumps(reasons), json.dumps(res.provenance, sort_keys=True), now_utc()))


def run(db, gateway: LLMGateway, *, limit: int = 20) -> RunSummary:
    summary = RunSummary()
    items = db.execute(ITEM_SQL, (limit,))
    reports: dict[int, list[tuple[verification.Report, int]]] = {}
    docs = []
    for row in items:
        item = dict(row)
        item["provider"] = item["source_id"]
        item["original_source"] = item.pop("source_name")
        item["text"] = item["text"] or ""
        res = extract(item, gateway, resolve_company=_resolver(db))
        summary.processed += 1
        summary.statuses[res.status] = summary.statuses.get(res.status, 0) + 1
        if not res.candidates:
            _store_extraction(db, res, None)
            summary.review_flags += int(res.needs_human_review)
            continue
        for cand in res.candidates:
            ev = cand.event
            event_id = repo.create_event(db, {
                "event_type": ev["event_type"], "headline": ev["headline"], "summary": ev["summary"],
                "event_date": ev["event_date"], "event_date_precision": ev["event_date_precision"],
                "geography": ev["geography"], "status_stage": ev["status_stage"],
                "verification_state": "single_source", "direction": ev["direction"],
                "magnitude": ev["magnitude"], "horizon": ev["horizon"], "confidence": cand.confidence,
                "first_seen_at_utc": item["published_at_utc"] or item["collected_at_utc"],
            }, changed_by="phase3-pipeline", reason="extracted", model_version=res.model,
                prompt_version=res.prompt.version)
            summary.events_created += 1
            for claim in ev["claims"]:
                repo.add_evidence(db, event_id=event_id, source_item_id=item["source_item_id"],
                                  claim=claim["claim"], claim_type=claim["claim_type"],
                                  relation="supports", excerpt=claim["quote"][:1000],
                                  recorded_by="phase3-pipeline")
            _store_extraction(db, res, event_id, cand)
            summary.review_flags += int(bool(cand.review_reasons or res.review_reasons))
            reports.setdefault(item["source_item_id"], []).append((verification.Report(
                item["source_item_id"], item["source_id"], item.get("owner") or item["source_id"],
                item["reliability_tier"], item["published_at_utc"], ev, cand.confidence,
                item["duplicate_of_item_id"]), event_id))
        docs.append(similarity.Doc(item["source_item_id"], item["title"] or "", item["text"],
                                   item["published_at_utc"],
                                   frozenset(e["name"].casefold() for c in res.candidates
                                             for e in c.event["entities"])))
    for cl in similarity.cluster(docs):
        if len(cl.members) < 2:
            continue
        summary.clusters += _persist_cluster(db, cl, reports)
    return summary


def _persist_cluster(db, cl: similarity.Cluster, reports) -> int:
    key = "items:" + ",".join(map(str, cl.members))
    db.execute("INSERT INTO story_clusters(cluster_key, created_at_utc) VALUES (?,?) "
               "ON CONFLICT(cluster_key) DO NOTHING", (key, now_utc()))
    cid = db.execute("SELECT cluster_id FROM story_clusters WHERE cluster_key=?", (key,))[0]["cluster_id"]
    first = cl.members[0]
    for m in cl.members:
        sim = 1.0 if m == first else max((s for (a, b), s in cl.links.items() if m in (a, b)), default=0.0)
        db.execute("INSERT INTO story_cluster_members VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                   (cid, m, sim, int(m in cl.near_duplicates), now_utc()))
    groups: dict[tuple, list] = {}
    for m in cl.members:
        for rep, event_id in reports.get(m, []):
            if m in cl.near_duplicates:
                rep.duplicate_of = cl.near_duplicates[m]
            groups.setdefault(verification.event_key(rep.event), []).append((rep, event_id))
    for pairs in groups.values():
        if len(pairs) < 2:
            continue
        a = verification.assess([p[0] for p in pairs])
        for _rep, event_id in pairs:
            repo.revise_event(db, event_id, {"verification_state": a.verification_state,
                                             "confidence": a.confidence},
                              reason="cross-source assessment: " + " | ".join(a.explanation)[:900],
                              changed_by="phase3-verification")
    return 1
