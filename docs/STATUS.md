# Implementation status register

Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED · TESTED (spec "Document status").
A feature is complete only when code **and** tests prove it. A page or placeholder doesn't count.

## Phases

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Specification and repository bootstrap | TESTED, approved and merged (PR #1) | See Phase 0 checklist below |
| 1 | Data foundation (Turso, migrations, company master) | TESTED, approved and merged (PR #2, merge commit 108cdd6) | See Phase 1 checklist below |
| 2 | Source collection engine | TESTED, approved and merged (PR #5, merge commit 992e4b0); no source ACTIVE; 0006 not yet applied to production | See Phase 2 checklist below |
| 3 | Event extraction and verification | TESTED, approved and merged (PR #11, merge commit 0491deec56adbd10c719eef3039bd7a546c521c6). Offline scope complete; live LLM NOT CONNECTED (BLOCKED, owner decision); 0007 not yet applied to production | See Phase 3 checklist below and `docs/PHASE_3_ACCEPTANCE.md` |
| 4 | Company exposure graph | NOT STARTED | |
| 5 | Impact analysis and Python calculations | NOT STARTED | |
| 6 | Streamlit MVP | NOT STARTED | |
| 7 | Scheduling and operations | NOT STARTED | |
| 8 | Corporate, policy and government modules | NOT STARTED | |
| 9 | Commodities, sectors, domestic/geopolitical risk | NOT STARTED | |
| 10 | Institutional and broker research | NOT STARTED | |
| 11 | YouTube and X collectors | NOT STARTED | |
| 12 | Valuation, scenario and opportunity radar | NOT STARTED | |
| 13 | Market event investigator, optional technical confirmation | NOT STARTED | |
| 14 | Backtesting, alerts and production audit | NOT STARTED | |

## Phase 0 checklist

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| README | `README.md` | Owner review | IMPLEMENTED |
| Independence ADR (permanent) | `docs/adr/0001-independence-from-technical-engine.md` | | IMPLEMENTED |
| Stack ADR | `docs/adr/0002-technology-stack.md` | | IMPLEMENTED |
| Cross-project dependency checks | `scripts/check_independence.py` (+ base-branch copy run on PRs), `.github/CODEOWNERS` | `tests/test_independence.py` (17 tests), CI step | TESTED |
| Installed-dependency source check | `scripts/check_installed_sources.py`, `pip check`, `pip-audit` on installed env + requirements | `tests/test_installed_sources.py`, CI step | TESTED |
| Sanitised specification (C1) | `docs/SPECIFICATION.md` | | IMPLEMENTED |
| Full traceability matrix | `docs/TRACEABILITY.md` | `tests/test_traceability.py` (every spec section traced) | TESTED |
| Owner decisions for future phases (guidance only) | `docs/adr/0003-owner-decisions-future-phases.md` | | IMPLEMENTED |
| Project instructions for Claude Code | `CLAUDE.md` | | IMPLEMENTED |
| `.gitignore` (secrets, DBs, dumps, media) | `.gitignore` | `tests/test_app_skeleton.py::test_no_secrets_files_committed` | TESTED |
| Config example (`PSXNI_` prefix only) | `.env.example`, `config/settings.py` | `test_settings_*`, `test_kill_switch` | TESTED |
| requirements / pyproject | `requirements*.txt`, `pyproject.toml` | Dependency rules in independence check | TESTED |
| Lint / test setup | `pyproject.toml` (ruff, pytest) | `ruff check .`, `pytest` | TESTED |
| CI workflow | `.github/workflows/ci.yml` | Runs on push / PR | IMPLEMENTED (verify first run on GitHub) |
| Scheduled-jobs workflow skeleton | `.github/workflows/scheduled-jobs.yml` | Manual-only; collects nothing | IMPLEMENTED |
| App skeleton starts | `app.py` | `test_app_starts_without_errors` (Streamlit AppTest) | TESTED |
| Secrets absent | Repo + full history | `gitleaks` full-history scan + planted-secret canary in CI | IMPLEMENTED (verify first run on GitHub) |
| No link to existing project | Whole repo | Independence check | TESTED |

## Phase 1 checklist

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| Independent Turso connection + config (`PSXNI_` only) | `database/connection.py`, ADR-0004 | `tests/test_turso_integration.py` (real Turso), `test_connect_*` | TESTED |
| Connection validation + error handling | `Database.validate`, retries, config errors | `test_validate_reports_foreign_keys`, `test_failed_batch_rolls_back` | TESTED |
| Migrations + management | `database/migrations/0001–0005`, `database/migrate.py` | idempotency, checksum, destructive-refusal and atomic-failure tests; applied to Turso | TESTED |
| Source registry (all planned sources, disabled) | `database/seed/sources.json`, `sources` | `test_source_cannot_be_enabled_before_verification`, `test_reuters_not_activatable` | TESTED |
| Company master: 50 listed + 1 delisted, PSX-sourced | `database/seed/companies.json` | `test_company_master_loaded`, `test_seed_validation_*` | TESTED |
| Tickers, aliases, effective-date history | `company_identifiers`, `company_aliases`, `company_status_history` | `test_point_in_time_ticker_and_delisting`, `test_alias_resolution` | TESTED |
| Sector classifications (official PSX) | `sectors`, `company_classifications` | `test_company_master_loaded` | TESTED |
| Event/news, evidence and provenance schemas | `0002_events_and_evidence.sql`, `repositories.py` | `test_event_*`, `test_evidence_*`, Turso store/retrieve test | TESTED |
| Timestamps + timezone handling | `database/canonical.py::to_utc` | `tests/test_canonical.py` | TESTED |
| Canonicalisation + deduplication foundations | `canonical_url`, `content_sha256`, `record_source_item` | `test_source_item_dedup_and_versioning`, `test_syndicated_copy_is_flagged_duplicate` | TESTED |
| Indexes + constraints | migrations | `test_expected_indexes_exist`, constraint tests (SQLite + Turso) | TESTED |
| Data-quality validation | `database/validation.py` | `test_seed_validation_catches_bad_records` | TESTED |
| Data-model documentation | `docs/DATA_MODEL.md` | | IMPLEMENTED |
| Supplied watchlists stored (collection deferred) | `database/seed/media_watchlist.json` | `test_watchlist_handles_preserved_exactly` | TESTED |
| Free-tier quota protection (meter, budget, kill switch, skip-unchanged, indexed lookups) | `database/connection.py`, `0005_dataset_loads.sql`, `seed_loader.py` | `test_turso_usage_is_metered`, `test_turso_budget_stops_further_requests`, `test_kill_switch_blocks_database_requests`, `test_hot_lookups_use_indexes`, `test_seed_load_is_idempotent` | TESTED |
| Backup / restore | plan in `docs/DATA_MODEL.md` | restore test is Phase 14 | IN PROGRESS |
| Turso tests in GitHub CI | `.github/workflows/ci.yml` reads `PSXNI_TURSO_*` secrets | skipped until the owner adds the two repository secrets | BLOCKED (needs owner) |

## Phase 2 checklist

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| Reusable collection pipeline | `collectors/engine.py`, ADR-0005 | `tests/test_collectors.py` | TESTED |
| HTTP reliability: timeouts, retries, backoff, Retry-After, rate limit, robots, conditional requests, size cap | `collectors/http.py` | `test_retry_*`, `test_rate_limited_*`, `test_timeouts_*`, `test_robots_*`, `test_per_host_rate_limit`, `test_conditional_*` | TESTED |
| Parsers: RSS, Atom, JSON API, HTML tables, PDF metadata, timestamps | `collectors/parsers.py` | parser tests (synthetic fixtures in `tests/fixtures/`) | TESTED |
| Provenance, hashing, dedup, versioning, missing timestamps | migration 0006, `record_source_item` | persistence tests | TESTED |
| Run audit, checkpoints, source health | `collector_runs`, `collector_checkpoints`, `source_health` | `test_source_failure_is_visible_in_health` | TESTED |
| Pagination, incremental, backfill, dry run | `fetch_pages`, `collect(since/until)` | pagination / backfill / dry-run tests | TESTED |
| Kill switch, DB budgets, ACTIVE gate | engine + trigger | `test_kill_switch_*`, `test_usage_budget_*`, `test_active_requires_*` | TESTED |
| Single authorisation gate for all entry points: dry runs refused for NOT REVIEWED / RESTRICTED / BLOCKED / LICENCE REQUIRED / DISABLED or any prohibition, before any network request (review F1) | `collectors/engine.py::authorise` (`collect`, `collect_document`, `fetch_pages`) | `test_prohibited_sources_are_refused_before_any_network_request`, `test_restricted_source_with_feed_is_refused_even_if_robots_would_allow`, `test_any_single_prohibition_blocks_a_dry_run` | TESTED |
| Collector status separate from feed freshness (review F4) | `sources.last_test_*`, `newest_item_at_utc`, `freshness_status`; `source_health` | `test_stale_feed_is_shown_as_stale_not_as_working`, `test_validation_refuses_tested_status_for_a_stale_feed` | TESTED |
| Source registry v3 (67 sources; PR #6 and PR #7 findings recorded, none ACTIVE) | `database/seed/sources.json` | `test_registry_*` | TESTED |
| Source access & licensing register | `docs/SOURCE_ACCESS_REGISTER.md` (generated) | `test_source_register_document_is_in_sync` | TESTED |
| Live access: Dawn, Business Recorder, Express Tribune, PBS | dry runs against live feeds | `tests/test_live_sources.py` (opt-in) | TESTED (no source ACTIVE) |
| X watchlist (23 + 2 pending) and YouTube (7) preserved | `database/seed/media_watchlist.json` | `test_watchlist_includes_new_accounts_exactly` | TESTED (collection Phase 11) |
| Scheduled workflow | `.github/workflows/scheduled-jobs.yml` | not yet run with Turso secrets; nothing ACTIVE | IMPLEMENTED |
| PSX disclosures collector | none | PSX terms prohibit automated retrieval without permission | BLOCKED |
| SBP / SECP / Commerce / IMF / OPEC | none | HTTP 403 to automated requests | BLOCKED |
| Energy prices (EIA) | none | robots.txt disallows /rss; API key needed | BLOCKED |

## Phase 3 checklist

Owner approved and merged on 2026-11-07 (PR #11, merge commit `0491deec56adbd10c719eef3039bd7a546c521c6`).
Main CI on the merge commit: test, secret-scan and CodeQL (Python, Actions) passed. Offline acceptance
criteria are met. The rows marked BLOCKED below remain open and are not part of the merged scope.

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| Strict extraction schema + validator (no repair) | `engines/schema.py` | `test_schema_*`, `test_dates_*`, `test_json_schema_is_strict` | TESTED |
| Versioned prompt (no invention, verbatim quotes) | `prompts/event_extraction_v1.txt` | `test_prompt_is_versioned_and_forbids_invention` | TESTED |
| Provider-independent gateway: retries, cache, token/cost limits, kill switch, ledger | `engines/llm.py`, `llm_calls` | `test_gateway_*`, `test_daily_cost_limit_*`, `test_kill_switch_blocks_llm`, `test_llm_ledger_is_append_only` | TESTED |
| Claude provider | `engines/llm.py::ClaudeProvider` | `test_claude_provider_is_not_connected_and_never_fakes_output` | BLOCKED (needs owner approval: SDK dependency, key, budget) |
| Relevance pre-filter, quote and number verification, entity/company resolution | `engines/extraction.py` | `test_extraction_*`, `test_invented_claim_*`, `test_irrelevant_items_*`, `test_rumour_*` | TESTED |
| Importance and confidence with explanations; human-review flags | `engines/extraction.py` | `test_extraction_keeps_only_quoted_facts_and_explains_confidence` | TESTED |
| Duplicate / near-duplicate detection, clustering across publications | `engines/similarity.py` | `test_near_duplicate_and_same_story_clustering` | TESTED |
| Credibility, corroboration, contradiction, timeline | `engines/verification.py` | `test_primary_confirmation_*`, `test_syndicated_*`, `test_contradictions_*`, `test_timeline_*` | TESTED |
| Persistence with provenance (migration 0007, append-only) | `engines/pipeline.py`, `0007_intelligence_engine.sql` | `test_pipeline_*` (local SQLite) | TESTED (not applied to production Turso) |
| Live extraction on real items | | needs live provider and ACTIVE sources | BLOCKED |

## Requirements traceability

The full matrix, covering every section of the specification, is in [`TRACEABILITY.md`](TRACEABILITY.md).
