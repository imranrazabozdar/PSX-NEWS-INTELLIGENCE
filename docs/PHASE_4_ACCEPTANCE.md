# Phase 4 acceptance report: company exposure mapping

Branch `phase-4-exposure-mapping`, based on `main` @ `211760e`. Status: **IMPLEMENTED and TESTED with
synthetic fixtures. Not ACCEPTED (awaiting owner review). Not OPERATIONAL** (no approved
company-evidence source, no ACTIVE source, migration 0008 not applied to production).

Labels used in this report:
- **IMPLEMENTED:** the code exists.
- **TESTED:** an automated test proves the behaviour on synthetic data.
- **EVIDENCE-BACKED:** works on real, approved evidence. Nothing in Phase 4 is evidence-backed yet.
- **AWAITING SOURCES:** needs an approved real-world source.
- **ACCEPTED:** owner approval.
- **OPERATIONAL:** running in production.

## Spec acceptance (§14 Phase 4, §16 exposure tests, §1.2, §5)
| Criterion | Evidence (`tests/test_exposure_mapping.py`) | Result |
|---|---|---|
| Correct direct links from documented exposure | `test_oil_rise_maps_by_documented_exposure_not_by_sector`, `test_pkr_depreciation_splits_exporters_and_importers`, `test_rate_rise_does_not_assume_every_bank_benefits` | TESTED |
| Correct indirect links (sector-level, relationships) | same; `test_unverified_subsidiary_maps_parent_indirectly_with_review` | TESTED |
| Unrelated companies excluded, with reasons | `test_duty_rule_maps_only_companies_in_scope`; sector candidates carry "sector membership alone is not proof" | TESTED |
| No identical exposure within a sector | oil and rate tests (OMC and bank candidates without evidence stay unknown) | TESTED |
| Company-specific variation within sectors | contradictory-evidence and direction tests | TESTED |
| Evidence freshness | `valid_from`/`valid_to` respected; source approval re-checked on each run (`test_persistence_is_idempotent_and_revisions_are_kept`) | TESTED |

## Owner requirements
| Requirement | Test | Status |
|---|---|---|
| Exact, alias and short-name matches | `test_exact_ticker_alias_and_short_name` | TESTED |
| Ambiguous names not auto-selected | `test_ambiguous_partial_name_is_not_auto_selected` | TESTED |
| False positives (lower-case words versus tickers) | `test_lowercase_words_never_match_tickers` | TESTED |
| Similar names | `test_similar_names_resolve_to_the_right_company` | TESTED |
| No invented company or symbol | `test_unknown_company_is_unresolved_and_nothing_is_created` | TESTED |
| Historical names and delisted companies | `test_former_name_*`, `test_delisted_company_resolves_only_historically` | TESTED |
| Parent and subsidiary relationships, constraints | `test_unverified_subsidiary_*`, `test_relationship_constraints` | TESTED; no real rows (AWAITING SOURCES) |
| Positive, negative, mixed, neutral and unknown; UNCERTAIN → unknown | `test_direction_lookup_and_neutral_distinct_from_unknown`, rule tests | TESTED |
| Missing evidence visible | `test_unapproved_evidence_stays_unverified`, `test_oil_fall_reverses_and_unclear_change_stays_unknown` | TESTED |
| Contradictory evidence | `test_contradictory_exposure_evidence_is_flagged` | TESTED |
| Rumours, disputed events, high-impact single source | `test_rumour_and_disputed_events_need_review`, `test_strong_and_potential_depend_on_event_verification` | TESTED |
| Confidence is not proof | `test_confidence_is_not_proof` | TESTED |
| Unsupported LLM assertions rejected and audited; versions kept | `test_llm_suggestions_are_validated_and_stay_suggestions`, `test_invalid_llm_output_is_rejected` | TESTED (fixture provider) |
| Kill switch; no live LLM | `test_llm_unavailable_or_kill_switch_produces_nothing` | TESTED |
| Duplicates, revisions, audit history, rule versioning | `test_persistence_is_idempotent_and_revisions_are_kept`, `test_candidate_table_constraints` | TESTED |
| Human review: accept only strong evidence; append-only | `test_review_accepts_only_strong_evidence_and_promotes_to_event_companies` | TESTED |
| PSX profile text not used as evidence | `test_psx_profile_text_is_never_used_as_exposure_evidence` | TESTED |
| Real-world exposure mapping | needs approved company-report sources | AWAITING SOURCES |

## Checks
| Check | Result |
|---|---|
| Independence guard, ruff | pass |
| pytest | 188 passed, 11 skipped (5 opt-in live-source, 6 Turso: not configured by design) |
| pip-audit | no known vulnerabilities |

## Not done (by instruction)
- Phase 5 (impact sizing, share-price effects), valuation and dashboards.
- Production migrations, source activation, live LLM, purchases.
