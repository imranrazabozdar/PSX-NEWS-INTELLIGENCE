# Phase 5 data contract (design)

Design only; nothing is implemented. All names are proposals for review.

## 1. Inputs
| Input | Source of truth | Contract |
|---|---|---|
| Event | `events` (current revision) + `event_evidence` | `verification_state`, `status_stage`, `magnitude`, `horizon`, `event_date`, evidence ids; revision number captured |
| Exposure | **`exposure_candidates_current`** (never the raw table) | `candidate_id`, `current_revision`, `effective_status`, `evidence_currently_valid`, `impact_direction`, `exposure_level`, category/subtype, `rule_id`, `ruleset_version`, `is_synthetic` |
| Exposure evidence | `exposure_candidate_evidence` | role, record ids, source item ids |
| Company financial inputs | `financial_metrics` (sourced) | value, unit, currency, period, basis, `source_item_id` |
| Benchmark inputs | `commodity_prices` (sourced) | grade, location, date, unit, currency, `source_item_id` |
| Transmission rules | versioned library (code) | `rule_id`, `transmission_version` |

## 2. Outputs (per event × company × mechanism)
| Field | Values / meaning |
|---|---|
| `assessment_status` | `confirmed_conclusion` · `provisional` · `scenario_only` · `needs_review` · `needs_revalidation` · `withdrawn` |
| `scenario_kind` | `current` (default) · `hypothetical` · `historical_test`. Only `current` may describe a present factual event; refuted events are restricted to `hypothetical` or `historical_test`. |
| `direction` | positive · negative · mixed · neutral · unknown (Phase 4 vocabulary) |
| `magnitude_level` | low · medium · high · not_assessable |
| `magnitude_basis` | `qualitative` · `deterministic_model` · `financially_quantified` |
| `horizon` | short (≤ 1 quarter) · medium (1–4 quarters) · long (> 1 year) · unknown |
| `scenarios` | base / optimistic / adverse: each a direction, a magnitude level and the stated assumptions |
| `transmission_chain` | ordered steps (driver → mechanism → financial statement line), each with its evidence ids |
| `affected_lines` | revenue, COGS, gross margin, finance cost, FX loss, tax, working capital, capex |
| `quantification` | formula id and version, inputs (with source ids, units, periods), result with unit, sensitivity table; or `null` with `missing_inputs` |
| `counter_evidence` | offsets, lags, reversal conditions, invalidation conditions |
| `market_check` | `not_evaluable` (no lawful market data); reserved for Phase 13 |
| confidence dimensions | see §5 |
| provenance | see §7 |

**Labels never mix.**
- `qualitative`, `deterministic_model` and `financially_quantified` are kept distinct.
- An **observed market reaction is never stored in an impact assessment.** It belongs to
  `market_outcomes` (Phase 14).

## 3. Evidence eligibility (highest priority)
`effective_status` is read from `exposure_candidates_current`:

| Exposure `effective_status` | Confirmed conclusion | Provisional assessment | Scenario-only | Review queue |
|---|---|---|---|---|
| `confirmed` (and evidence currently valid) | **Yes**, if the event is `corroborated` or `primary_confirmed` | Yes | Yes | No (unless contradiction) |
| `strongly_supported` | No (needs human acceptance) | **Yes** | Yes | Yes (for acceptance) |
| `potential` | No | No | **Yes** (labelled) | Yes |
| `unverified` | No | No | **Yes**, only as "exposure not established" | Yes |
| `rejected` | **Never** | Never | Never | No (audit only) |
| `needs_revalidation` (revoked or superseded evidence, source no longer approved) | **Never** | Never | Never | **Yes** (revalidate) |
| Contradictory (Phase 4 contradiction flag, or the event is `disputed`) | Never | No | Yes, with direction `mixed` or `unknown` | **Yes** |
| Missing evidence (no company-specific link) | Never | No | Yes, as "not established" | Yes |

Rules:
1. **Revalidation at read and at write.** Eligibility is evaluated at read time from the view, and
   again immediately before writing. It is never cached from an earlier run.
2. **Revocation propagates.** When any underlying candidate becomes `needs_revalidation`, `rejected`
   or superseded, every assessment built on it moves to `needs_revalidation`, with a new revision.
   Nothing is deleted.
