# Requirements traceability matrix

Source: [`docs/SPECIFICATION.md`](SPECIFICATION.md) (Master Implementation Specification v2.0).
Every numbered section and sub-section of the specification has at least one row here.
`tests/test_traceability.py` enforces this.

Statuses: NOT STARTED · IN PROGRESS · PARTIAL · BLOCKED · IMPLEMENTED · TESTED.
Something is **TESTED** only when code and an automated test (or a CI job) prove it.
Owner decisions recorded in [`docs/adr/0003-owner-decisions-future-phases.md`](adr/0003-owner-decisions-future-phases.md) are cited as "ADR-0003".

| ID | § | Requirement | Phase | Code / evidence | Test | Status |
|---|---|---|---|---|---|---|
| R-DS-1 | DS | Implementation status register maintained | 0 | `docs/STATUS.md`, this file | `tests/test_traceability.py` | TESTED |
| R-DS-2 | DS | Build in approved milestones; no one-shot build | all | `CLAUDE.md`, `docs/STATUS.md` | owner review gates | IMPLEMENTED |
| R-DS-3 | DS | Do not invent data, access, exposures, prices or estimates | all | `CLAUDE.md`; Phase 0 app shows status only | `test_app_starts_without_errors` | IMPLEMENTED (ongoing rule) |
| R-1.1-1 | 1.1 | Answer what happened, when it happened, when the system learned of it | 2–3 | | | NOT STARTED |
| R-1.1-2 | 1.1 | Classify fact / proposal / unverified / opinion / rumour | 3 | `engines/schema.py` claim_type and status_stage vocabularies | tests/test_intelligence.py::test_rumour_and_unresolved_company_need_review | TESTED (offline; live LLM not connected) |
| R-1.1-3 | 1.1 | Evidence-proven direct/indirect exposure | 4 | | | NOT STARTED |
| R-1.1-4 | 1.1 | Transmission pathway to financials | 5 | | | NOT STARTED |
| R-1.1-5 | 1.1 | Quantify only from sourced inputs, otherwise qualitative + missing list | 5 | | | NOT STARTED |
| R-1.1-6 | 1.1 | Horizon, confidence, downside, counter-evidence, invalidation | 5, 12 | | | NOT STARTED |
| R-1.1-7 | 1.1 | Market reaction, liquidity, priced-in assessment | 12–13 | | | NOT STARTED |
| R-1.1-8 | 1.1 | Point-in-time belief and later accuracy | 14 | | | NOT STARTED |
| R-1.2-1 | 1.2 | No automatic orders, buy/sell instructions or guaranteed predictions | all | README disclaimer; app caption | `test_app_starts_without_errors` | IMPLEMENTED (ongoing rule) |
| R-1.2-2 | 1.2 | No assumption that positive news means attractive at any valuation | 12 | | | NOT STARTED |
| R-1.2-3 | 1.2 | No identical-exposure assumption within a sector | 4 | | | NOT STARTED |
| R-1.2-4 | 1.2 | No automatic trust in social media, brokers, headlines or LLM output | 3, 11 | LLM output validated, quote-checked and scored in Python; rumours flagged | tests/test_intelligence.py::test_invented_claim_and_number_are_removed_and_flagged | PARTIAL (LLM part tested offline; social/broker: Phases 10–11) |
| R-1.2-5 | 1.2 | No merging with the technical engine or shared database | 0 (permanent) | ADR-0001, `scripts/check_independence.py`, base-branch guard in CI | `tests/test_independence.py` | TESTED |
| R-1.2-6 | 1.2 | No circumvention of paywalls, logins, API limits, robots, copyright | 2+ | `collectors/http.py` obeys robots.txt (403 robots = disallow), rate limits; restricted/blocked sources never collected; PSX terms honoured | tests/test_collectors.py::test_robots_disallow_is_respected, tests/test_collectors.py::test_robots_forbidden_means_disallow, tests/test_live_sources.py::test_robots_restriction_is_honoured_live | TESTED |
| R-1.3-1 | 1.3 | New public GitHub repository, code + non-sensitive docs only | 0 | this repo; `.gitignore` | `test_no_secrets_files_committed`, gitleaks CI | TESTED |
| R-1.3-2 | 1.3 | Separate Turso account/database, credentials, backups | 1 | Dedicated Turso DB `psx-news-intelligence`; `database/connection.py`; ADR-0004; backup plan in `docs/DATA_MODEL.md` | tests/test_turso_integration.py::test_connection_and_foreign_keys | TESTED against live Turso from the dev session; skipped in CI until secrets are added (restore test: Phase 14) |
| R-1.3-3 | 1.3 | Separate Streamlit deployment, private / authenticated (ADR-0003) | 6 | `app.py` skeleton only | | NOT STARTED |
| R-1.3-4 | 1.3 | Scheduled processing via GitHub Actions | 7 | `.github/workflows/scheduled-jobs.yml` (manual-only skeleton) | | IN PROGRESS (skeleton) |
| R-1.3-5 | 1.3 | Python for collection, calculations, scoring, backtesting | 0+ | `pyproject.toml` | CI | IMPLEMENTED |
| R-1.3-6 | 1.3 | LLM never sole authority; provider-independent adapter (ADR-0003) | 3 | `engines/llm.py` provider gateway; ADR-0006 | tests/test_intelligence.py::test_claude_provider_is_not_connected_and_never_fakes_output | PARTIAL (adapter tested; Claude provider not connected) |
| R-1.3-7 | 1.3 | Secrets only in Actions / Streamlit Secrets / ignored `.env` | 0 | `config/settings.py`, `.gitignore`, `PSXNI_` secret rule | `test_settings_*`, `test_prefixed_secret_is_allowed`, gitleaks | TESTED |
| R-1.3-8 | 1.3 | Compact storage; no large blobs in database | 1 | Excerpt length CHECKs (≤1000 chars); no blob columns for media/PDF | tests/test_database.py::test_source_item_dedup_and_versioning | IMPLEMENTED |
| R-1.3-9 | 1.3 | Verify current free-tier limits before choosing polling | 1–2, 7 | | | NOT STARTED |
| R-2-1 | 2 | End-to-end flow: sources → … → backtesting | 2–14 | README / ADR-0002 (design only) | | NOT STARTED |
| R-2.1-1 | 2.1 | Collection layer persistence (identity, URL/ID, times, hash, access method) | 1–2 | `collectors/engine.py` persists source identity, canonical URL/ID, published (UTC+raw+offset), collected time, hash, retrieval method, run ID, HTTP status | tests/test_collectors.py::test_collection_persists_items_with_provenance_and_audit | TESTED |
| R-2.1-2 | 2.1 | Relevance layer (score, matched terms, inclusion/exclusion reason) | 2 | `source_items.relevance_score/relevance_reason` columns |  | IN PROGRESS (schema only) |
| R-2.1-3 | 2.1 | Event intelligence layer persistence | 3 | `engines/pipeline.py` creates events with revisions and evidence | tests/test_intelligence.py::test_pipeline_persists_events_evidence_provenance_and_cross_source_assessment | TESTED (offline) |
| R-2.1-4 | 2.1 | Verification layer persistence | 3 | `engines/verification.py`; revision records cross-source assessment | tests/test_intelligence.py::test_primary_confirmation_and_media_corroboration | TESTED (offline) |
| R-2.1-5 | 2.1 | Exposure mapping layer persistence | 4 | `event_companies`, `company_exposures` (evidence required) |  | IN PROGRESS (schema only) |
| R-2.1-6 | 2.1 | Economics layer persistence | 5 | `analyses` (versioned) |  | IN PROGRESS (schema only) |
| R-2.1-7 | 2.1 | Market context layer | 12–13 | | | NOT STARTED |
| R-2.1-8 | 2.1 | Decision support layer (no auto-trade) | 12 | | | NOT STARTED |
| R-2.1-9 | 2.1 | Learning layer (point-in-time snapshots) | 14 | `alerts_predictions` frozen by trigger, `market_outcomes` |  | IN PROGRESS (schema only) |
| R-2.2-1 | 2.2 | Streamlit has no polling or long-running loops | 6 | ADR-0002 | | NOT STARTED |
| R-2.2-2 | 2.2 | Scheduled, incremental, idempotent jobs with run logs | 2, 7 | Incremental (ETag/Last-Modified checkpoints), idempotent writes, `collector_runs` audit; `.github/workflows/scheduled-jobs.yml` | tests/test_collectors.py::test_rerun_with_same_content_is_idempotent, tests/test_collectors.py::test_incremental_conditional_request_uses_checkpoint | PARTIAL (engine tested; scheduled workflow not yet run with Turso secrets and no source is ACTIVE) |
| R-2.2-3 | 2.2 | Separate workflows per source family | 2, 7 | One workflow with per-source frequency via `due_sources` (ADR-0005 explains why not one workflow per family yet) | tests/test_collectors.py::test_scheduler_respects_frequency | PARTIAL |
| R-2.2-4 | 2.2 | Manual backfill with date range, rate limits, dry-run | 2 | `collectors.run --since/--until --dry-run`; per-host rate limit | tests/test_collectors.py::test_backfill_window_filters_by_publication_time, tests/test_collectors.py::test_dry_run_writes_nothing, tests/test_collectors.py::test_per_host_rate_limit | TESTED |
| R-3-0 | 3 | 23 modules share one core (company master, sources, evidence, events, exposure graph) | 1+ | Shared schema: company master, source registry, evidence, events, exposure tables | tests/test_database.py | IN PROGRESS (foundation tested) |
| R-3.1 | 3.1 | News Intelligence (initial sources per ADR-0003) | 2–3 | RSS collectors for Dawn, Business Recorder, Express Tribune (live-tested), The News (feed category unconfirmed); Profit/Mettis/Nukta reviewed, no feed | tests/test_live_sources.py::test_live_feed_dry_run | PARTIAL (collection only; no source ACTIVE until terms approved; extraction Phase 3) |
| R-3.2 | 3.2 | Corporate Intelligence | 2, 8 | PSX disclosures: PSX Terms of Use prohibit automated/systematic retrieval without written permission |  | BLOCKED (needs PSX permission or data licence) |
| R-3.3 | 3.3 | Policy & Regulatory Intelligence | 2, 8 | Official sources reviewed: PBS RSS live-tested; FBR/OGRA/NEPRA/MoF reviewed (no feed/terms); SBP, SECP, Commerce refuse automated access (403) | tests/test_live_sources.py::test_live_feed_dry_run | PARTIAL |
| R-3.4 | 3.4 | Government Decision Tracker | 8 | | | NOT STARTED |
| R-3.5 | 3.5 | Domestic Stability & Geopolitical Risk | 9 | | | NOT STARTED |
| R-3.6 | 3.6 | International Contagion | 9 | | | NOT STARTED |
| R-3.7 | 3.7 | Sector & Industry Intelligence | 9 | | | NOT STARTED |
| R-3.8 | 3.8 | Commodity & Input-Cost Intelligence | 2, 9 | EIA public-domain content, but robots.txt disallows /rss; official EIA API needs a free key. OPEC refuses automated access |  | BLOCKED (needs EIA API key) |
| R-3.9 | 3.9 | Dedicated LPG Intelligence + landed-cost calculator | 9 | | | NOT STARTED |
| R-3.10 | 3.10 | Mutual Fund & Institutional Intelligence | 10 | | | NOT STARTED |
| R-3.11 | 3.11 | Broker Research Intelligence | 10 | | | NOT STARTED |
| R-3.12 | 3.12 | Market Event Investigator | 13 | | | NOT STARTED |
| R-3.13 | 3.13 | Company Relationship & Exposure Map | 4 | | | NOT STARTED |
| R-3.14 | 3.14 | Valuation & Fair Value | 12 | | | NOT STARTED |
| R-3.15 | 3.15 | Investment Opportunity Radar | 12 | | | NOT STARTED |
| R-3.16 | 3.16 | Early Warning & Catalyst Tracker | 8 | | | NOT STARTED |
| R-3.17 | 3.17 | Scenario Simulator | 12 | | | NOT STARTED |
| R-3.18 | 3.18 | Technical confirmation, independent of the technical engine | 13 | ADR-0001 (no integration) | `tests/test_independence.py` (separation part only) | NOT STARTED (module) |
| R-3.19 | 3.19 | Historical Event & Prediction Backtesting | 14 | | | NOT STARTED |
| R-3.20 | 3.20 | Daily Briefing & Alerts | 14 | | | NOT STARTED |
| R-3.21 | 3.21 | Company Financial Statement Intelligence | 8 | | | NOT STARTED |
| R-3.22 | 3.22 | YouTube & Financial Media Intelligence (deferred, ADR-0003) | 2, 11 | 7 channels registered exactly; collection deferred | tests/test_collectors.py::test_watchlist_includes_new_accounts_exactly | IN PROGRESS (watchlist registered; collection Phase 11) |
| R-3.23 | 3.23 | X (Twitter) Intelligence (deferred, ADR-0003) | 2, 11 | 23 X handles + 2 pending registered exactly; official API required | tests/test_collectors.py::test_watchlist_includes_new_accounts_exactly | IN PROGRESS (watchlist registered; collection Phase 11) |
| R-4-1 | 4 | Store supplied URLs/handles as watchlist identifiers; no silent substitution | 1, 11 | `media_accounts` seeded from `database/seed/media_watchlist.json` (exact handles, disabled) | tests/test_database.py::test_watchlist_handles_preserved_exactly | TESTED (identifiers stored; collection: Phase 11) |
| R-4.1-1 | 4.1 | 20 supplied X accounts | 1, 2, 11 | 23 X accounts stored verbatim (3 added in Phase 2), categorised, disabled, `identity_verification='unverified'` | tests/test_collectors.py::test_watchlist_includes_new_accounts_exactly | TESTED (identifiers stored) |
| R-4.1-2 | 4.1 | Donald Trump and Reuters kept in `pending_accounts`; no guessed handles | 1, 11 | Trump / Reuters stored as `pending_handle`, no URL; validation rejects guessed URLs | tests/test_database.py::test_watchlist_validation_rejects_guessed_handles | TESTED |
| R-4.2-1 | 4.2 | 7 supplied YouTube channels | 1, 11 | 7 YouTube channels stored verbatim, disabled | tests/test_database.py::test_watchlist_handles_preserved_exactly | TESTED (identifiers stored) |
| R-4.3-1 | 4.3 | Staged relevance filter (high / conditional / low) before LLM | 11 | `engines/extraction.py::relevance` deterministic pre-filter (single stage) | tests/test_intelligence.py::test_irrelevant_items_skip_the_llm_and_restricted_sources_are_not_processed | PARTIAL (high/conditional/low staging later) |
| R-4.4-1 | 4.4 | Extraction fields for X / YouTube items | 11 | | | NOT STARTED |
| R-4.5-1 | 4.5 | Verified cross-platform identity; @ARNOfficiall unlinked until confirmed | 11 | `media_accounts` CHECK: active requires verified identity; @ARNOfficiall unlinked | tests/test_database.py::test_unverified_media_account_cannot_be_activated | IN PROGRESS (constraint tested) |
| R-4.5-2 | 4.5 | Reposts / syndication not counted as corroboration; event clustering | 11 | `engines/similarity.py` clustering; near-duplicates not independent | tests/test_intelligence.py::test_syndicated_copies_do_not_count_as_independent | TESTED (offline) |
| R-4.5-3 | 4.5 | Prediction tracking by author | 11, 14 | | | NOT STARTED |
| R-4.6-1 | 4.6 | Official X API / authorised providers; quota-aware; no assumption it's free | 11 | ADR-0003 (deferred) | | NOT STARTED |
| R-4.6-2 | 4.6 | YouTube Data API quotas; honest `transcript_status` | 11 | | | NOT STARTED |
| R-5-1 | 5 | 30–50 company universe (KSE-30 + sector additions, expandable; ADR-0003) | 1 | `database/seed/companies.json`: 50 listed (KSE-30 + 20) + FFBL delisted, each from its PSX page with URL, time and SHA-256 | tests/test_database.py::test_company_master_loaded, tests/test_turso_integration.py::test_reference_data_present | TESTED |
| R-5-2 | 5 | Canonical company ID; history of ticker/name changes, mergers, delistings | 1 | `company_identifiers` validity dates, `company_status_history` (FFBL merged into FFC) | tests/test_database.py::test_point_in_time_ticker_and_delisting | TESTED |
| R-5-3 | 5 | Alias dictionary validated against active master | 1 | `company_aliases` + `resolve_alias`; PSX `XD` suffix handled by `base_ticker` | tests/test_database.py::test_alias_resolution, tests/test_canonical.py::test_names_and_tickers | TESTED |
| R-5-4 | 5 | No exposure inferred from sector membership | 1, 4 | Only official PSX sector stored; segments/exposures require source + excerpt | tests/test_database.py::test_company_master_loaded | IMPLEMENTED |
| R-6-1 | 6 | Sector indicator sets (cement … logistics) | 9 | | | NOT STARTED |
| R-7-1 | 7 | Benchmark metadata (grade, location, currency, unit, dates, source, type) | 9 | | | NOT STARTED |
| R-7.1-1 | 7.1 | Mandatory transmission logic (inventory lag, FX, rates, tariffs, logistics, mixed oil impact) | 5, 9 | | | NOT STARTED |
| R-8-1 | 8 | Policy lifecycle stages; proposal ≠ approval ≠ notification ≠ implementation | 1, 8 | `events.status_stage` lifecycle enumeration; revisions preserve every stage | tests/test_database.py::test_event_revisions_preserve_history | IN PROGRESS (schema tested; tracker: Phase 8) |
| R-9-1 | 9 | 10-step event-to-company impact engine | 3–5, 12, 14 | | | NOT STARTED |
| R-9.1-1 | 9.1 | Company impact report fields | 5–6 | | | NOT STARTED |
| R-9.2-1 | 9.2 | Coal-price worked example behaves as specified | 5 | | | NOT STARTED |
| R-10.1-1 | 10.1 | Separate score dimensions; versioned formula; no hidden composite | 12 | | | NOT STARTED |
| R-10.2-1 | 10.2 | Opportunity categories | 12 | | | NOT STARTED |
| R-10.3-1 | 10.3 | Valuation rules (methods, peers, scenarios, diluted shares, staleness flags) | 12 | | | NOT STARTED |
| R-11-1 | 11 | 28-table event-centred schema | 1 | `database/migrations/0001–0005` (35 tables incl. all 28 spec tables; applied on Turso, checksums match) | tests/test_database.py::test_all_spec_tables_exist, tests/test_turso_integration.py::test_all_migrations_applied_with_matching_checksums | TESTED |
| R-11.1-1 | 11.1 | UTC internally, original timestamp/offset preserved | 1 | `database/canonical.py::to_utc` (UTC + raw + offset; no zone guessing) | tests/test_canonical.py::test_timestamps_to_utc | TESTED |
| R-11.1-2 | 11.1 | Dedup by canonical URL / external ID / hash; revisions not overwrites | 1–2 | Canonical URL, content hash, unique keys, versions, duplicate links | tests/test_database.py::test_source_item_dedup_and_versioning, tests/test_database.py::test_syndicated_copy_is_flagged_duplicate | TESTED |
| R-11.1-3 | 11.1 | Indexes on listed fields | 1 | Indexes on ticker/alias, dates, source, URL, hash, status, platform/external_id | tests/test_database.py::test_expected_indexes_exist | TESTED |
| R-11.1-4 | 11.1 | Migrations, versioning, FKs, constraints, transactions | 1 | `database/migrate.py`: checksums, atomic apply, FKs, CHECKs, transactions | tests/test_database.py::test_migrations_are_idempotent, tests/test_database.py::test_failed_migration_applies_nothing, tests/test_turso_integration.py::test_constraints_enforced_on_turso | TESTED |
| R-11.1-5 | 11.1 | Retention policies, compact storage | 1, 7 | Excerpt limits; no blobs. Retention policy: Phase 7 |  | IN PROGRESS |
| R-11.1-6 | 11.1 | Provenance for every AI claim and calculation | 1, 3, 5 | `event_extractions.provenance_json`, model/prompt versions, `llm_calls` | tests/test_intelligence.py::test_pipeline_persists_events_evidence_provenance_and_cross_source_assessment | PARTIAL (AI claims done; calculations: Phase 5) |
| R-11.1-7 | 11.1 | Backup/export + tested restore; no destructive migration without approval | 1, 14 | Destructive migrations refused; backup plan documented; restore test Phase 14 | tests/test_database.py::test_destructive_migration_is_refused | IN PROGRESS |
| R-12-1 | 12 | 14 dashboard pages, built only for implemented modules | 6+ | `app.py` status page only | | NOT STARTED |
| R-12-2 | 12 | UI standard: facts vs. AI interpretation, sources, states, mobile, no fake numbers | 6+ | `app.py` shows no data or placeholder figures | `test_app_starts_without_errors` | IN PROGRESS |
| R-13-1 | 13 | Repository structure per spec (directories added when implemented) | 0+ | ADR-0002 | | IN PROGRESS |
| R-14-0 | 14 | Phase 0: README, ADR, .gitignore, config example, pyproject, lint/test, workflow skeleton, no link to existing project; app starts; secrets absent; CI runs | 0 | see `docs/STATUS.md` Phase 0 checklist | CI on PR #1 | TESTED (approved and merged, PR #1) |
| R-14-P1 | 14 | Phase 1 data foundation and acceptance gate | 1 | `database/`, `docs/DATA_MODEL.md`, ADR-0004 | `tests/test_database.py`, `tests/test_turso_integration.py`, CI | TESTED (approved and merged, PR #2) |
| R-14-P2 | 14 | Phase 2 source collection engine and acceptance gate | 2 | `collectors/`, migration 0006, ADR-0005, `docs/COLLECTORS.md`, `docs/SOURCE_ACCESS_REGISTER.md` | `tests/test_collectors.py`, `tests/test_live_sources.py`, `tests/test_turso_integration.py` | IMPLEMENTED (awaiting owner review) |
| R-14-3…14 | 14 | Phases 3–14 and their acceptance gates | 3–14 | | | NOT STARTED |
| R-15-1 | 15 | Operating prompts 1–8 followed per phase (Prompt 1 audit delivered; Prompt 8 audit at end) | all | Step 1 audit report (delivered in session) | | IN PROGRESS |
| R-16-1 | 16 | Collector tests | 2 | Collector tests: reachability (live), permitted access, canonical URL, timestamps, pagination, rate limit, retry, dedup, repeat runs | tests/test_collectors.py, tests/test_live_sources.py | TESTED |
| R-16-2 | 16 | Event tests | 3 | `tests/test_intelligence.py` | tests/test_intelligence.py | TESTED (offline) |
| R-16-3 | 16 | Exposure tests | 4 | | | NOT STARTED |
| R-16-4 | 16 | Calculation tests | 5 | | | NOT STARTED |
| R-16-5 | 16 | Social tests | 11 | | | NOT STARTED |
| R-16-6 | 16 | Dashboard tests (links, filters, no fake values, states, access control, mobile) | 6 | Phase 0 smoke test only | `test_app_starts_without_errors` | IN PROGRESS |
| R-16-7 | 16 | Security tests: no secrets in history, least privilege, dependency audit, environment separation | 0+ | gitleaks full history + canary; pip-audit (installed env + requirements); installed-source check; independence guard | CI `secret-scan`, `test` jobs; `tests/test_installed_sources.py` | TESTED (least-privilege tokens: Phase 1+) |
| R-16-8 | 16 | Operations tests | 7 | | | NOT STARTED |
| R-16-9 | 16 | Backtest tests | 14 | | | NOT STARTED |
| R-17-1 | 17 | Start small (30–50 companies, 3–5 sources) | 1–2 | ADR-0003 | | NOT STARTED |
| R-17-2 | 17 | RSS / official feeds; ETag / Last-Modified incremental fetch | 2 | RSS first; conditional requests with ETag/Last-Modified checkpoints | tests/test_collectors.py::test_conditional_request_headers_and_304, tests/test_collectors.py::test_incremental_conditional_request_uses_checkpoint | TESTED |
| R-17-3 | 17 | Filter before LLM; cache by content hash + prompt/model version | 3 | Pre-filter + cache by prompt/model/input hash; extracted items not re-sent | tests/test_intelligence.py::test_gateway_ledger_tokens_cost_and_cache | TESTED (offline) |
| R-17-4 | 17 | Usage tracking (X, YouTube, LLM, Actions, Turso, failures) | 1, 2, 7 | Turso usage meter; `collector_runs` counts, durations, HTTP requests; `source_health` view. LLM tokens/cost/outcome per call in `llm_calls` (Phase 3). GitHub minutes later | tests/test_collectors.py::test_source_failure_is_visible_in_health | PARTIAL |
| R-17-5 | 17 | Per-source polling, daily budgets, kill switch, source enable/disable | 0–2, 7 | Per-source `collection_frequency_minutes`, kill switch (engine + workflow variable), lifecycle/enabled gates, DB budgets | tests/test_collectors.py::test_kill_switch_stops_collection, tests/test_collectors.py::test_scheduler_respects_frequency, tests/test_collectors.py::test_non_active_sources_are_never_collected_for_real | TESTED |
| R-17-6 | 17 | Large documents kept outside the database | 1–2 | Documents: only URL, size, type, SHA-256 and dates stored; bodies never stored | tests/test_collectors.py::test_document_versions | TESTED |
| R-18-1 | 18 | Source registry entries with terms, tier, cadence, enabled state | 1–2 | Registry v2: 64 sources with URL, category, terms, licensing, verification, lifecycle (10 statuses), frequency, health; ACTIVE gated by trigger | tests/test_collectors.py::test_active_requires_approved_terms_in_database, tests/test_collectors.py::test_registry_keeps_all_phase1_sources_and_adds_universe | TESTED |
| R-18-2 | 18 | Every conclusion labelled by evidence type | 3+ | Each claim labelled with claim_type; evidence rows carry claim_type | tests/test_intelligence.py::test_pipeline_persists_events_evidence_provenance_and_cross_source_assessment | PARTIAL (events done; impact conclusions: Phase 5) |
| R-18-3 | 18 | Reliability is context, not truth; short excerpts only (copyright) | 2 | Retention modes: metadata only unless terms approved; excerpts capped | tests/test_collectors.py::test_excerpt_only_when_retention_permits | TESTED |
| R-18-4 | 18 | Virality isn't truth; promotion / amplification flagged as signals | 11 | | | NOT STARTED |
| R-18-5 | 18 | Schema-validated LLM output; never sole calculator / verifier / ticker master | 3 | `engines/schema.py` strict validation; Python verifies quotes/numbers/tickers | tests/test_intelligence.py::test_invalid_model_output_is_rejected_not_repaired | TESTED (offline) |
| R-19-1 | 19 | Independent repository DoD | 0 | this repo, CI | CI | TESTED |
| R-19-2 | 19 | Independent database DoD | 1 | Dedicated Turso DB, migrations, `PSXNI_` secrets, connection tests, backup plan | tests/test_turso_integration.py | TESTED against live Turso from the dev session; skipped in CI until secrets are added |
| R-19-3 | 19 | Company seed DoD | 1 | 51 company records, validated ticker/name/sector, PSX-sourced summary | tests/test_database.py::test_seed_validation_passes | TESTED |
| R-19-4 | 19 | News MVP DoD | 2, 7 | 4 publications live-tested, deduplicated, timestamped, traceable; none ACTIVE (terms not located); schedule not yet exercised | tests/test_live_sources.py::test_live_feed_dry_run | PARTIAL |
| R-19-5 | 19 | Event MVP DoD | 3 | ADR-0006, `docs/PHASE_3_ACCEPTANCE.md` | tests/test_intelligence.py | PARTIAL (offline acceptance met; live provider not connected) |
| R-19-6 | 19 | Impact MVP DoD | 4–5 | | | NOT STARTED |
| R-19-7 | 19 | Dashboard MVP DoD | 6 | | | NOT STARTED |
| R-19-8 | 19 | Operations DoD | 7 | | | NOT STARTED |
| R-20-1 | 20 | Final implementation rules (evidence first, company-specific, lifecycle, quantify only when sourced, social = leads, technicals = confirmation, technical engine untouched, one pipeline first, traceability) | all | `CLAUDE.md`, ADR-0001 | `tests/test_independence.py` (separation rule) | IN PROGRESS (ongoing rules) |
| R-A-1 | A | Unresolved identity/access checks (Trump, Reuters, @ARNOfficiall, 5 identities, X plan, YouTube quota) | 11 | ADR-0003 | | NOT STARTED |
| R-B-1 | B | Build sequence followed | all | `docs/STATUS.md` | | IN PROGRESS |
