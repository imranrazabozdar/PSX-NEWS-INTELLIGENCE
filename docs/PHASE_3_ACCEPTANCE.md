# Phase 3 acceptance report: event extraction and verification

PR #11, **approved by the owner and merged** on 2026-11-07 (merge commit
`0491deec56adbd10c719eef3039bd7a546c521c6`). Status: **TESTED offline, complete for the offline scope. Live LLM
NOT CONNECTED.** Final checks on head `9b9324c`:
- local: independence guard and ruff pass; pytest 160 passed, 11 skipped (5 opt-in live-source, 6 Turso);
  pip-audit clean;
- GitHub: test, secret-scan and CodeQL pass ("No new alerts in code changed by this pull request");
- main CI on the merge commit passes.

## Spec acceptance (§14 Phase 3, §16 event tests, §19 Event MVP)

| Criterion | Evidence | Result |
|---|---|---|
| Malformed JSON rejected | `test_invalid_model_output_is_rejected_not_repaired`, `test_schema_accepts_valid_and_rejects_extra_missing_and_bad_vocab` | PASS (offline) |
| Every claim cites a source item | `test_invented_claim_and_number_are_removed_and_flagged`, `test_pipeline_persists_events_evidence_provenance_and_cross_source_assessment` (evidence row with verbatim excerpt) | PASS (offline) |
| Unknown stays unknown | `test_dates_must_be_iso_and_unknown_dates_stay_unknown` | PASS (offline) |
| Date extraction / stage distinction | schema date rule, stage vocabulary, `test_timeline_orders_and_marks_stage_changes` | PASS (offline) |
| Conflicting claims | `test_contradictions_are_detected_and_lower_confidence` | PASS (offline) |
| Unsupported ticker rejection | `test_rumour_and_unresolved_company_need_review` | PASS (offline) |
| Duplicate / near-duplicate / clustering | `test_near_duplicate_and_same_story_clustering`, `test_syndicated_copies_do_not_count_as_independent` | PASS (offline) |
| Model/prompt versioning, token and cost tracking, retries, budget, kill switch | `test_gateway_*`, `test_daily_cost_limit_*`, `test_kill_switch_blocks_llm`, `test_llm_ledger_is_append_only` | PASS (offline) |
| Provenance on every extraction | pipeline test asserts provenance keys | PASS (offline) |
| Live extraction on real items | needs approved LLM provider, key and budget | NOT CONNECTED |

## Sources and access status
Phase 3 adds no sources and makes no network calls. It processes only stored items from sources that
are not restricted, blocked or licence-required. No PSX data is used. All test items are synthetic
and labelled `SYNTHETIC FIXTURE`.

## Remaining / blockers
1. Owner approval for the live provider: add the official `anthropic` SDK dependency, issue
   `PSXNI_ANTHROPIC_API_KEY` via the secret store, and confirm the daily budget.
2. Phase 2 is merged (PR #5). Migrations 0006 and 0007 must still be applied
   to production Turso. Neither has been applied by this branch.
3. No source is ACTIVE yet, so there are no real items to extract (Phase 2 terms reviews).
4. Calibrate thresholds on owner-reviewed real items. Build the human-review queue UI (Phase 6).
