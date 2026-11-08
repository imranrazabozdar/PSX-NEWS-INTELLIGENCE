"""Stage 2, batch 2: company exposure and T1-T9 impact intelligence (deterministic).

Pipeline per event that batch 1 has assessed (an event-intel/1 record exists):

1. Exposure: the existing Phase 4 engine (engines.exposure_mapping.map_event) builds exposure candidates from
   companies the exact-match resolver assigned (direct, "named in event"), rule links to DOCUMENTED company
   exposures (company_exposures), documented subsidiary/associate relationships, and, for the oil/gas/rate
   rules, sector-level candidates explicitly marked "sector membership alone is not proof" (contextual
   hypotheses, never established exposure). It is idempotent and keeps revision history.
2. Impact: for each current candidate, only the T1-T9 mechanisms (docs/PHASE_5_TRANSMISSION_FRAMEWORK.md) that
   the event and the candidate support get one impact_assessments row each (migration 0009), with transmission
   steps, base/optimistic/adverse scenarios and inputs. Framework rules applied exactly:
   * direction = event change x documented role x mechanism sign; any unknown factor -> unknown;
   * magnitude is qualitative (low for indirect/sector-level; not_assessable when the documented share is
     missing); approved thresholds do not exist, so no quantified magnitude is ever produced;
   * horizons per framework §5; scenarios are conditional framings, never forecasts or prices;
   * every assessment starts scenario_only (or needs_review when the event is disputed): no assessment is
     upgraded here, so low-confidence exposure can never become a provisional or confirmed impact.
3. Fundamentals versus market pressure: each assessment states its impact layers separately (fundamental,
   operational, financial, valuation, market sentiment). Fundamentals and valuation are "not assessed" unless
   sourced financial_metrics exist; a geopolitical or market-wide event is recorded as possible risk-premium
   pressure, never as a change in fundamentals.

No AI, no prices, no recommendations. Single runner: the job holds no lease, so run one processor at a time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from database.canonical import now_utc
from database.connection import Database, DatabaseBudgetError, DatabaseError
from engines import event_intel as ei
from engines import exposure_mapping, exposure_rules

TRANSMISSION_VERSION = "transmission/1"
RULESET_VERSION = "impact-rules/1"
CHANGED_BY = "impact-intel/1"
RULE_MECHANISM = {"R-OIL-1": "T1", "R-GAS-1": "T2", "R-RATE-1": "T3", "R-PKR-1": "T4", "R-DUTY-1": "T5"}
_SENTIMENT_TYPES = {"geopolitical", "security_incident", "market_structure", "political"}


@dataclass(frozen=True)
class Mechanism:
    name: str
    horizon: str  # framework §5
    lines: tuple[str, ...]
    steps: tuple[tuple[str, str, str], ...]  # (from, to, explanation); signs come from the assessment
    offsets: tuple[str, ...]  # framework "offsets / uncertainty" column
    required: tuple[str, ...]  # inputs that would strengthen the assessment
    invalidators: tuple[str, ...]


MECHANISMS: dict[str, Mechanism] = {
    "T1": Mechanism(
        "Oil price",
        "short",
        ("crude cost", "realised price", "inventory valuation", "fuel cost"),
        (
            (
                "benchmark oil price",
                "company input cost or realised price",
                "price change passes to the documented exposure",
            ),
            ("input cost or realised price", "margin", "with an inventory lag"),
        ),
        ("OGRA price pass-through", "hedging", "inventory accounting", "crack spreads", "PKR moves"),
        ("sourced benchmark price change", "documented exposure share"),
        ("the price move reverses within the horizon", "regulated pass-through offsets the change"),
    ),
    "T2": Mechanism(
        "Gas / RLNG and circular debt",
        "medium",
        ("feedstock cost", "fuel cost", "receivables"),
        (
            (
                "regulated gas price or settlement",
                "feedstock / fuel cost or receivables",
                "notified price or settlement changes",
            ),
            ("cost or receivables", "margin or liquidity", "pass-through decides the net effect"),
        ),
        ("subsidised feedstock regimes", "pass-through orders", "delayed payment"),
        ("notification text", "documented exposure", "receivable disclosure"),
        ("notification withdrawn or delayed", "full pass-through confirmed"),
    ),
    "T3": Mechanism(
        "Interest rates",
        "medium",
        ("finance cost", "net interest income", "credit demand"),
        (
            (
                "SBP policy rate",
                "KIBOR-linked borrowing cost / asset repricing",
                "rate decision reprices floating instruments",
            ),
            ("finance cost or NII", "earnings", "with repricing lags"),
        ),
        ("fixed-rate debt", "hedges", "deposit mix", "repricing lags"),
        ("MPS statement", "company debt terms", "bank repricing-gap data"),
        ("decision reversed", "company debt is fixed-rate"),
    ),
    "T4": Mechanism(
        "PKR exchange rate",
        "short",
        ("import cost", "FX revenue", "FX debt revaluation"),
        (("PKR/USD level", "PKR value of FX revenue, costs or debt", "translation of FX exposures"),),
        ("pricing power", "hedging", "natural hedge", "pass-through"),
        ("sourced FX data", "company FX disclosures"),
        ("PKR move reverses", "exposure is hedged"),
    ),
    "T5": Mechanism(
        "Inflation, tax and duties",
        "medium",
        ("input cost", "product price", "demand"),
        (
            (
                "CPI release or tax/duty notification",
                "cost or price of the product or input in scope",
                "measure applies within the notification's scope",
            ),
        ),
        ("notification versus implementation stage", "exemptions", "pass-through"),
        ("notification text and stage", "scope match to the company's product or input"),
        ("measure withdrawn or exempted", "stage stays at proposal"),
    ),
    "T6": Mechanism(
        "Electricity tariffs",
        "medium",
        ("energy cost", "tariff revenue"),
        (
            (
                "NEPRA determination / tariff notification",
                "energy cost or tariff revenue",
                "tariff change applies to the company's consumption or generation",
            ),
        ),
        ("captive power", "fuel mix", "determination versus notification"),
        ("determination text", "documented energy-cost share"),
        ("determination not notified", "captive power covers demand"),
    ),
    "T7": Mechanism(
        "Global commodities",
        "medium",
        ("input cost (COGS)", "output price"),
        (
            (
                "benchmark of the specific grade and location",
                "input cost or output price",
                "with inventory lag",
            ),
        ),
        ("grade mismatch", "local versus imported mix", "freight", "FX"),
        ("benchmark (grade, date, source)", "company input or fuel mix"),
        ("grade or location does not match the company's input", "price move reverses"),
    ),
    "T8": Mechanism(
        "Geopolitical, shipping and supply",
        "unknown",
        ("freight and insurance cost", "delivery delays", "lost production or exports", "risk premium"),
        (
            (
                "conflict, chokepoint, closure or sanctions",
                "route / location-specific operations",
                "only through a documented route or location exposure",
            ),
        ),
        ("duration", "rerouting", "inventory buffers"),
        ("verified event", "route or location exposure"),
        ("de-escalation or reopening", "company has no exposure to the route"),
    ),
    "T9": Mechanism(
        "Fiscal policy, borrowing and IMF",
        "long",
        ("tax measures", "subsidies", "development spending", "government receivables"),
        (
            (
                "budget / IMF review / borrowing measure",
                "sector or company named in the measure",
                "measure applies at its implementation stage",
            ),
        ),
        ("negotiation stage", "implementation lag"),
        ("official documents with stage", "measure naming the sector or company"),
        ("measure dropped in negotiation", "stage remains at proposal"),
    ),
}


def event_mechanisms(event: dict, intel: dict) -> tuple[list[dict], str]:
    """T-mechanisms the event itself supports (independent of any company), and its scope."""
    names = {e["name"].casefold() for e in intel.get("entities", []) if e.get("entity_type") != "company"}
    text = " " + (event.get("headline") or "").casefold() + " "
    etype = event["event_type"]
    types = {etype} | set(intel.get("secondary_types", []))
    foreign = {e["name"] for e in intel.get("entities", []) if e.get("entity_type") == "country"} - {
        "Pakistan"
    }
    pakistani = bool(
        names
        & {
            "state bank of pakistan",
            "fbr",
            "secp",
            "nepra",
            "ogra",
            "pakistan",
            "ministry of finance",
            "ecc",
            "pkr",
        }
    )
    scope = "global" if foreign and not pakistani else "pakistan"
    has = lambda *ws: any(w in names or f" {w} " in text for w in ws)  # noqa: E731
    out = []

    def add(t, basis):
        if t not in {m["mechanism"] for m in out}:
            out.append({"mechanism": t, "basis": basis})

    if has("crude oil", "brent crude", "oil", "petrol", "diesel", "petroleum products") and types & {
        "commodity_price",
        "commodity_supply",
        "geopolitical",
        "energy_policy",
        "tax_policy",
    }:
        add("T1", "oil price or supply named in an oil-relevant event")
    if has("natural gas", "lng", "lpg", "rlng", "circular debt", "gas price") and types & {
        "energy_policy",
        "commodity_price",
        "commodity_supply",
        "regulatory_action",
    }:
        add("T2", "gas / RLNG price or circular debt named")
    if (
        "monetary_policy" in types
        and scope == "pakistan"
        and has("policy rate", "interest rate", "kibor", "state bank of pakistan", "monetary policy")
    ):
        add("T3", "SBP policy-rate decision")
    if has("pkr", "rupee", "exchange rate", "usd") and types & {
        "economic_indicator",
        "monetary_policy",
        "imf_program",
    }:
        add("T4", "PKR exchange rate named")
    if types & {"tax_policy", "trade_policy"} or has("inflation", "cpi"):
        add("T5", "inflation, tax or duty measure")
    if has("electricity tariff", "power tariff", "nepra", "fuel adjustment", "fca", "electricity price"):
        add("T6", "electricity tariff determination or notification")
    if "commodity_price" in types and has(
        "coal", "urea", "steel", "cotton", "wheat", "sugar", "copper", "gold"
    ):
        add("T7", "specific commodity benchmark named")
    if types & {"geopolitical", "security_incident", "infrastructure"} or (
        "commodity_supply" in types and has("shipment", "cargo", "supply", "shortage", "disruption")
    ):
        add("T8", "conflict, security, route or supply disruption")
    if types & {"fiscal_policy", "imf_program"}:
        add("T9", "fiscal, borrowing or IMF measure")
    return out, scope


def _change(event: dict, mech: str) -> int | None:
    driver = {"T1": "crude_oil_price", "T2": "gas_price", "T3": "policy_rate", "T4": "pkr_depreciation"}.get(
        mech
    )
    return exposure_rules.change_of(event.get("headline") or "", driver) if driver else None


def _sector(db: Database, company_id: str) -> str | None:
    r = db.execute(
        "SELECT sector_id FROM company_classifications WHERE company_id = ? AND valid_to IS NULL",
        (company_id,),
    )
    return r[0]["sector_id"] if r else None


def _direction(db: Database, event: dict, cand: dict, mech: str) -> tuple[str, list[str]]:
    """Framework §2: event change x documented role x mechanism sign; unknown if any factor is unknown."""
    if cand["impact_direction"] in ("positive", "negative", "mixed", "neutral"):
        return cand["impact_direction"], [f"from the documented exposure: {cand['mechanism']}"]
    change, sector = _change(event, mech), _sector(db, cand["company_id"])
    if change is None:
        return "unknown", ["the event does not state the direction of the change"]
    if cand["origin"] == "rule" and cand["exposure_level"] == "indirect" and mech == "T1":
        role = {
            "psx-oil-gas-exploration-companies": (
                "positive" if change > 0 else "negative",
                "E&P: realised price moves with oil",
            ),
            "psx-refinery": ("mixed", "refiner: crude cost versus inventory gain and product prices"),
            "psx-oil-gas-marketing-companies": ("mixed", "OMC: regulated margins and inventory valuation"),
        }.get(sector)
        if role:
            return role[0], [f"framework T1 sector role ({role[1]}); sector-level hypothesis only"]
    if (
        cand["origin"] == "rule"
        and cand["exposure_level"] == "indirect"
        and mech == "T2"
        and sector == "psx-fertilizer"
    ):
        return ("negative" if change > 0 else "positive"), [
            "framework T2: feedstock user, unless pass-through"
        ]
    return "unknown", ["no documented role for this company under the mechanism"]


def _assessment(db: Database, event: dict, cand: dict, mech: str, intel: dict) -> dict:
    m = MECHANISMS[mech]
    direction, why_dir = _direction(db, event, cand, mech)
    status = cand["effective_status"]
    exposure_conf = {"confirmed": "high", "strongly_supported": "medium"}.get(status, "low")
    evidence_conf = "medium" if event["verification_state"] == "primary_confirmed" else "low"
    direction_conf = "medium" if direction != "unknown" and exposure_conf != "low" else "low"
    documented = cand["origin"] == "rule" and cand["exposure_level"] == "direct"
    sector_only = "sector membership alone is not proof" in (cand["missing_evidence_json"] or "")
    magnitude = "low" if cand["exposure_level"] == "indirect" else "not_assessable"
    metrics = db.execute(
        "SELECT COUNT(*) AS n FROM financial_metrics WHERE company_id = ?", (cand["company_id"],)
    )[0]["n"]
    disputed = event["verification_state"] == "disputed"
    sentiment = event["event_type"] in _SENTIMENT_TYPES or mech == "T8"
    layers = {
        "fundamental": (
            "not assessed: no sourced financial_metrics for this company"
            if not metrics
            else "financial metrics exist but are not evaluated by this engine"
        ),
        "operational": ", ".join(x for x in m.lines if "cost" in x or "production" in x or "delivery" in x)
        or "not indicated by this mechanism",
        "financial": ", ".join(x for x in m.lines if x not in ("delivery delays",)) or "not indicated",
        "valuation": "not assessed (later phase)",
        "market_sentiment": (
            "possible risk-premium or sentiment pressure from a geopolitical or market-wide "
            "event; this is not evidence of a change in fundamentals"
        )
        if sentiment
        else "not indicated",
    }
    missing = list(json.loads(cand["missing_evidence_json"] or "[]")) + [f"needs: {x}" for x in m.required]
    if not metrics:
        missing.append("no sourced financial_metrics: fundamentals not assessed")
    missing.append("no market data: market reaction not evaluable")
    return {
        "direction": direction,
        "magnitude": magnitude,
        "horizon": m.horizon,
        "evidence_conf": evidence_conf,
        "exposure_conf": exposure_conf,
        "direction_conf": direction_conf,
        "magnitude_conf": "low",
        "uncertainty": "undetermined" if direction == "unknown" else "wide",
        "status": ("needs_review", "event_disputed") if disputed else ("scenario_only", "created_scenario"),
        "reasons": {
            "evidence": f"event verification_state={event['verification_state']} (headline-only evidence)",
            "exposure": f"exposure candidate {status}; level {cand['exposure_level']}; origin "
            f"{cand['origin']}"
            + ("; sector-level hypothesis" if sector_only else "")
            + ("; documented company exposure" if documented else ""),
            "direction": "; ".join(why_dir),
            "magnitude": "qualitative only: approved thresholds and sourced shares do not exist",
            "horizon": f"framework §5 typical horizon for {mech} ({m.name})",
        },
        "layers": layers,
        "lines": list(m.lines),
        "counter": list(m.offsets),
        "missing": missing,
        "sector_only": sector_only,
    }


def _key_sql() -> str:
    return (
        "(SELECT assessment_id FROM impact_assessments WHERE event_id = ? AND company_id = ? "
        "AND mechanism_id = ? AND scenario_kind = 'current' AND transmission_version = ?)"
    )


def _statements(db: Database, event: dict, cand: dict, mech: str, a: dict, synthetic: bool) -> list:
    now, m = now_utc(), MECHANISMS[mech]
    key = (event["event_id"], cand["company_id"], mech, TRANSMISSION_VERSION)
    stmts = [
        (
            "INSERT INTO impact_assessments(event_id, event_revision_no, company_id, mechanism_id, "
            "transmission_version, "
            "ruleset_version, scenario_kind, assessment_status, status_reason, direction, magnitude_level, "
            "magnitude_basis, horizon, evidence_confidence, exposure_confidence, direction_confidence, "
            "magnitude_confidence, scenario_uncertainty, confidence_reasons_json, affected_lines_json, "
            "counter_evidence_json, missing_inputs_json, freshness_basis, is_synthetic, change_reason, "
            "changed_by, "
            "actor_type, created_at_utc, updated_at_utc) "
            "VALUES (?,?,?,?,?,?,'current',?,?,?,?,'qualitative',?,?,?,?,?,"
            "?,?,?,?,?,'not_established',?,?,?,'system',?,?)",
            [
                event["event_id"],
                event["current_revision"],
                cand["company_id"],
                mech,
                TRANSMISSION_VERSION,
                RULESET_VERSION,
                a["status"][0],
                a["status"][1],
                a["direction"],
                a["magnitude"],
                a["horizon"],
                a["evidence_conf"],
                a["exposure_conf"],
                a["direction_conf"],
                a["magnitude_conf"],
                a["uncertainty"],
                json.dumps(a["reasons"], sort_keys=True),
                json.dumps({"lines": a["lines"], "impact_layers": a["layers"]}, sort_keys=True),
                json.dumps(a["counter"]),
                json.dumps(a["missing"]),
                int(synthetic),
                f"{mech} assessment from exposure candidate {cand['candidate_id']}",
                CHANGED_BY,
                now,
                now,
            ],
        )
    ]
    evid = db.execute(
        "SELECT evidence_id, source_item_id FROM event_evidence WHERE event_id = ? "
        "ORDER BY evidence_id LIMIT 5",
        (event["event_id"],),
    )
    first_item = evid[0]["source_item_id"]
    stmts.append(
        (
            f"INSERT INTO impact_assessment_inputs(assessment_id, input_kind, exposure_candidate_id, "  # noqa: S608
            f"exposure_candidate_revision, source_item_id, added_at_utc) VALUES ({_key_sql()}, "
            f"'exposure_candidate', ?, ?, ?, ?)",
            [*key, cand["candidate_id"], cand["current_revision"], first_item, now],
        )
    )
    for e in evid:
        stmts.append(
            (
                f"INSERT INTO impact_assessment_inputs(assessment_id, input_kind, event_evidence_id, "  # noqa: S608
                f"source_item_id, added_at_utc) VALUES ({_key_sql()}, 'event_evidence', ?, ?, ?)",
                [*key, e["evidence_id"], e["source_item_id"], now],
            )
        )
    sign = {"positive": 1, "negative": -1, "neutral": 0}.get(a["direction"])
    for n, (frm, to, why) in enumerate(m.steps, 1):
        stmts.append(
            (
                f"INSERT INTO impact_transmission_steps(assessment_id, revision_no, step_no, from_variable, "  # noqa: S608
                f"to_variable, sign, lag_horizon, explanation) VALUES ({_key_sql()}, 1, ?, ?, ?, ?, ?, ?)",
                [*key, n, frm, to, sign if n == len(m.steps) else None, a["horizon"], why],
            )
        )
    common = {
        "mechanism": mech,
        "conditional": "a framing under stated assumptions; not a forecast or price",
        "strengthened_by": list(m.required),
        "invalidated_by": list(m.invalidators),
    }
    for case, assumption in (
        ("base", "the stated change persists at the stated level for the horizon"),
        ("optimistic", "favourable variation: " + "; ".join(m.offsets[:2])),
        ("adverse", "unfavourable variation: no offset (" + "; ".join(m.offsets[:2]) + ")"),
    ):
        stmts.append(
            (
                f"INSERT INTO impact_scenarios(assessment_id, revision_no, scenario_case, direction, "  # noqa: S608
                f"magnitude_level, assumptions_json) VALUES ({_key_sql()}, 1, ?, ?, ?, ?)",
                [
                    *key,
                    case,
                    a["direction"],
                    a["magnitude"],
                    json.dumps(common | {"assumption": assumption}, sort_keys=True),
                ],
            )
        )
    return stmts


@dataclass
class Summary:
    events: int = 0
    candidates: int = 0
    assessments_created: int = 0
    already_assessed: int = 0
    stale: list[str] = field(default_factory=list)
    no_mechanism: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped_at_budget: bool = False


def _assessed_events(db: Database, limit: int) -> list[int]:
    return [
        r["event_id"]
        for r in db.execute(
            "SELECT DISTINCT event_id FROM event_extractions WHERE schema_version = ? "
            "AND event_id IS NOT NULL "
            "ORDER BY event_id LIMIT ?",
            (ei.SCHEMA_VERSION, limit),
        )
    ]


def process_event(db: Database, event_id: int, *, synthetic: bool, s: Summary) -> None:
    exposure_mapping.map_event(db, event_id, synthetic=synthetic, changed_by=CHANGED_BY)
    event = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))[0]
    intel = ei.event_intel(db, event_id)
    mechs, _scope = event_mechanisms(event, intel)
    event_ts = {m["mechanism"] for m in mechs}
    cands = db.execute(
        "SELECT * FROM exposure_candidates_current WHERE event_id = ? AND is_synthetic = ? "
        "AND effective_status <> 'rejected' ORDER BY candidate_id",
        (event_id, int(synthetic)),
    )
    for cand in map(dict, cands):
        s.candidates += 1
        rule_t = RULE_MECHANISM.get(cand["rule_id"] or "")
        applicable = [rule_t] if rule_t else sorted(event_ts)
        if not applicable:
            s.no_mechanism.append(f"event {event_id} / {cand['company_id']}: no supported T1-T9 mechanism")
            continue
        for mech in applicable:
            existing = db.execute(
                "SELECT event_revision_no FROM impact_assessments WHERE event_id = ? AND "
                "company_id = ? AND mechanism_id = ? AND scenario_kind = 'current' AND "
                "transmission_version = ?",
                (event_id, cand["company_id"], mech, TRANSMISSION_VERSION),
            )
            if existing:
                s.already_assessed += 1
                if existing[0]["event_revision_no"] < event["current_revision"]:
                    s.stale.append(f"event {event_id} / {cand['company_id']} / {mech}: revalidation deferred")
                continue
            a = _assessment(db, event, cand, mech, intel)
            try:
                db.batch(_statements(db, event, cand, mech, a, synthetic))
            except DatabaseBudgetError:
                raise
            except DatabaseError:
                if db.execute(
                    "SELECT 1 FROM impact_assessments WHERE event_id = ? AND company_id = ? AND "
                    "mechanism_id = ? AND transmission_version = ?",
                    (event_id, cand["company_id"], mech, TRANSMISSION_VERSION),
                ):
                    s.already_assessed += 1  # a concurrent or earlier attempt created it
                    continue
                raise
            s.assessments_created += 1


def run(db: Database, *, synthetic: bool = False, limit: int = 200) -> Summary:
    """Exposure + impact for events assessed by batch 1. Safe to re-run; one transaction per assessment."""
    s = Summary()
    for event_id in _assessed_events(db, limit):
        s.events += 1
        try:
            process_event(db, event_id, synthetic=synthetic, s=s)
        except DatabaseBudgetError:
            s.stopped_at_budget = True
            break
        except (DatabaseError, ValueError, TypeError, KeyError) as exc:
            s.errors.append(f"event {event_id}: {type(exc).__name__}: {str(exc)[:200]}")
    return s


def event_impact_overview(db: Database, event_id: int) -> dict:
    """Everything a view needs, including what is unresolved, unsupported or needs review."""
    event = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))[0]
    intel = ei.event_intel(db, event_id)
    mechs, scope = event_mechanisms(event, intel)
    cands = db.execute(
        "SELECT candidate_id, company_id, psx_symbol, exposure_level, origin, rule_id, "
        "effective_status, review_status, mechanism, impact_direction FROM "
        "exposure_candidates_current WHERE event_id = ? ORDER BY candidate_id",
        (event_id,),
    )
    rows = db.execute(
        "SELECT * FROM impact_assessments WHERE event_id = ? ORDER BY company_id, mechanism_id", (event_id,)
    )
    by_company: dict[str, list[dict]] = {}
    for r in rows:
        by_company.setdefault(r["company_id"], []).append(
            {
                k: r[k]
                for k in (
                    "mechanism_id",
                    "direction",
                    "magnitude_level",
                    "horizon",
                    "assessment_status",
                    "evidence_confidence",
                    "exposure_confidence",
                    "direction_confidence",
                    "magnitude_confidence",
                )
            }
            | {"layers": json.loads(r["affected_lines_json"])["impact_layers"]}
        )
    aggregate = {}
    for cid, items in by_company.items():
        signs = {i["direction"] for i in items} - {"unknown"}
        aggregate[cid] = (
            "mixed"
            if {"positive", "negative"} <= signs or "mixed" in signs
            else next(iter(signs))
            if len(signs) == 1
            else "unknown"
        )
    unresolved = [
        e
        for e in intel["entities"]
        if e.get("entity_type") == "company" and e["relation"] in ("ambiguous", "unresolved")
    ]
    return {
        "event_id": event_id,
        "classification": intel["status"],
        "scope": scope,
        "mechanisms": mechs or [],
        "no_transmission": not mechs,
        "no_transmission_reason": None
        if mechs
        else "no supported T1-T9 mechanism: no demonstrable PSX transmission from this event",
        "exposure_candidates": [dict(c) for c in cands],
        "no_established_exposure": not cands,
        "assessments": by_company,
        "company_aggregate_direction": aggregate,  # opposite signs are never netted (framework §2)
        "unresolved_companies": unresolved,
        "conflicts": intel["conflicts"],
        "review_required": [r["assessment_id"] for r in rows if r["assessment_status"] == "needs_review"]
        + [c["candidate_id"] for c in cands if c["review_status"] == "pending"],
    }


def main(argv: list[str] | None = None) -> int:
    """Local only: runs against a SQLite file. No Turso path exists in this component."""
    import argparse

    from database.connection import SQLiteDatabase

    ap = argparse.ArgumentParser(description="Exposure and T1-T9 impact for a LOCAL SQLite database")
    ap.add_argument("--local-db", required=True)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args(argv)
    db = SQLiteDatabase(args.local_db)
    try:
        s = run(db, synthetic=args.synthetic, limit=args.limit)
    finally:
        db.close()
    print(json.dumps(vars(s), indent=1))
    return 1 if s.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
