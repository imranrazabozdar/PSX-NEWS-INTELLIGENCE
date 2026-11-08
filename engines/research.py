"""Research views for the dashboard and exported reports (read-only; Stage 2, final batch).

Everything here reads stored records; nothing is estimated. Financial statements, ratios, valuation, share
prices and technical indicators are not part of this project's data, so every report says
NOT_ASSESSED for them. Each report carries its data timestamp and separates current assessments from
historical (superseded or stale) ones.

Navigation: event -> evidence -> entities -> exposure candidates -> T1-T9 assessments -> scenarios, and back
from a company or sector to its events.
"""

from __future__ import annotations

import json

from database.canonical import now_utc
from database.connection import Database
from engines import event_intel as ei
from engines import impact_intel as ii

NOT_ASSESSED = "Not assessed — supporting data unavailable."
MACRO_TYPES = (
    "commodity_price",
    "commodity_supply",
    "energy_policy",
    "economic_indicator",
    "monetary_policy",
    "fiscal_policy",
    "tax_policy",
    "imf_program",
    "trade_policy",
    "geopolitical",
    "security_incident",
    "regulatory_action",
    "infrastructure",
)


def _marks(n: int) -> str:
    return ",".join("?" * n)


def events_page(db: Database, *, macro_only: bool = False, limit: int = 20, offset: int = 0) -> dict:
    """One page of events (newest first) with their classification status; total for pagination."""
    where = f"WHERE event_type IN ({_marks(len(MACRO_TYPES))})" if macro_only else ""
    params = MACRO_TYPES if macro_only else ()
    total = db.execute(f"SELECT COUNT(*) AS n FROM events {where}", params)[0]["n"]  # noqa: S608
    rows = db.execute(
        f"SELECT event_id, event_type, headline, status_stage, verification_state, novelty, "  # noqa: S608
        f"current_revision, first_seen_at_utc FROM events {where} "
        f"ORDER BY first_seen_at_utc DESC, event_id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    ids = [r["event_id"] for r in rows]
    assessed = (
        {
            r["event_id"]
            for r in db.execute(
                f"SELECT DISTINCT event_id FROM event_extractions WHERE schema_version = ? "  # noqa: S608
                f"AND event_id IN ({_marks(len(ids))})",
                (ei.SCHEMA_VERSION, *ids),
            )
        }
        if ids
        else set()
    )
    out = []
    for r in rows:
        d = dict(r)
        d["classification"] = "assessed" if r["event_id"] in assessed else "not_assessed"
        d["display_stage"] = d["status_stage"] if d["classification"] == "assessed" else "Not assessed"
        out.append(d)
    return {"total": total, "limit": limit, "offset": offset, "items": out}


def event_detail(db: Database, event_id: int) -> dict | None:
    rows = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    if not rows:
        return None
    event = dict(rows[0])
    evidence = db.execute(
        "SELECT v.evidence_id, v.source_item_id, v.excerpt, v.claim_type, v.verification_state, "
        "v.is_independent, "
        "i.canonical_url, i.original_url, i.published_at_utc, i.collected_at_utc, s.name AS publisher, "
        "s.reliability_tier FROM event_evidence v JOIN source_items i USING(source_item_id) "
        "JOIN sources s ON s.source_id = i.source_id WHERE v.event_id = ? ORDER BY v.evidence_id",
        (event_id,),
    )
    recs = {
        r["source_item_id"]: json.loads(r["extracted_json"])
        for r in db.execute(
            "SELECT source_item_id, extracted_json FROM event_extractions WHERE event_id = ? AND "
            "schema_version = ?",
            (event_id, ei.SCHEMA_VERSION),
        )
    }
    ev_rows = []
    for e in evidence:
        rec = recs.get(e["source_item_id"], {})
        ev_rows.append(
            dict(e)
            | {
                "headline_only": True,
                "claim_nature": rec.get("classification", {}).get("claim_nature", "not assessed"),
                "publisher_group": rec.get("evidence", {}).get("publisher_group", "not assessed"),
                "independence": rec.get("evidence", {}).get("independence", "not assessed"),
            }
        )
    intel = ei.event_intel(db, event_id)
    return {
        "event": event,
        "classification": intel["status"],
        "display_stage": event["status_stage"] if intel["status"] == "assessed" else "Not assessed",
        "revisions": db.execute(
            "SELECT revision_no, recorded_at_utc, status_stage, verification_state, change_reason, "
            "changed_by FROM event_revisions WHERE event_id = ? ORDER BY revision_no",
            (event_id,),
        ),
        "evidence": ev_rows,
        "secondary_types": intel["secondary_types"],
        "publisher_groups": intel["publisher_groups"],
        "conflicts": intel["conflicts"],
        "entities": intel["entities"],
        "impact": ii.event_impact_overview(db, event_id),
    }


def _assessments(db: Database, where: str, params: tuple) -> list[dict]:
    rows = db.execute(
        f"SELECT a.*, e.headline, e.event_type, e.current_revision AS event_current_revision, "  # noqa: S608
        f"e.verification_state FROM impact_assessments a JOIN events e USING(event_id) WHERE {where} "
        f"ORDER BY e.first_seen_at_utc DESC, a.mechanism_id",
        params,
    )
    ids = [r["assessment_id"] for r in rows]
    scen: dict[int, list[dict]] = {}
    if ids:
        for s in db.execute(
            f"SELECT s.* FROM impact_scenarios s JOIN impact_assessments a USING(assessment_id) "  # noqa: S608
            f"WHERE s.assessment_id IN ({_marks(len(ids))}) AND s.revision_no = "
            f"(SELECT MAX(x.revision_no) FROM impact_scenarios x WHERE x.assessment_id = s.assessment_id)",
            tuple(ids),
        ):
            scen.setdefault(s["assessment_id"], []).append(
                dict(s) | {"assumptions": json.loads(s["assumptions_json"])}
            )
    out = []
    for r in rows:
        d = dict(r)
        d["layers"] = json.loads(r["affected_lines_json"]).get("impact_layers", {})
        d["missing"] = json.loads(r["missing_inputs_json"])
        d["scenarios"] = scen.get(r["assessment_id"], [])
        d["currency"] = (
            "historical (event revised since; revalidation pending)"
            if r["event_revision_no"] < r["event_current_revision"]
            else "current"
        )
        out.append(d)
    return out


def company_report(db: Database, company_id: str) -> dict | None:
    comp = db.execute(
        "SELECT c.company_id, c.legal_name, c.listing_status, cc.sector_id, s.name AS sector, "
        "(SELECT value FROM company_identifiers i WHERE i.company_id = c.company_id AND i.id_type = "
        "'psx_ticker' "
        "AND i.valid_to IS NULL LIMIT 1) AS ticker FROM companies c LEFT JOIN company_classifications cc "
        "ON cc.company_id = c.company_id AND cc.valid_to IS NULL LEFT JOIN sectors s ON s.sector_id "
        "= cc.sector_id "
        "WHERE c.company_id = ?",
        (company_id,),
    )
    if not comp:
        return None
    comp = dict(comp[0])
    cands = db.execute(
        "SELECT x.candidate_id, x.event_id, e.headline, e.event_type, x.exposure_level, x.origin, "
        "x.rule_id, x.effective_status, x.review_status, x.mechanism, x.explanation, "
        "x.missing_evidence_json FROM exposure_candidates_current x JOIN events e USING(event_id) "
        "WHERE x.company_id = ? ORDER BY e.first_seen_at_utc DESC",
        (company_id,),
    )
    assessments = _assessments(db, "a.company_id = ?", (company_id,))
    named = [c for c in cands if (c["mechanism"] or "").startswith("named in the event")]
    sector_events = (
        db.execute(
            "SELECT DISTINCT e.event_id, e.headline, e.event_type, e.first_seen_at_utc FROM "
            "exposure_candidates x "
            "JOIN events e USING(event_id) JOIN company_classifications cc ON cc.company_id = x.company_id "
            "AND cc.valid_to IS NULL WHERE cc.sector_id = ? AND x.company_id <> ? ORDER BY "
            "e.first_seen_at_utc DESC "
            "LIMIT 20",
            (comp["sector_id"], company_id),
        )
        if comp["sector_id"]
        else []
    )
    by_mech: dict[str, list[dict]] = {}
    for a in assessments:
        by_mech.setdefault(a["mechanism_id"], []).append(a)
    horizon = {
        h: [
            f"{a['mechanism_id']} {a['direction']} ({a['headline']})"
            for a in assessments
            if a["horizon"] == h
        ]
        for h in ("short", "medium", "long", "unknown")
    }
    evidence_refs = (
        db.execute(
            f"SELECT DISTINCT v.event_id, v.excerpt, i.canonical_url, i.published_at_utc, s.name AS "  # noqa: S608
            f"publisher "
            f"FROM event_evidence v JOIN source_items i USING(source_item_id) JOIN sources s ON "
            f"s.source_id = i.source_id "
            f"WHERE v.event_id IN ({_marks(len({c['event_id'] for c in cands}))}) ORDER BY "
            f"i.published_at_utc DESC "
            f"LIMIT 50",
            tuple({c["event_id"] for c in cands}),
        )
        if cands
        else []
    )
    metrics = db.execute("SELECT COUNT(*) AS n FROM financial_metrics WHERE company_id = ?", (company_id,))[
        0
    ]["n"]
    directions = {a["direction"] for a in assessments} - {"unknown"}
    summary = (
        f"{len(cands)} event exposure(s) and {len(assessments)} T1-T9 assessment(s) on record. "
        + (
            "Directions differ across mechanisms (mixed); they are not netted. "
            if len(directions) > 1
            else ""
        )
        + "All assessments are scenario-only: no conclusion is confirmed. "
        + "Fundamentals, valuation and market data are not assessed."
    )
    return {
        "generated_at_utc": now_utc(),
        "company": comp,
        "executive_summary": summary,
        "latest_developments": [dict(c) for c in cands[:10]],
        "company_specific_news": [dict(c) for c in named],
        "sector_developments": [dict(r) for r in sector_events],
        "macro_geopolitical_exposure": {
            m: [f"{a['direction']} — {a['headline']}" for a in v] for m, v in by_mech.items()
        },
        "exposure": {
            "direct": [dict(c) for c in cands if c["exposure_level"] == "direct"],
            "indirect_or_contextual": [dict(c) for c in cands if c["exposure_level"] != "direct"],
        },
        "impact_by_mechanism": by_mech,
        "outlook_by_horizon": horizon,
        "scenarios": {a["assessment_id"]: a["scenarios"] for a in assessments},
        "risks_and_invalidation": sorted(
            {
                x
                for a in assessments
                for s in a["scenarios"]
                for x in s["assumptions"].get("invalidated_by", [])
            }
        ),
        "evidence_references": [dict(r) for r in evidence_refs],
        "limitations": {
            "financial_statements": NOT_ASSESSED
            if not metrics
            else "financial metrics stored but not evaluated",
            "valuation": NOT_ASSESSED,
            "share_price": NOT_ASSESSED,
            "technical_indicators": NOT_ASSESSED,
            "evidence_basis": "headline metadata only; no article text",
            "confidence": "exposure and direction confidence are low until an approved "
            "company-evidence source "
            "exists; magnitude is qualitative",
        },
    }


def sector_report(db: Database, sector_id: str) -> dict | None:
    sec = db.execute("SELECT sector_id, name FROM sectors WHERE sector_id = ?", (sector_id,))
    if not sec:
        return None
    members = db.execute(
        "SELECT c.company_id, c.legal_name FROM company_classifications cc JOIN companies c "
        "USING(company_id) WHERE cc.sector_id = ? AND cc.valid_to IS NULL ORDER BY c.legal_name",
        (sector_id,),
    )
    ids = [m["company_id"] for m in members]
    assessments = _assessments(db, f"a.company_id IN ({_marks(len(ids))})", tuple(ids)) if ids else []
    cands = (
        db.execute(
            f"SELECT x.*, e.headline FROM exposure_candidates_current x JOIN events e USING(event_id) "  # noqa: S608
            f"WHERE x.company_id IN ({_marks(len(ids))})",
            tuple(ids),
        )
        if ids
        else []
    )
    per_event: dict[int, dict] = {}
    for a in assessments:
        per_event.setdefault(a["event_id"], {"headline": a["headline"], "directions": {}})["directions"][
            a["company_id"]
        ] = a["direction"]
    return {
        "generated_at_utc": now_utc(),
        "sector": dict(sec[0]),
        "companies": [dict(m) for m in members],
        "developments": per_event,
        "differing_impacts": {k: v for k, v in per_event.items() if len(set(v["directions"].values())) > 1},
        "direct_exposure": [dict(c) for c in cands if c["exposure_level"] == "direct"],
        "indirect_or_contextual": [dict(c) for c in cands if c["exposure_level"] != "direct"],
        "unverified_relationships": [dict(c) for c in cands if c["effective_status"] == "unverified"],
        "conflicts": [a["headline"] for a in assessments if a["verification_state"] == "disputed"],
        "note": "Sector membership alone never establishes a company impact; each company is shown "
        "separately.",
    }


def _md_table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "_None on record._\n"
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join(
        "| " + " | ".join(str(r.get(c, "")).replace("|", "/")[:120] for c in cols) + " |\n" for r in rows
    )


def report_markdown(rep: dict) -> str:
    """Plain Markdown export of a company report (no extra dependencies)."""
    c = rep["company"]
    lines = [
        f"# {c['legal_name']} ({c.get('ticker') or 'no ticker'}) — research report",
        f"_Data as of {rep['generated_at_utc']} (UTC). Headline-based intelligence; not investment advice; "
        f"no buy/sell recommendation._",
        "",
        "## 1. Executive summary",
        rep["executive_summary"],
        "",
        "## 2. Latest developments",
        _md_table(rep["latest_developments"], ["event_id", "headline", "exposure_level", "effective_status"]),
        "## 3. Company-specific news",
        _md_table(rep["company_specific_news"], ["event_id", "headline"]),
        "## 4. Sector developments",
        _md_table(rep["sector_developments"], ["event_id", "headline"]),
        "## 5. Macro and geopolitical exposure",
    ]
    lines += [f"- **{m}**: " + "; ".join(v) for m, v in rep["macro_geopolitical_exposure"].items()] or [
        "_None._"
    ]
    lines += [
        "",
        "## 6. Direct and indirect exposure",
        "### Direct",
        _md_table(rep["exposure"]["direct"], ["event_id", "headline", "origin", "effective_status"]),
        "### Indirect or contextual (hypotheses; not established exposure)",
        _md_table(
            rep["exposure"]["indirect_or_contextual"], ["event_id", "headline", "origin", "effective_status"]
        ),
        "## 7. Impact by transmission mechanism",
    ]
    for m, items in rep["impact_by_mechanism"].items():
        lines.append(f"### {m} — {ii.MECHANISMS[m].name}")
        lines.append(
            _md_table(
                items,
                [
                    "headline",
                    "direction",
                    "magnitude_level",
                    "horizon",
                    "assessment_status",
                    "exposure_confidence",
                    "direction_confidence",
                    "currency",
                ],
            )
        )
    lines += ["## 8. Outlook by horizon"] + [
        f"- **{h}**: " + ("; ".join(v) or "none") for h, v in rep["outlook_by_horizon"].items()
    ]
    lines += ["", "## 9. Scenarios (conditional framings, not forecasts or prices)"]
    for aid, sc in rep["scenarios"].items():
        lines += [
            f"- assessment {aid}: "
            + "; ".join(
                f"{s['scenario_case']}: {s['direction']} — {s['assumptions'].get('assumption', '')}"
                for s in sc
            )
        ]
    lines += ["", "## 10. Risks and invalidation conditions"] + [
        f"- {x}" for x in rep["risks_and_invalidation"]
    ]
    lines += [
        "",
        "## 11. Evidence and source references",
        _md_table(rep["evidence_references"], ["published_at_utc", "publisher", "excerpt", "canonical_url"]),
        "## 12. Data limitations and confidence",
    ] + [f"- **{k}**: {v}" for k, v in rep["limitations"].items()]
    return "\n".join(lines) + "\n"
