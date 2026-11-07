# Phase 4 acceptance report: company exposure mapping

PR #15 was **ACCEPTED by the owner and merged** on 2026-11-07 (merge commit `0bdfb1a08de7dae9ea37899f4d93c10892b32e59`; final PR head
`7099f08`). Main CI on the merge commit: test pass, secret-scan pass, CodeQL Python pass, CodeQL
Actions pass.

Status: **TESTED with synthetic fixtures and ACCEPTED. NOT OPERATIONAL.**
- No approved company-evidence source exists and no source is ACTIVE.
- Real company exposure mappings remain unverified.
- Migration 0008 is not applied to production.
- Turso compatibility is unverified on a real Turso server.
- Deeper cycle protection is application-level only.
- Downstream consumers must use `exposure_candidates_current`.

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
| pytest | 208 passed, 11 skipped (5 opt-in live-source, 6 Turso: not configured by design) |
| pip-audit | no known vulnerabilities |

## Database-integrity review (owner, 2026-11-07)
| Finding in the first version of 0008 | Correction | Tests |
|---|---|---|
| A candidate could be inserted without revision 1, because the application wrote it | `AFTER INSERT` trigger writes revision 1; inserts must start at 1 | `test_every_candidate_has_revision_one_written_by_the_database`, `test_failed_batch_leaves_no_candidate_or_revision` |
| Evidence was a JSON id list: any non-empty array passed | normalised `exposure_candidate_evidence` with foreign keys and ownership triggers | `test_fabricated_and_foreign_evidence_links_are_refused` |
| `strongly_supported` could be inserted or updated by direct SQL | inserts only `unverified`/`rejected`; upgrades re-checked against links, approved sources and event verification | `test_direct_sql_cannot_create_strong_or_confirmed_candidates`, `test_status_cannot_be_raised_or_confirmed_without_real_evidence_and_review`, `test_downgraded_evidence_blocks_strong_status` |
| `confirmed` needed only `review_status = 'accepted'`, a field anyone could set | `confirmed` needs a prior strongly supported status and `last_review_id` pointing to an immutable `accept` review with reviewer, timestamp and status at decision; `event_companies` acceptance requires a confirmed candidate | same, plus `test_review_accepts_only_strong_evidence_and_promotes_to_event_companies` |
| Revisions could be hand-inserted out of order | only the current revision can be inserted (by trigger); no update or delete | `test_revisions_are_immutable_and_cannot_be_forged` |
| Relationships could be edited or deleted silently; no cycle checks | append-only with superseding corrections, view of current rows, self, direct and deep cycle checks | `test_relationships_are_append_only_with_correction_history`, `test_relationship_cycles_are_refused`, `test_relationship_constraints` |
| Synthetic data could support a real mapping | `sources.is_synthetic`; triggers refuse synthetic evidence on non-synthetic rows; the whole batch rolls back | `test_synthetic_evidence_cannot_support_a_real_mapping` |
| Parent-company candidates reused the child's exposure rows | the parent's evidence is only the relationship row; without a cited source the candidate stays unverified | `test_unverified_subsidiary_maps_parent_indirectly_with_review` (now persisted) |

All tests now persist through the database, so every status the application assigns is re-checked by
the triggers.

## Final acceptance audit (owner, 2026-11-07)

### Database-level guarantees (migration 0008)
- **Revisions:** revision 1 and every later revision are written by triggers. Revisions can't be
  inserted out of order, updated or deleted, and a candidate's identity is fixed.
- **Evidence links:** real foreign keys with ownership checks. Each link must belong to the candidate's
  event, or to its company as owner or parent, and match its source item. Links are append-only.
- **Status upgrades:** candidates are inserted as `unverified` or `rejected` only. `potential` and above
  require company-specific evidence that is currently valid (`invalid_candidate_evidence` is empty for
  the candidate). Currently valid means:
  - the source is ACTIVE, with approved terms, verified access and enabled = 1;
  - the record is not retracted;
  - the relationship is not superseded or rejected.
- **Strong and confirmed:** `strongly_supported` also needs a corroborated or primary-confirmed event.
  `confirmed` needs a prior strongly supported status plus an immutable `accept` review.
- **Reviews:** reviewer, timestamp and status-at-decision are required, and reviews are append-only. An
  `evidence_revoked` review is only possible when some linked evidence really is invalid.
