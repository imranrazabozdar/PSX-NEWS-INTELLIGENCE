"""Event-to-company exposure mapping (Phase 4).

``map_event`` turns one stored event into exposure candidates with deterministic rules:
companies named in the event, rule links to documented company exposures, subsidiary and
associate links, and sector-level candidates when nothing company-specific is documented.
``suggest_with_llm`` (optional) asks the Phase 3 gateway for suggestions, then validates them
deterministically. ``review`` records an append-only human decision.

Evidence status is assigned by fixed rules, never from model confidence:
* confirmed          - strongly supported AND accepted by a human reviewer;
* strongly_supported - company-specific evidence from approved (ACTIVE) sources and a
                       corroborated or primary-confirmed event, with no contradiction;
* potential          - company-specific evidence from approved sources, but the event is
                       single-source, unverified or disputed;
* unverified         - no company-specific evidence, or evidence only from sources that are
                       not approved (today: every source, since none is ACTIVE);
* rejected           - failed validation or rejected by a reviewer.
No impact size or share-price effect is estimated here (that is Phase 5).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from database.canonical import now_utc
from engines import exposure_rules as rules
from engines import exposure_taxonomy as tax
from engines.entity_resolution import resolve
from engines.extraction import normalise_for_match

SCHEMA_VERSION = "exposure-candidate/1"
STRONG_EVENT_STATES = ("primary_confirmed", "corroborated")
BASE_CONFIDENCE = {"company_evidence_approved": 0.75, "company_evidence_unapproved": 0.45,
                   "named_in_event": 0.5, "relationship": 0.4, "sector_only": 0.2, "llm": 0.3}
NAMED_EVENT_CATEGORY = {
    "regulatory_action": ("regulatory", "regulator_decision"),
    "tax_policy": ("regulatory", "taxes_duties"), "trade_policy": ("regulatory", "trade_restrictions"),
    "energy_policy": ("regulatory", "government_notification"),
    "fiscal_policy": ("macroeconomic", "fiscal_policy"),
    "commodity_supply": ("operational", "supply_chain"),
    "geopolitical": ("geopolitical", "regional_conflict"),
    "security_incident": ("geopolitical", "regional_conflict"),
}
DEFAULT_NAMED = ("sector", "sector_development")


@dataclass
class Candidate:
    company: dict
    category: str
    subtype: str
    level: str
    direction: str
    mechanism: str
    basis: str                       # key of BASE_CONFIDENCE
    claim_evidence_ids: list[int] = field(default_factory=list)
    exposure_evidence: list[dict] = field(default_factory=list)   # [{"table": ..., "id": ...}]
    source_item_ids: list[int] = field(default_factory=list)
    segment_id: int | None = None
    rule_id: str | None = None
    origin: str = "rule"
    review_reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    relationship_status: str | None = None
    entity_confidence: float = 1.0
    model: str | None = None
    prompt_version: str | None = None
    evidence_status: str = "unverified"
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class MappingResult:
    event_id: int
    candidates: list[Candidate] = field(default_factory=list)
    unresolved_mentions: list[dict] = field(default_factory=list)
    rejected_suggestions: list[dict] = field(default_factory=list)
    stored: dict = field(default_factory=lambda: {"created": 0, "revised": 0, "unchanged": 0})


# ---------------------------------------------------------------- loading
def load_event(db, event_id: int) -> dict:
    rows = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    if not rows:
        raise ValueError(f"event {event_id} not found")
    ev = dict(rows[0])
    ext = db.execute("SELECT extracted_json FROM event_extractions WHERE event_id = ? "
                     "ORDER BY extraction_id DESC LIMIT 1", (event_id,))
    payload = json.loads(ext[0]["extracted_json"]).get("event") if ext else None
    payload = payload or {}
    for key in ("entities", "indicators", "claims"):
        ev[key] = payload.get(key, [])
    ev["evidence"] = db.execute(
        "SELECT e.evidence_id, e.source_item_id, e.claim, e.claim_type, e.relation, e.excerpt, i.source_id "
        "FROM event_evidence e JOIN source_items i USING(source_item_id) WHERE e.event_id = ? "
        "ORDER BY e.evidence_id", (event_id,))
    if not ev["claims"]:
        ev["claims"] = [{"claim": r["claim"], "claim_type": r["claim_type"], "quote": r["excerpt"]}
                        for r in ev["evidence"]]
    return ev


def _approved_sources(db, source_item_ids: list[int]) -> bool:
    if not source_item_ids:
        return False
    marks = ",".join("?" * len(source_item_ids))
    rows = db.execute(f"SELECT DISTINCT s.lifecycle_status, s.terms_status FROM source_items i "  # noqa: S608
                      f"JOIN sources s USING(source_id) WHERE i.source_item_id IN ({marks})",
                      tuple(source_item_ids))
    return bool(rows) and all(r["lifecycle_status"] == "ACTIVE" and r["terms_status"] == "approved"
                              for r in rows)


def _valid_at(row: dict, as_of: str | None) -> bool:
    if as_of is None:
        return row.get("valid_to") is None
    return ((row.get("valid_from") is None or row["valid_from"] <= as_of)
            and (row.get("valid_to") is None or row["valid_to"] >= as_of))


def _company_by_id(db, company_id: str) -> dict:
    return db.execute("SELECT c.company_id, c.legal_name, c.listing_status, "
                      "(SELECT value FROM company_identifiers i WHERE i.company_id = c.company_id "
                      " AND i.id_type='psx_ticker' ORDER BY i.valid_to IS NULL DESC LIMIT 1) AS psx_symbol "
                      "FROM companies c WHERE c.company_id = ?", (company_id,))[0]


# ---------------------------------------------------------------- candidate generation
def _named_companies(db, ev: dict, result: MappingResult) -> list[Candidate]:
    out = []
    as_of = (ev.get("event_date") or "")[:10] or None
    category, subtype = NAMED_EVENT_CATEGORY.get(ev["event_type"], DEFAULT_NAMED)
    if ev["event_type"].startswith("corporate_") or ev["event_type"] == "management_change":
        category, subtype = "operational", "production_facilities"
    for ent in ev.get("entities", []):
        if ent.get("entity_type") != "company":
            continue
        res = resolve(db, ent["name"], as_of=as_of)
        if res.status not in ("resolved", "historical"):
            result.unresolved_mentions.append({"mention": ent["name"], "status": res.status,
                                               "candidates": [c.get("psx_symbol") for c in res.candidates],
                                               "reasons": res.reasons})
            continue
        needle = normalise_for_match(ent.get("quote") or ent["name"])
        ev_ids = [r["evidence_id"] for r in ev["evidence"] if needle in normalise_for_match(r["excerpt"])]
        c = Candidate(res.company, category, subtype, "direct", "unknown",
                      f"named in the event ('{ent['name']}')", "named_in_event",
                      claim_evidence_ids=[r["evidence_id"] for r in ev["evidence"]],
                      exposure_evidence=[{"table": "event_evidence", "id": i} for i in ev_ids],
                      source_item_ids=sorted({r["source_item_id"] for r in ev["evidence"]}),
                      entity_confidence=res.confidence)
        if not ev_ids:
            c.missing.append("no stored evidence excerpt names this company")
        if res.needs_review:
            c.review_reasons.append(f"entity match '{ent['name']}' via {res.method} needs confirmation")
        if res.status == "historical":
            c.review_reasons.append("historical company (delisted after the event date)")
        c.missing.append("direction cannot be set from a mention alone; Phase 5 analysis needed")
        out.append(c)
    return out


def _rule_candidates(db, ev: dict) -> list[Candidate]:
    out = []
    as_of = (ev.get("event_date") or "")[:10] or None
    text = rules.scope_terms(ev)
    exposures = [r for r in db.execute("SELECT * FROM company_exposures") if _valid_at(r, as_of)]
    for rule, change in rules.matching_rules(ev):
        covered = set()
        for link in rule.links:
            for x in exposures:
                if x["exposure_kind"] not in link.exposure_kinds:
                    continue
                if not re.search(link.subject_pattern, x["subject"], re.I):
                    continue
                if rule.rule_id == "R-DUTY-1" and x["subject"].casefold() not in text:
                    continue  # tax/duty rules only map companies whose product/input is in scope
                sign = None if (link.sign_if_up is None or change is None) else link.sign_if_up * change
                if link.sign_if_up == 0:
                    sign = 0
                c = Candidate(_company_by_id(db, x["company_id"]), link.category, link.subtype, link.level,
                              tax.combine([sign]), f"{link.mechanism} (documented exposure: {x['subject']})",
                              "company_evidence_unapproved", rule_id=rule.rule_id,
                              claim_evidence_ids=[r["evidence_id"] for r in ev["evidence"]],
                              exposure_evidence=[{"table": "company_exposures", "id": x["exposure_id"]}],
                              source_item_ids=sorted({x["source_item_id"]} |
                                                     {r["source_item_id"] for r in ev["evidence"]}),
                              segment_id=x["segment_id"])
                if change is None:
                    c.missing.append("the event text does not state the direction of the change")
                if link.sign_if_up is None:
                    c.missing.append("rule cannot sign this exposure; needs company-specific analysis")
                if x["confidence"] != "documented":
                    c.review_reasons.append(f"company exposure is only '{x['confidence']}'")
                covered.add(x["company_id"])
                out.append(c)
        for sector_id in rule.sector_candidates:
            rows = db.execute("SELECT company_id FROM company_classifications WHERE sector_id = ? "
                              "AND valid_to IS NULL", (sector_id,))
            for r in rows:
                if r["company_id"] in covered:
                    continue
                comp = _company_by_id(db, r["company_id"])
                if comp["listing_status"] != "listed":
                    continue
                c = Candidate(comp, rule.sector_category, rule.sector_subtype, "indirect", "unknown",
                              f"sector-level candidate: {sector_id} may be exposed to {rule.driver}",
                              "sector_only", rule_id=rule.rule_id,
                              claim_evidence_ids=[e["evidence_id"] for e in ev["evidence"]],
                              source_item_ids=sorted({e["source_item_id"] for e in ev["evidence"]}))
                c.missing.append("no company-specific exposure evidence; "
                                 "sector membership alone is not proof")
                out.append(c)
    return out


def _relationship_candidates(db, ev: dict, base: list[Candidate]) -> list[Candidate]:
    out = []
    as_of = (ev.get("event_date") or "")[:10] or None
    mapped = {c.company["company_id"]: c for c in base}
    mentioned = {normalise_for_match(e["name"]) for e in ev.get("entities", [])}
    for rel in db.execute("SELECT * FROM current_company_relationships"):
        if not _valid_at(rel, as_of) or rel["evidence_status"] == "rejected":
            continue
        via = mapped.get(rel["child_company_id"]) if rel["child_company_id"] else None
        if via is None and normalise_for_match(rel["child_name"]) not in mentioned:
            continue
        parent = _company_by_id(db, rel["parent_company_id"])
        c = Candidate(parent, via.category if via else "operational",
                      via.subtype if via else "production_facilities", "indirect",
                      via.direction if via and rel["relationship_type"] == "subsidiary" else "unknown",
                      f"through its {rel['relationship_type']} {rel['child_name']}", "relationship",
                      claim_evidence_ids=[e["evidence_id"] for e in ev["evidence"]],
                      # only the relationship itself is the parent's company-specific evidence; the
                      # child's own exposure rows belong to the child and are cited in the mechanism
                      exposure_evidence=[{"table": "company_relationships", "id": rel["relationship_id"]}],
                      source_item_ids=sorted(({rel["source_item_id"]} if rel["source_item_id"] else set())
                                             | set(via.source_item_ids if via else [])),
                      rule_id="R-REL-1", relationship_status=rel["evidence_status"])
        if rel["evidence_status"] not in ("confirmed", "strongly_supported"):
            c.review_reasons.append(f"{rel['relationship_type']} relationship is {rel['evidence_status']}")
        if not rel["source_item_id"]:
            c.exposure_evidence = []
            c.missing.append("relationship has no cited source")
        if rel["ownership_pct"] is None:
            c.missing.append("ownership percentage not documented")
        out.append(c)
    return out


# ---------------------------------------------------------------- evidence status and confidence
def _assess(db, ev: dict, c: Candidate, contradictory: set[str]) -> None:
    approved = _approved_sources(db, c.source_item_ids) if c.exposure_evidence else False
    if c.basis == "company_evidence_unapproved" and approved:
        c.basis = "company_evidence_approved"
    reasons = c.review_reasons
    if not c.exposure_evidence:
        status = "unverified"
    elif not approved:
        status = "unverified"
        c.missing.append("cited sources are not approved (no source is ACTIVE)")
    elif (ev["verification_state"] in STRONG_EVENT_STATES and c.company["company_id"] not in contradictory
          and c.relationship_status in (None, "confirmed", "strongly_supported") and c.origin == "rule"):
        status = "strongly_supported"
    else:
        status = "potential"
    if c.origin == "llm_suggestion" and status in ("strongly_supported", "confirmed"):
        status = "potential"   # suggestions stay suggestions until a rule or reviewer confirms them
    c.evidence_status = status

    ev_conf = ev.get("confidence") if ev.get("confidence") is not None else 0.5
    conf = BASE_CONFIDENCE[c.basis] * (0.5 + 0.5 * ev_conf) * c.entity_confidence
    if c.relationship_status and c.relationship_status not in ("confirmed", "strongly_supported"):
        conf *= 0.6
    if c.company["company_id"] in contradictory:
        conf -= 0.2
    c.confidence = round(max(0.0, min(1.0, conf)), 3)

    if ev["status_stage"] == "rumour" or any(cl.get("claim_type") == "rumour" for cl in ev.get("claims", [])):
        reasons.append("event is a rumour or speculative claim")
    if ev["magnitude"] == "high" and ev["verification_state"] not in STRONG_EVENT_STATES:
        reasons.append("high-impact event supported by a single or unverified source")
    if ev["verification_state"] in ("disputed", "refuted"):
        reasons.append(f"event is {ev['verification_state']}")
    if c.company["company_id"] in contradictory:
        reasons.append("contradictory exposure evidence for this company")
    if c.level == "direct" and status == "unverified":
        reasons.append("material (direct) mapping without approved company-specific evidence")
    if status == "unverified" and not any("not approved" in m or "sector" in m for m in c.missing):
        c.missing.append("no approved company-specific evidence")
    symbol = c.company.get("psx_symbol") or "no symbol"
    c.explanation = (f"{c.company['legal_name']} ({symbol}): {c.mechanism}. "
                     f"Evidence status {status}; confidence {c.confidence} from basis '{c.basis}', "
                     f"event verification '{ev['verification_state']}'. Confidence is not proof.")


def _contradictions(cands: list[Candidate]) -> set[str]:
    by: dict[tuple, set[str]] = {}
    for c in cands:
        if c.rule_id and c.direction in ("positive", "negative"):
            by.setdefault((c.company["company_id"], c.rule_id), set()).add(c.direction)
    return {cid for (cid, _), dirs in by.items() if len(dirs) > 1}


# ---------------------------------------------------------------- persistence
# Evidence is stored as rows in exposure_candidate_evidence (real foreign keys, checked by triggers),
# revisions are written by database triggers, and status changes above 'unverified' are re-checked
# by the database against the linked evidence and approved sources.
_MATERIAL = ("impact_direction", "exposure_level", "evidence_status", "review_status", "confidence",
             "explanation", "missing_evidence_json", "review_reasons_json", "segment_id")
_KEY = ("event_id", "company_id", "exposure_category", "exposure_subtype", "mechanism", "ruleset_version")
_WHERE_KEY = " AND ".join(f"{k} = ?" for k in _KEY)   # fixed column names only


def _row(ev_id: int, c: Candidate, synthetic: bool) -> dict:
    return {
        "event_id": ev_id, "company_id": c.company["company_id"], "psx_symbol": c.company.get("psx_symbol"),
        "exposure_category": c.category, "exposure_subtype": c.subtype, "exposure_level": c.level,
        "impact_direction": c.direction, "segment_id": c.segment_id, "mechanism": c.mechanism,
        "explanation": c.explanation, "missing_evidence_json": json.dumps(sorted(set(c.missing))),
        "confidence": c.confidence, "evidence_status": c.evidence_status,
        "review_status": "rejected" if c.evidence_status == "rejected"
        else ("needs_review" if c.review_reasons or c.evidence_status == "unverified" else "pending"),
        "review_reasons_json": json.dumps(sorted(set(c.review_reasons))), "origin": c.origin,
        "rule_id": c.rule_id, "ruleset_version": rules.RULESET_VERSION, "model": c.model,
        "prompt_version": c.prompt_version, "schema_version": SCHEMA_VERSION, "is_synthetic": int(synthetic),
    }


def _links(db, ev: dict, c: Candidate) -> list[tuple]:
    """(role, event_evidence_id, company_exposure_id, relationship_id, source_item_id) rows to link."""
    out = []
    by_ev = {r["evidence_id"]: r["source_item_id"] for r in ev["evidence"]}
    for eid in sorted(set(c.claim_evidence_ids)):
        if eid in by_ev:
            out.append(("claim", eid, None, None, by_ev[eid]))
    for ref in c.exposure_evidence:
        if ref["table"] == "event_evidence" and ref["id"] in by_ev:
            out.append(("company_specific", ref["id"], None, None, by_ev[ref["id"]]))
        elif ref["table"] == "company_exposures":
            row = db.execute("SELECT source_item_id FROM company_exposures WHERE exposure_id = ?",
                             (ref["id"],))
            if row:
                out.append(("company_specific", None, ref["id"], None, row[0]["source_item_id"]))
        elif ref["table"] == "company_relationships":
            row = db.execute("SELECT source_item_id FROM company_relationships WHERE relationship_id = ?",
                             (ref["id"],))
            if row and row[0]["source_item_id"] is not None:
                out.append(("company_specific", None, None, ref["id"], row[0]["source_item_id"]))
    return sorted(set(out), key=lambda t: tuple(-1 if v is None else v for v in t[1:]) + (t[0],))


def _link_stmt(key_vals: tuple, link: tuple, now: str):
    sql = ("INSERT INTO exposure_candidate_evidence(candidate_id, role, event_evidence_id, "  # noqa: S608
           "company_exposure_id, relationship_id, source_item_id, added_at_utc) "
           "SELECT candidate_id, ?, ?, ?, ?, ?, ? FROM exposure_candidates WHERE " + _WHERE_KEY)
    return sql, (*link, now, *key_vals)


def _store(db, row: dict, links: list[tuple], changed_by: str) -> str:
    now = now_utc()
    key_vals = tuple(row[k] for k in _KEY)
    existing = db.execute(f"SELECT * FROM exposure_candidates WHERE {_WHERE_KEY}", key_vals)  # noqa: S608
    stmts = []
    if not existing:
        first = "rejected" if row["evidence_status"] == "rejected" else "unverified"
        start = dict(row, evidence_status=first)
        cols = list(start) + ["current_revision", "change_reason", "changed_by", "created_at_utc",
                              "updated_at_utc"]
        vals = list(start.values()) + [1, "created", changed_by, now, now]
        stmts.append((f"INSERT INTO exposure_candidates({', '.join(cols)}) "  # noqa: S608 - fixed columns
                      f"VALUES ({', '.join('?' * len(cols))})", vals))
        stmts += [_link_stmt(key_vals, link, now) for link in links]
        if row["evidence_status"] != start["evidence_status"]:
            stmts.append((f"UPDATE exposure_candidates SET evidence_status = ?, current_revision = 2, "  # noqa: S608
                          f"change_reason = 'evidence linked; status assessed', changed_by = ?, "
                          f"updated_at_utc = ? WHERE {_WHERE_KEY}",
                          (row["evidence_status"], changed_by, now, *key_vals)))
        db.batch(stmts)
        return "created"
    cur = existing[0]
    if cur["review_status"] in ("accepted", "rejected"):
        return "unchanged"   # a human or validation decision is not overwritten by a re-run
    have = {(r["role"], r["event_evidence_id"], r["company_exposure_id"], r["relationship_id"],
             r["source_item_id"])
            for r in db.execute("SELECT * FROM exposure_candidate_evidence WHERE candidate_id = ?",
                                (cur["candidate_id"],))}
    new_links = [lk for lk in links if lk not in have]
    changes = {k: row[k] for k in _MATERIAL if cur[k] != row[k]}
    if not changes and not new_links:
        return "unchanged"
    stmts += [_link_stmt(key_vals, link, now) for link in new_links]
    changes = changes or {"explanation": row["explanation"]}
    stmts.append(_revise_stmt(cur, changes, "re-run with changed evidence or rules", changed_by, now))
    db.batch(stmts)
    return "revised"


def _revise_stmt(cur: dict, changes: dict, reason: str, changed_by: str, now: str, review_sql: str = ""):
    sets = ", ".join(f"{k} = ?" for k in changes)
    extra = ", last_review_id = (SELECT MAX(review_id) FROM exposure_reviews WHERE candidate_id = ?)" \
        if review_sql else ""
    params = [*changes.values(), cur["current_revision"] + 1, reason, changed_by, now]
    if review_sql:
        params.append(cur["candidate_id"])
    params.append(cur["candidate_id"])
    return (f"UPDATE exposure_candidates SET {sets}, current_revision = ?, change_reason = ?, "  # noqa: S608
            f"changed_by = ?, updated_at_utc = ?{extra} WHERE candidate_id = ?", params)


# ---------------------------------------------------------------- public API
def map_event(db, event_id: int, *, synthetic: bool = False, persist: bool = True,
              changed_by: str = "phase4-rules") -> MappingResult:
    ev = load_event(db, event_id)
    result = MappingResult(event_id)
    cands = _named_companies(db, ev, result)
    cands += _rule_candidates(db, ev)
    cands += _relationship_candidates(db, ev, cands)
    contradictory = _contradictions(cands)
    for c in cands:
        _assess(db, ev, c, contradictory)
    result.candidates = cands
    if persist:
        for c in cands:
            result.stored[_store(db, _row(event_id, c, synthetic), _links(db, ev, c), changed_by)] += 1
    return result


LLM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["suggestions", "missing_evidence"],
    "properties": {
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["company_mention", "exposure_category", "exposure_subtype", "exposure_level",
                         "impact_direction", "mechanism", "evidence_quote"],
            "properties": {
                "company_mention": {"type": "string"},
                "exposure_category": {"type": "string", "enum": list(tax.CATEGORIES)},
                "exposure_subtype": {"type": "string"},
                "exposure_level": {"type": "string", "enum": list(tax.LEVELS)},
                "impact_direction": {"type": "string", "enum": sorted(tax.DIRECTION_LOOKUP)},
                "mechanism": {"type": "string"},
                "evidence_quote": {"type": "string"}}}}},
}
_SUGGESTION_KEYS = set(LLM_SCHEMA["properties"]["suggestions"]["items"]["properties"])


def _validate_suggestion(db, ev: dict, s, as_of) -> tuple[Candidate | None, str | None, dict | None]:
    if (not isinstance(s, dict) or set(s) != _SUGGESTION_KEYS
            or not all(isinstance(v, str) for v in s.values())):
        return None, "suggestion does not match the schema", None
    if not tax.is_valid(s["exposure_category"], s["exposure_subtype"]):
        return None, f"invalid category/subtype {s['exposure_category']}/{s['exposure_subtype']}", None
    if s["exposure_level"] not in tax.LEVELS:
        return None, "invalid exposure level", None
    try:
        direction = tax.to_direction(s["impact_direction"])
    except ValueError:
        return None, "invalid direction", None
    res = resolve(db, s["company_mention"], as_of=as_of)
    if res.status not in ("resolved", "historical"):
        return None, f"company '{s['company_mention']}' is {res.status}", None
    quote = normalise_for_match(s["evidence_quote"])
    company_x = db.execute("SELECT exposure_id, evidence_excerpt, source_item_id FROM company_exposures "
                           "WHERE company_id = ?", (res.company["company_id"],))
    def found(text: str) -> bool:
        return len(quote) >= 3 and quote in normalise_for_match(text)

    ev_hits = [r for r in ev["evidence"] if found(r["excerpt"])]
    cx_hits = [r for r in company_x if found(r["evidence_excerpt"])]
    if not ev_hits and not cx_hits:
        return None, "evidence_quote is not found in stored evidence", res.company
    c = Candidate(res.company, s["exposure_category"], s["exposure_subtype"], s["exposure_level"], direction,
                  s["mechanism"][:300], "llm", origin="llm_suggestion",
                  claim_evidence_ids=[r["evidence_id"] for r in ev_hits],
                  exposure_evidence=[{"table": "company_exposures", "id": r["exposure_id"]} for r in cx_hits],
                  source_item_ids=sorted({r["source_item_id"] for r in ev_hits + cx_hits}),
                  entity_confidence=res.confidence)
    c.review_reasons.append("LLM suggestion: requires human review")
    if not cx_hits:
        c.missing.append("suggestion is not supported by documented company exposure evidence")
    return c, None, None


def suggest_with_llm(db, event_id: int, gateway, *, synthetic: bool = False) -> MappingResult:
    """Ask the Phase 3 gateway for suggestions; validate each deterministically and store it."""
    from engines.llm import load_prompt

    prompt = load_prompt("exposure_candidate_v1")
    ev = load_event(db, event_id)
    as_of = (ev.get("event_date") or "")[:10] or None
    result = MappingResult(event_id)
    exposures = db.execute("SELECT c.legal_name, x.exposure_kind, x.subject, x.evidence_excerpt "
                           "FROM company_exposures x JOIN companies c USING(company_id)")
    user = json.dumps({"event": {k: ev[k] for k in ("event_type", "headline", "summary", "status_stage")},
                       "evidence": [r["excerpt"] for r in ev["evidence"]],
                       "documented_company_exposures": exposures}, sort_keys=True, default=str)
    out = gateway.complete(prompt, user, LLM_SCHEMA)
    if out.text is None:
        result.rejected_suggestions.append({"reason": f"llm {out.outcome}: {out.error}"})
        return result
    try:
        payload = json.loads(out.text)
        if not isinstance(payload, dict) or set(payload) != {"suggestions", "missing_evidence"} \
                or not isinstance(payload["suggestions"], list):
            raise ValueError("top-level shape")
    except (json.JSONDecodeError, ValueError) as exc:
        result.rejected_suggestions.append({"reason": f"invalid model output: {exc}"})
        return result
    contradictory: set[str] = set()
    for s in payload["suggestions"]:
        cand, why, company = _validate_suggestion(db, ev, s, as_of)
        if cand is None:
            result.rejected_suggestions.append({"suggestion": s, "reason": why})
            if company is not None and isinstance(s, dict):   # resolvable company: keep an audit row
                rej = Candidate(company, s["exposure_category"], s["exposure_subtype"], s["exposure_level"],
                                tax.to_direction(s["impact_direction"]), s["mechanism"][:300], "llm",
                                origin="llm_suggestion", review_reasons=[f"rejected: {why}"])
                rej.evidence_status, rej.confidence = "rejected", 0.0
                rej.explanation = f"Rejected LLM suggestion: {why}."
                rej.model, rej.prompt_version = out.model, prompt.version
                result.stored[_store(db, _row(event_id, rej, synthetic), [], "phase4-llm")] += 1
            continue
        cand.model, cand.prompt_version = out.model, prompt.version
        _assess(db, ev, cand, contradictory)
        result.candidates.append(cand)
        result.stored[_store(db, _row(event_id, cand, synthetic), _links(db, ev, cand), "phase4-llm")] += 1
    return result


def review(db, candidate_id: int, decision: str, *, reviewer: str, notes: str) -> dict:
    """Record a human decision. Only strongly supported candidates can be accepted (-> confirmed).

    The review row, the candidate's new revision and (on acceptance) the event_companies link are
    written in one atomic batch; the database re-checks every rule.
    """
    if decision not in ("accept", "reject", "needs_more_evidence"):
        raise ValueError("decision must be accept, reject or needs_more_evidence")
    if not notes.strip():
        raise ValueError("review notes are required")
    if len(reviewer.strip()) < 2:
        raise ValueError("a reviewer identity is required")
    rows = db.execute("SELECT * FROM exposure_candidates WHERE candidate_id = ?", (candidate_id,))
    if not rows:
        raise ValueError(f"candidate {candidate_id} not found")
    cur = rows[0]
    if decision == "accept" and cur["evidence_status"] != "strongly_supported":
        raise ValueError(f"cannot accept a candidate whose evidence is '{cur['evidence_status']}'; "
                         "approved company-specific evidence and a corroborated event are required")
    now = now_utc()
    changes = {"accept": {"evidence_status": "confirmed", "review_status": "accepted"},
               "reject": {"evidence_status": "rejected", "review_status": "rejected"},
               "needs_more_evidence": {"review_status": "needs_review"}}[decision]
    stmts = [("INSERT INTO exposure_reviews(candidate_id, decision, reviewer, notes, decided_at_utc, "
              "evidence_status_at_decision) VALUES (?,?,?,?,?,?)",
              (candidate_id, decision, reviewer.strip(), notes, now, cur["evidence_status"])),
             _revise_stmt(cur, changes, f"review: {decision} by {reviewer.strip()}", reviewer.strip(), now,
                          review_sql="yes")]
    if decision == "accept":
        stmts.append(("INSERT INTO event_companies(event_id, company_id, exposure_type, impact_direction, "
                      "channel, rationale, confidence, reviewer_status, created_at_utc) "
                      "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id, company_id) DO NOTHING",
                      (cur["event_id"], cur["company_id"], cur["exposure_level"], cur["impact_direction"],
                       f"{cur['exposure_category']}/{cur['exposure_subtype']}", cur["explanation"],
                       cur["confidence"], "accepted", now)))
    db.batch(stmts)
    return db.execute("SELECT * FROM exposure_candidates WHERE candidate_id = ?", (candidate_id,))[0]


def _would_cycle(db, parent_id: str, child_id: str | None) -> bool:
    if child_id is None:
        return False
    rows = db.execute(
        "WITH RECURSIVE down(cid) AS (SELECT ? UNION SELECT r.child_company_id "
        "FROM current_company_relationships r JOIN down ON r.parent_company_id = down.cid "
        "WHERE r.child_company_id IS NOT NULL AND r.evidence_status <> 'rejected') "
        "SELECT 1 FROM down WHERE cid = ? LIMIT 1", (child_id, parent_id))
    return bool(rows)


def record_relationship(db, *, parent_company_id: str, child_name: str, relationship_type: str,
                        evidence_status: str, recorded_by: str, change_reason: str,
                        child_company_id: str | None = None, ownership_pct: float | None = None,
                        valid_from: str | None = None, valid_to: str | None = None,
                        source_item_id: int | None = None, evidence_excerpt: str | None = None,
                        is_synthetic: bool = False, supersedes: int | None = None) -> int:
    """Append a relationship, or a correction that supersedes an earlier row. Never edits or deletes."""
    if evidence_status != "rejected" and _would_cycle(db, parent_company_id, child_company_id):
        raise ValueError("relationship would create an ownership cycle")
    db.execute("INSERT INTO company_relationships(supersedes_relationship_id, parent_company_id, "
               "child_company_id, child_name, relationship_type, ownership_pct, valid_from, valid_to, "
               "evidence_status, source_item_id, evidence_excerpt, is_synthetic, change_reason, recorded_by, "
               "recorded_at_utc) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (supersedes, parent_company_id, child_company_id, child_name, relationship_type, ownership_pct,
                valid_from, valid_to, evidence_status, source_item_id, evidence_excerpt, int(is_synthetic),
                change_reason, recorded_by, now_utc()))
    return db.execute("SELECT MAX(relationship_id) i FROM company_relationships")[0]["i"]


def relationship_history(db, relationship_id: int) -> list[dict]:
    """The full correction chain containing this relationship, oldest first."""
    chain, rid = [], relationship_id
    while True:   # walk back to the original
        row = db.execute("SELECT * FROM company_relationships WHERE relationship_id = ?", (rid,))[0]
        if row["supersedes_relationship_id"] is None:
            break
        rid = row["supersedes_relationship_id"]
    while rid is not None:
        row = db.execute("SELECT * FROM company_relationships WHERE relationship_id = ?", (rid,))[0]
        chain.append(row)
        nxt = db.execute("SELECT relationship_id FROM company_relationships "
                         "WHERE supersedes_relationship_id = ?", (rid,))
        rid = nxt[0]["relationship_id"] if nxt else None
    return chain
