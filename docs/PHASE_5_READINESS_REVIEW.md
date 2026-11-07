# Phase 5 readiness review: impact analysis

Documentation only. Prepared 2026-11-07 on `main` @ `c9de6bc`. **Phase 5 is not implemented or
authorised by this document.** No migration, source, collector, API or LLM was touched.

## Verdict: **CONDITIONALLY READY — SPECIFIED PREREQUISITES REMAIN**
The deterministic core of Phase 5 can be built and tested **now** against synthetic fixtures in local
and CI databases. That core covers evidence eligibility, transmission chains, qualitative direction
and magnitude, scenarios, the separate confidence dimensions, aggregation, review and provenance.

Four things are **blocked**, and none of them can be faked:
- quantified financial impact on real companies;
- the market check (spec §9 step 8);
- any production run;
- any claim about real companies.

The conditions are listed in §5. The verdict is not "READY", because Phase 5 cannot produce a single
real, evidence-backed conclusion until an approved source exists.

## 1. Scope per the specification
- **Spec §14, Phase 5:** "Build transmission chains, qualitative fallback, sourced-input financial
  calculators, sensitivity and missing-input handling. Acceptance: formulas tested with units; no
  unsupported quantitative estimates."
- **Spec §9:** Phase 5 covers steps 5 (Trace), 6 (Quantify) and 7 (Counter-check). It feeds steps 8–10
  (market check, prioritise, learn), which belong to Phases 12–14.
- **Spec §7.1:** mandatory transmission logic.
- **Spec §9.1:** report fields.
- **Spec §9.2:** the coal worked example.

## 2. Existing capabilities (verified in code on `main`)
| Capability | Where | Use in Phase 5 |
|---|---|---|
| Verified events with stage, verification state, magnitude, horizon, revisions | `events`, `event_revisions` (0002), Phase 3 `engines/verification.py` | Input (event layer) |
| Claim-level evidence with verbatim excerpts | `event_evidence` (0002) | Evidence provenance |
| Exposure candidates with evidence links, evidence status, append-only revisions and reviews | `exposure_candidates*`, `exposure_reviews` (0008) | Exposure input |
| **Read-time validity** (`effective_status`, `evidence_currently_valid`, `data_label`) | view `exposure_candidates_current` (0008) | **The only permitted exposure input** |
| Evidence revocation and revalidation | `invalid_candidate_evidence`, `evidence_retractions`, `revalidate()` | Propagation trigger for impact revalidation |
| Five versioned driver rules (oil, rate, PKR, gas, duty) plus relationship propagation | `engines/exposure_rules.py` (`exposure-rules/1.0.0`) | Starting set of transmission drivers |
| Company financial facts with source | `financial_metrics` (0003, `source_item_id` required) | Quantification inputs (no rows yet) |
| Commodity and benchmark prices with source | `commodity_prices` (0003) | Quantification inputs (no rows yet) |
| Analysis records (quantitative/qualitative, missing inputs, versions) | `analyses` (0003, no-update trigger) | Partial fit; see §4 |
| Frozen theses and outcomes | `alerts_predictions`, `market_outcomes` (0003) | Phase 14, not Phase 5 |
| LLM gateway with budgets, kill switch, ledger, prompt versions | `engines/llm.py` | Optional narrative only; **live LLM not connected** |