3. **Expiry.** Each exposure input has a freshness horizon: `valid_to`, or the `last_verified_utc` age
   threshold per exposure kind (proposed: 12 months for documented business exposures, one reporting
   period for financial figures). Expired inputs make the assessment `needs_revalidation`.
   **Database enforcement (migration 0009):** every linked company-specific exposure record must have a
   `valid_to` that is a real calendar date (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`) and has not passed by
   the database clock. A missing, impossible, malformed or expired date on **any** linked record blocks the
   upgrade to `provisional` or `confirmed_conclusion`. It also shows the assessment as `needs_revalidation`
   at read time. One fresh record never compensates for a stale one.
   **Linked evidence is immutable:** once an exposure record backs an exposure candidate, the database
   refuses any UPDATE, UPSERT, REPLACE or DELETE that would change its evidentiary fields. Expiry is
   therefore irreversible. To correct a record, retract it and record a new one; a new candidate and new
   human review are then needed before an assessment is eligible again. (Migration 0009 §22. Not yet
   verified on a real Turso server.)
   **Retractions are permanent:** a retraction cannot be updated, deleted or replaced, by REPLACE, UPSERT or a
   conflicting insert on its id or record. Retracted evidence can therefore never regain eligibility.
   (Migration 0009 §23. The REPLACE guards for the remaining tables of migrations 0001–0008 are migration
   0010.)
   **The exposure chain cannot be rewritten:** existing exposure candidates, their evidence links (by rowid
   or by unique key) and their revisions cannot be replaced. A retracted link therefore can't be redirected
   to copied evidence, and candidate history can't be reset. (Migration 0009 §24. Other legacy tables are
   migration 0010; real Turso verification is outstanding.)
   **Not yet database-enforced:**
   - the `last_verified_utc` age thresholds, because no expiry policy is approved yet;
   - expiry of relationship-based evidence;
   - review of the assessment notes `counter_evidence_json`, `missing_inputs_json` and
     `confidence_reasons_json`. Changes to these are recorded in revisions.
4. **Unknown stays unknown.** A mechanism whose sign the rule cannot set, or an exposure with direction
   `unknown`, yields `direction = unknown`. No calculation may infer a sign to complete itself.
5. **Contradiction.** Opposing documented exposures or a disputed event lower direction confidence one
   level, set `mixed` or `unknown`, and require review.
6. **Event verification state:**

   | Event state | Treatment |
   |---|---|
   | `corroborated`, `primary_confirmed` | Normal evidence-eligible assessments, per the table above |
   | `single_source`, `unverified` | At most `provisional`; human review required |
   | `disputed` | At most `provisional` or explicitly `scenario_only`, per the evidence rules. Direction is forced to `mixed` or `unknown`, and human review is **mandatory**. |
   | `refuted` | **No ordinary event-driven impact assessment is generated.** A refuted event may appear only in a separately labelled `hypothetical` or `historical_test` scenario (`scenario_kind`), never as a current factual event. Existing assessments built on an event that becomes refuted move to `withdrawn`, with a revision. |
   | `rumour` stage (any verification) | At most `scenario_only`; review required |

   **Refuted and disputed events are never deleted.** Their evidence, verification history and event
   revisions are preserved (append-only, Phase 1–3).

## 4. Assessment lifecycle
```
scenario_only ─▶ provisional ─▶ confirmed_conclusion
      ▲               │                 │
      └── needs_review ◀─────────────────┤
needs_revalidation ◀── evidence revoked / expired / superseded (from any state)
withdrawn ◀── human rejection (terminal; record kept)
```
- `confirmed_conclusion` needs a human acceptance record, like Phase 4.
- Every state change is a new revision. History is append-only.

## 5. Confidence and uncertainty (five separate dimensions; never combined into one "truth")
| Dimension | Derived from | Scale |
|---|---|---|
| Evidence confidence | event verification and source tier (Phase 3) | low / medium / high |
| Exposure confidence | `effective_status` and exposure basis (Phase 4) | low / medium / high |
| Direction confidence | rule sign certainty, contradictions, lags | low / medium / high |
| Impact magnitude | §6 of the transmission framework (separate from confidence) | low / medium / high / not_assessable |
| Scenario uncertainty | spread between base, optimistic and adverse | narrow / wide / undetermined |

- **Ordinal levels are the default.** A numeric score, if introduced, must be versioned, carry its
  formula and inputs, and be labelled `uncalibrated` until calibrated against Phase 14 outcomes.
- **Every level carries a short reason.**
- **Confidence is never evidence.** High confidence without eligible evidence cannot raise
  `assessment_status`.

## 6. Proposed storage (for a future additive migration 0009; NOT written now)
| Structure | Why | Existing alternative | Integrity | Idempotency / audit | Effect of revocation |
|---|---|---|---|---|---|
| Reuse `analyses` as the per-company summary record | already versioned per event and company | — | add a delete-protection trigger in 0009 (do not edit 0003) | new `analysis_version` per change | summary re-issued as a new version |
| `impact_assessments` (event × company × mechanism) | several mechanisms per company; status lifecycle | `analyses` lacks a per-mechanism key | FKs to events, companies, `analyses`; CHECKs on status, direction, labels | unique key (event, company, mechanism, transmission_version); revision-only updates (Phase 4 pattern) | trigger or engine sets `needs_revalidation` |
| `impact_assessment_inputs` | normalised links to exposure candidates (with revision), event evidence, financial_metrics and commodity_prices | none | FKs; triggers check the inputs belong to the same event or company | append-only | read-time validity view, as in Phase 4 |
| `impact_assessment_revisions` | history | Phase 4 pattern | trigger-written; append-only | — | — |
| `impact_reviews` | human decisions | `exposure_reviews` pattern | reviewer, timestamp, status at decision | append-only | acceptance blocked while inputs are invalid |
| Scenario rows | base/optimistic/adverse per assessment | could be JSON on the assessment | JSON with schema validation, or a child table | part of the revision snapshot | follows the assessment |
| Transmission mechanisms | rule library | **code** (versioned), not a table | `transmission_version` stored on each assessment | — | — |
| Historical snapshots | point-in-time replay | revisions + `alerts_predictions` (Phase 14) | — | — | — |
| Current-validity view `impact_assessments_current` | consumers never read stale conclusions | — | — | — | computes `effective_assessment_status` from inputs |

## 7. Provenance and versioning (required on every assessment)
- event id and revision;
- exposure candidate ids and revisions;
- evidence and source item ids;
- `ruleset_version` (Phase 4), `transmission_version`, `calculation_version` and formula ids;
- schema version; model and prompt version (if an LLM wrote narrative);
- `is_synthetic`. It propagates to company and sector aggregates. Any aggregate with a synthetic input
  is synthetic. Every synthetic output carries `data_label = 'SYNTHETIC TEST DATA'` and must not be
  presented as an actual company exposure, actual event or investment conclusion. The database must
  refuse linking synthetic inputs to a non-synthetic assessment (Phase 4 pattern);
- created and updated timestamps (UTC).

**Re-processing the same inputs with the same versions must produce no new record.** Changing a
version creates a new assessment or a new revision, never an overwrite.