- **Shortcuts closed:** accepted `event_companies` links require a confirmed candidate. Synthetic sources
  and relationships can't support a non-synthetic candidate or relationship.
- **Relationships and retractions:** relationships are append-only (corrections supersede). Self-links
  and direct A↔B cycles are refused. Evidence retractions are append-only and must name a real record.
- **Read-time guard:** the `exposure_candidates_current` view reports `effective_status =
  needs_revalidation` as soon as evidence becomes invalid, even before revalidation runs. It also labels
  synthetic rows.

### Application-level guarantees
- **Atomic writes:** each candidate, its links and its status assessment are written in one batch.
- **Revalidation:** `revalidate()` downgrades every potential, strong or confirmed candidate with invalid
  evidence. It writes an `evidence_revoked` review and a revision, and resets the `event_companies` link
  to pending. `retract_evidence()` records a retraction and then revalidates.
- **Re-runs:** retracted exposures and superseded or rejected relationships are skipped, and real runs
  ignore synthetic relationships.
- **Cycles deeper than A↔B** are refused in `record_relationship`, the only application path that writes
  relationships; a test enforces this.
- **Labelling:** synthetic explanations are prefixed `[SYNTHETIC TEST DATA]`.

### Relationship cycles: limitation
Self-links and direct A↔B cycles are refused by the database. Longer cycles (A→B→C→A and beyond),
including those that a correction would reintroduce, are refused **in application code only**. A
direct SQL insert can still create a deeper cycle. A recursive check inside a trigger worked on
SQLite 3.53, but it was left out until it is verified on the Turso server.

### Evidence revocation behaviour
| Change | Result | Test |
|---|---|---|
| Source ACTIVE → DISABLED | view shows `needs_revalidation`; `revalidate` downgrades confirmed → unverified and resets `event_companies` to pending; history kept | `test_source_changes_revoke_confirmed_mappings_without_deleting_history[...DISABLED...]` |
| Terms no longer approved | same | `[...terms_status...]` |
| Source restricted | same | `[...restricted...]` |
| Evidence record found incorrect | `retract_evidence` (append-only); mapping downgraded; record kept; re-runs no longer use it | `test_retracted_evidence_revokes_and_is_kept` |
| Relationship superseded or rejected | parent mapping downgraded; both relationship rows kept | `test_superseded_or_rejected_relationship_revokes_parent_mapping` |

A downgraded candidate can't be raised again while its evidence stays invalid; the database refuses it.

### Synthetic-data isolation
| Requirement | Result |
|---|---|
| Synthetic evidence can't support a real candidate | refused by trigger; the whole batch rolls back |
| Synthetic relationships can't support a real candidate | real runs skip them, and the trigger refuses the link |
| Visibly labelled | `is_synthetic`, `data_label = 'SYNTHETIC TEST DATA'` in the view, explanation prefix |

### Turso compatibility: NOT VERIFIED against a Turso server
No disposable Turso database is available, and production was deliberately not used. Evidence gathered
locally, in a throwaway scratch environment outside the project's dependencies:

- **SQLite 3.47.0** (the version the production Turso server reports), via `sqlean.py==3.47.0` as a
  drop-in `sqlite3`: all exposure, database, intelligence and collector tests pass, with 0001–0008
  applied.
- **libSQL embedded engine** (`libsql-experimental`, SQLite 3.45.1 base): all 8 migrations
  (175 statements) apply.
  - Revision-1 trigger, forged-status refusal, confirmation-by-field-flip refusal, revision append-only,
    direct-cycle refusal and relationship append-only all behave as on SQLite.
  - The read view works.

Features used by 0008, all of which worked on both engines:
- `ALTER TABLE … ADD COLUMN` with CHECK;
- triggers with `RAISE(ABORT)`, multi-statement bodies, subqueries and views referenced from triggers;
- `json_object`/`json`;
- an expression unique index (`COALESCE`).

Open questions for a real Turso test:
1. Do these behave identically on the hosted server through the Hrana HTTP pipeline?
2. Does the statement splitter handle `BEGIN … END` trigger bodies over HTTP?
3. Are there any server-side limits on trigger or view complexity?

**Production migration approval stays blocked until 0006–0008 are checked on a disposable Turso
database.**

## Not done (by instruction)
- Phase 5 (impact sizing, share-price effects), valuation and dashboards.
- Production migrations, source activation, live LLM, purchases.