## 3. Missing prerequisites
| # | Prerequisite | Needed for | Status |
|---|---|---|---|
| P1 | Approved company-specific evidence source (annual reports / IR, or a licensed provider) | Any non-synthetic exposure above `unverified`; any quantification | **Missing** (PR #17; `SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`) |
| P2 | Approved event sources | Real events | **Missing** (no source ACTIVE) |
| P3 | Live LLM (optional; Phase 3 extraction) | Real event extraction from text | **Not authorised** |
| P4 | Lawful market data | Spec §9 step 8 (market check), observed reaction | **Missing**; licensed provider only (PR #17 §A6) |
| P5 | Disposable Turso verification of 0006–0008 (and later 0009) | Any production migration | **Not done** |
| P6 | Owner decision on Phase 5 scope vs Phase 12 (scenario simulator, valuation) | Scope boundary | **Recommendation in §6** |
| P7 | *Optional alignment, not a prerequisite:* PR #13 (Module 24, Page 15) | later Module 24 integration only | Open. **Not required** for Phase 5 synthetic development: T1–T9 are built and tested without it. Integration with Module 24 is a separate later step. |

## 4. Inconsistencies found (spec vs implementation vs this design)
1. **`analyses` table (0003):**
   - It has a no-update trigger but **no delete protection**.
   - It has **no evidence links** (only a free-text `transmission`).
   - It has a **single `confidence`**, while Phase 5 needs five separate dimensions.
   - It has **no revalidation state**.
   - `UNIQUE(event_id, company_id, analysis_version)` allows only one assessment per pair per version,
     but several mechanisms per company are needed.

   *Recommendation:* in a future additive migration, keep `analyses` as the versioned per-company
   summary and add normalised child structures (see `PHASE_5_DATA_CONTRACT.md` §6). Do not rewrite 0003.
2. **`event_companies`:** it holds one row per event and company and is written only on Phase 4
   acceptance. Phase 5 must **not** read it as the exposure source; use `exposure_candidates_current`.
3. **Market check:** spec §9 step 8 requires market data. No lawful source exists (PR #17 §A6), so
   Phase 5 outputs must record the market check as `not_evaluable`.
4. **Scenario Simulator:** that is spec module §3.17, built in Phase 12. **Owner decision
   (approved):**

   | Phase | Scope |
   |---|---|
   | Phase 5 | evidence-linked transmission chains; qualitative direction and magnitude; base, optimistic and adverse **qualitative** scenario framing; separate confidence dimensions; unit-aware calculators (initially synthetic inputs); company and sector aggregation with provenance; human review and correction |
   | Phase 12 | the **editable scenario simulator**; valuation and opportunity ranking |
   | Phase 13 | market reaction investigation |
   | Phase 14 | backtesting and outcome validation |

   The master specification is not changed.
5. **Coverage gap:** Phase 4 has driver rules for oil, rates, PKR, gas and duties only. Spec §7.1 also
   requires input-cost and inventory lag, border/port disruption, and tariff or tax pass-through.
   Electricity, inflation, IMF and fiscal mechanisms have no rules yet. See
   `PHASE_5_TRANSMISSION_FRAMEWORK.md`.
6. **Event magnitude** (`events.magnitude`) is event-level. Company-level impact magnitude is a
   separate concept and must not be copied from it.
7. **`revalidate()` is not scheduled anywhere.** Phase 5 must read the view (read-time guard) and
   must re-check before every write, not rely on a prior revalidation run.

## 5. Conditions before implementation and after it
- **Before implementation:**
  - owner approval of this design (the scope in §4 item 4 is approved);
  - the migration-0009 design reviewed (still local and CI only).
- **Before any real-data claim:** P1 and P2, each source approved right by right.
- **Before production:** P5, plus separate approval.
- **Before quantification on real companies:** sourced `financial_metrics` and `commodity_prices` rows
  from approved sources.

## 6. What can be developed safely now (synthetic only)
- Evidence-eligibility gate on `exposure_candidates_current`.
- Transmission-chain library (versioned rules) and qualitative direction and magnitude.
- Scenario framing; separate confidence dimensions; company and sector aggregation.
- Review, correction and revalidation propagation; provenance and versioning.
- Unit-aware calculators exercised with synthetic, clearly labelled inputs.
- Report structure for spec §9.1, without dashboards (Phase 6).

## 7. What remains blocked
- Real events, real exposures and real financial inputs.
- Market reaction and priced-in assessment.
- Live LLM narrative.
- Production migrations and scheduling.
- Any dashboard output (Phase 6).

## 8. Risks
| Risk | Mitigation |
|---|---|
| Synthetic outputs mistaken for real conclusions | fictional companies and synthetic tickers in fixtures; `syn`-prefixed synthetic sources; `is_synthetic` propagated through assessments and company/sector aggregates; `data_label` in every view and report; mixing refused by the database; no synthetic data in production Turso |
| Refuted events treated as fact | no current assessment for refuted events; only labelled hypothetical or historical-test scenarios; history kept |
| Stale evidence silently kept | eligibility is re-evaluated at read and at write; assessment status follows evidence (`PHASE_5_DATA_CONTRACT.md` §4) |
| Unknown direction forced to a sign | contract rule: unknown stays unknown; tests assert it |
| False precision from scores | ordinal levels by default; any numeric score versioned, labelled "uncalibrated" |
| Scope creep into valuation or alerts (Phases 12–14) | roadmap gates |
| Turso trigger incompatibility | disposable-Turso verification before production |
