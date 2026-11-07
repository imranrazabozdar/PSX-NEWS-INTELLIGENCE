# Phase 5 implementation roadmap (proposal)

Each step is a separate, reviewable PR and needs owner approval. **Development and production
activation are separate tracks.**

## Track A — development (synthetic only; local and CI databases)
| Step | Deliverable | Depends on | Gate |
|---|---|---|---|
| A0 | Owner approves this readiness review (the Phase 5 / 12 / 13 / 14 scope split is already approved; see the readiness review §4) | — | Owner |
| A1 | Migration 0009 design PR (additive): `impact_assessments`, inputs, revisions, reviews, current-validity view, delete protection for `analyses` | A0 | Owner review of the schema |
| A2 | Evidence-eligibility gate on `exposure_candidates_current`, plus revocation propagation | A1 | Tests S9–S11 |
| A3 | Transmission library T1–T5 (versioned), direction rules, qualitative magnitude | A2 | Tests S1–S5, S7, S12, S15 |
| A4 | T6–T9, scenarios, horizons, aggregation (company and sector) | A3 | Tests S8, S13, S14 |
| A5 | Unit-aware calculators and sensitivity (synthetic inputs only) | A3 | Tests S16, S17; spec §14 formula tests |
| A6 | Review and correction workflow, report structure (spec §9.1), provenance completeness | A4, A5 | Bypass tests; acceptance report |
| A7 | Phase 5 acceptance PR | A6 | Owner accepts. **"Accepted, not operational."** |

**PR #13 (Module 24):** an optional alignment dependency, not a Track A prerequisite. Steps A0–A7,
including T1–T9, do not require PR #13 to be merged. Integration with the Global Energy & Oil Shock
Monitor is a separate, later task once PR #13 is decided.

## Track B — production activation (blocked; separate approvals)
| Step | Requirement |
|---|---|
| B1 | Disposable-Turso verification of 0006–0009 |
| B2 | Owner approval to apply the migrations to production |
| B3 | At least one approved event source, right by right (PR #17) |
| B4 | At least one approved company-evidence source |
| B5 | Optional: live LLM decision (D2) |
| B6 | Quantification on real companies only with sourced `financial_metrics` and `commodity_prices` |
| B7 | Market check (spec §9 step 8) only with a licensed market-data source (PR #17 §A6) |

No Track B step is implied by completing Track A.

## Explicitly out of scope
- Phase 6 dashboards.
- Phase 12: the editable scenario simulator, valuation and the opportunity radar.
- Phase 13: market reaction investigation.
- Phase 14: backtesting, outcome validation and alerts.
- Buy/sell recommendations or price targets.
