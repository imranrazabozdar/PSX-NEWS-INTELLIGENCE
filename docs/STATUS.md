# Implementation status register

Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED · TESTED (spec "Document status").
A feature is complete only when code **and** tests prove it. A page or placeholder doesn't count.

## Phases

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Specification and repository bootstrap | TESTED, approved and merged (PR #1) | See Phase 0 checklist below |
| 1 | Data foundation (Turso, migrations, company master) | TESTED, approved and merged (PR #2, merge commit 108cdd6) | See Phase 1 checklist below |
| 2 | Source collection engine | TESTED, approved and merged (PR #5, merge commit 992e4b0). 2026-11-08: owner approved 11 sources (10 RSS feeds, metadata only, and the SCS chart feed for PSX OHLCV). They are ACTIVE in the seed registry, and real collection is verified locally. Not yet loaded into or applied to production. | See Phase 2 checklist below |
| 3 | Event extraction and verification | TESTED, approved and merged (PR #11, merge commit 0491deec56adbd10c719eef3039bd7a546c521c6). Offline scope complete; live LLM NOT CONNECTED (BLOCKED, owner decision); 0007 not yet applied to production | See Phase 3 checklist below and `docs/PHASE_3_ACCEPTANCE.md` |
| 4 | Company exposure graph | TESTED with synthetic fixtures, approved and merged (PR #15, merge commit 0bdfb1a08de7dae9ea37899f4d93c10892b32e59); NOT OPERATIONAL: no approved company-evidence source, real mappings unverified; 0008 not applied to production; Turso server compatibility unverified | See Phase 4 checklist below and `docs/PHASE_4_ACCEPTANCE.md` |
| PSX feed ingestion (side track) | TESTED offline (36 tests: parser, router and runner safety rules, store upsert, and end-to-end receiver ingest). Committed on `feature/financial-pdf-reconciliation` at 3dc9bc8; NOT merged to main; NOT DEPLOYED. Ready for owner review, not live deployment. Components: `engines/psx_feed_parser.py` (frozen dataclasses, latin-1 in-memory ZIP), `engines/document_router.py` (edge URLs only for feed-disclosed doc IDs), `engines/termux_node_runner.py` (trading-hours gate, polite HTTP, SQLite dedup), migration 0015 `psx_announcements` with idempotent upsert in `database/psx_announcements.py`, and the stdlib WSGI receiver `services/psx_announcement_receiver.py` (POST /ingest/psx-announcement, bearer token `PSXNI_ANNOUNCE_INGEST_TOKEN`, fails closed when unset). Open items: owner approval for deployment; open-mirror resolver disabled by default pending legal review; live feed not run; Turso disposable suite NOT RUN (no target); Pydantic not admitted. | `tests/test_psx_feed_parser.py`, `tests/test_psx_router_runner.py`, `tests/test_psx_announcements_store.py`, `tests/test_psx_e2e_ingest.py` |
| Financial PDF layer 3: PUCAR earnings-declaration parser | TESTED offline (45 tests: two REAL annual-report statement pages from the supplied files, a manufacturing PKR '000 table and a bank USD '000 table, plus synthetic PUCAR layouts for the 4-column quarterly table and split labels; not PSX letterheads): `engines/pucar_statement_parser.py`, standard library only, reads raw text, returns a frozen `PucarFinancialResult` with `scale`, `currency`, warnings, and PKR-normalised `*_pkr` properties (None for non-PKR statements). NOT connected to any pipeline; NOT validated against real PSX letterheads (none supplied; the uploaded PDFs are annual reports). | `tests/test_pucar_statement_parser.py`, `tests/fixtures/pucar/` (see SOURCES.md) |
| Financial reconciliation wiring (layer 3 end) | TESTED offline: migration 0016 `psx_financial_results` (unique on symbol, period_ended, period_type) and `psx_reconciliation_status` (per announcement: reconciled or no_figures); repository `database/psx_financial_results.py` (idempotent upsert; a re-parse fills and refreshes figures but never erases a stored one); coordinator `engines/financial_reconciler.py` `reconcile_announcement_statement()`. Test links are synthetic. NOT connected to any live feed; NOT DEPLOYED; Turso server path unverified; disposable Turso suite NOT RUN. | `tests/test_financial_reconciliation_e2e.py`, `database/psx_financial_results.py`, `engines/financial_reconciler.py` |
| Real-report regression (archive path) | PINNED offline: UBL Annual Report 2025 (unconsolidated pp. 42-45, 98), LUCK Annual Report 2026 (pp. 34-42; 2025 values are the printed comparatives), OGDC Annual Report 2026 standalone (pp. 5-10, spread halves). Text fixtures with source SHA-256, pdftotext 24.02.0 and extractor version in each manifest; every pinned value has its PDF page; pipeline check statuses reproduced from text. Regenerate from vault: `scripts/regenerate_real_report_fixtures.py`. Five statements per company and column reconcile from the text (coverage matrix: `docs/coverage/EXTRACTION_COVERAGE.md`, 30 of 30 green cells, 3 of 51 seeded companies). Vault re-check: run with PSXNI_DOCUMENT_VAULT. | `tests/test_real_report_regression.py`, `tests/fixtures/real_reports/` | 
| Role guard completeness (F6) | IMPLEMENTED and TESTED: operational, archive and portfolio table sets derived from the migration directories; a table in the wrong role, an unknown migration directory, or an archive-named table in the news migrations fails a test. Completeness only: nothing moved or dropped. | `database/connection.py`, `tests/test_role_guard_completeness.py` | 
| PSX export fail-closed (F1) | IMPLEMENTED and TESTED: UNIX compress (1f 9d) and other binary input raise instead of returning zero rows. `psx_exports.py` is a dead-code removal candidate, not deleted (owner decision). | `engines/psx_exports.py`, `engines/psx_feed_parser.py`, `tests/test_psx_fail_closed.py` | 
| Archive fact provenance (migration 0006) | TESTED offline: every versioned fact and reconciliation result stores the source SHA-256 (`report_sha256`), refused on mismatch; view `v_fact_provenance` resolves legacy rows | `database/archive_migrations/0006_fact_provenance.sql`, `database/financial_repo.py`, `tests/test_fact_provenance.py` | 
| Archive status vocabulary (migration 0007) | TESTED offline: the seven codes (reconciled, reconciled_with_rounding, unreconciled, insufficient_data, not_verifiable_from_disclosure, unmapped, requires_review) stored per statement and per fact; IAS 7 not-verifiable wired to the cash-equivalent fact; a failed identity is never hidden | `database/archive_migrations/0007_status_vocabulary.sql`, `engines/status_vocabulary.py`, `tests/test_status_vocabulary.py` | 
| Archive identity results (migration 0008) | TESTED offline: six identities stored with left, right, delta and status; a reconciled result must lie within tolerance; exceptions stored with their delta | `database/archive_migrations/0008_identity_checks.sql`, `tests/test_identity_checks.py` | 
| Extraction coverage matrix | GENERATED: company x period x statement from the fixture pipeline; company coverage 3 of 108 watchlist companies (2.8%) with all five statements reconciled for the current period; 30 of 30 extracted cells green; 105 watchlist companies not_started; drift-tested. Denominator is the defined watchlist (`config/coverage_watchlist.json`), not the seed | `docs/coverage/EXTRACTION_COVERAGE.md`, `scripts/build_coverage_matrix.py`, `tests/test_coverage_matrix.py` | 
| Turso database policy | DOCUMENTED: three roles, per-role URLs and tokens, separate ledgers, immutable and additive migrations, owner approval and disposable rehearsal before any live apply; this session is local SQLite only | `docs/TURSO_DATABASE_POLICY.md` | 
| 5 | Impact analysis and Python calculations | NOT STARTED | |
| 6 | Streamlit MVP | NOT STARTED | |
| 7 | Scheduling and operations | IN PROGRESS: market run orchestration (lease, abandoned-run recovery, backoff, bounded continuation, trigger tracking, 1-minute-first priority) TESTED offline; external dispatch (repository side), trading calendar, session completeness, gap detection and recovery, cheap coverage and the Collection operations view TESTED offline (PRs #27, #28, Stage 5) | `docs/COLLECTION_ORCHESTRATION.md`, `tests/test_market_orchestration.py` |
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
| X watchlist (33 owner-supplied + 2 pending) and YouTube (7) preserved | `database/seed/media_watchlist.json` | `test_all_33_supplied_accounts_present_exactly` | TESTED (no automated collection) |
| X manual post import, claim typing, predictions, copy detection, honest status (M1) | `engines/x_watchlist.py`, `docs/X_WATCHLIST.md` | `tests/test_m1_universe_and_x_watchlist.py` | TESTED offline; not run in production |
| Priority list and 20-session liquidity qualification (M1) | `engines/universe.py` | `tests/test_m1_universe_and_x_watchlist.py` | TESTED offline; owner priority list not yet supplied |
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

## Phase 4 checklist

Owner approved and merged on 2026-11-07 (PR #15, merge commit `0bdfb1a08de7dae9ea37899f4d93c10892b32e59`). Main CI on the merge commit
passed: test, secret-scan, and CodeQL for Python and Actions.

Open limitations:
- Turso compatibility is unverified on a real Turso server.
- Migration 0008 is not applied to production.
- No approved real company-evidence source exists, so real mappings remain unverified.
- Protection against relationship cycles deeper than A↔B is application-level only.
- Consumers must read `exposure_candidates_current`.

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| Entity resolution (ticker, alias, former name, ambiguity, delisted/historical, no creation) | `engines/entity_resolution.py` | `test_exact_*`, `test_lowercase_*`, `test_ambiguous_*`, `test_similar_*`, `test_unknown_company_*`, `test_delisted_*`, `test_former_name_*` | TESTED |
| Exposure taxonomy (6 categories, defined subtypes; UNCERTAIN → unknown) | `engines/exposure_taxonomy.py` | `test_direction_lookup_and_neutral_distinct_from_unknown` | TESTED |
| Versioned deterministic rules (oil, rates, PKR, gas, duties, relationships) | `engines/exposure_rules.py` (`exposure-rules/1.0.0`) | rule tests | TESTED |
| Evidence status and confidence with explanations; human-review flags | `engines/exposure_mapping.py` | evidence-status, rumour, contradiction, confidence tests | TESTED |
| LLM suggestions via the Phase 3 gateway, validated and audited | `engines/exposure_mapping.py::suggest_with_llm`, `prompts/exposure_candidate_v1.txt` | LLM tests (fixture provider) | TESTED; live LLM BLOCKED |
| Append-only candidates, revisions, reviews; relationships (migration 0008) | `0008_exposure_mapping.sql` | persistence, review and constraint tests | TESTED (local/CI only) |
| Real company exposures, segments and relationships | needs approved sources (`docs/SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`) | — | BLOCKED (awaiting sources) |

## Requirements traceability

The full matrix, covering every section of the specification, is in [`TRACEABILITY.md`](TRACEABILITY.md).

## Master programme modules (M2–M10), 2026-11-08
All rows below are **TESTED offline only**, using in-memory SQLite and synthetic hand-calculated fixtures. Nothing
has run in production, and no migration has been applied to Turso.

| Module | Code | Tests | Status |
|---|---|---|---|
| M2 financial reports: import, text parsing, mapping, reconciliation, promotion | `engines/financials.py`, migration 0011, `config/account_mappings.json` | `tests/test_m2_m3_financials.py` | TESTED offline. A present balance sheet must balance before promotion (`balance_sheet_required`) |
| M2 PDF intake and extraction: SHA-256 vault, pdfplumber + pdftotext -layout per-page cross-check, page-referenced statement lines, owner-confirmed statement pages and spread halves | `engines/document_intake.py`, `engines/pdf_extraction.py`, `engines/pdf_reader.py`, `engines/statement_pipeline.py` | `tests/test_document_intake.py`, `tests/test_pdf_extraction.py`, `tests/test_pdf_reader.py`, `tests/test_financial_pipeline.py`, `tests/test_layout_fallback_and_banking.py` | TESTED offline with SYNTHETIC PDFs. Real-report run on UBL Annual Report 2025 (unconsolidated pp. 41-45): statements RECONCILED, grid figures match to zero delta; OCI and total comprehensive income reconcile; KAM 1 (Expected credit loss against advances, Notes 9 and 9.4, p. 42) read by word coordinates with a letter-spacing flag. The auditor's report prints ONE KAM (pp. 42 and 98, verified); KAM 1 pinned. Owner page map: `--page-map` (JSON). Not validated on other reports: the owner must confirm statement pages for each filing (OWNER_ACTIONS 19) |
| Corporate (non-financial) cross-sector check: OGDC Annual Report 2026, standalone statements (part 2 of the upload, PDF pp. 5-10): balance sheet, P&L with OCI, cash flow reconcile with delta 0; 4 KAMs (verified, pages 5R, 6L, 6R) pinned as permanent regression. Trade-debts ageing and circular-debt exposures read manually from the notes (the engine does not parse Note 21 yet). Disposable Turso suite NOT run (no disposable target configured) | `engines/page_layout.py`, `config/account_mappings.json` (corporate), `scripts/financial_intake.py` | `tests/test_real_report_regression.py` (permanent, page-referenced), `tests/test_columns_oci_pagemap.py` | PINNED offline on real pages (text fixtures, PDFs not committed); not validated on other companies. Balance sheet: REQUIRES REVIEW (two-column layout, unlabelled totals) |
| OGDC note 21 (trade debts: gross, doubtful-debt provision kept separate from ECL, ageing to over 90 days, over-365 null when not disclosed, circular-debt overdue, counterparty table kept separate), note 41 (cash and cash equivalents explained by term deposits), OCI components with component-sum check, income-statement identity in the JSON diagnostic | `engines/trade_debts_note.py`, `engines/cash_equivalents.py`, `engines/financials.py` (wrapped labels), `scripts/financial_intake.py` | `tests/test_trade_debts_cash_note.py` | TESTED offline on synthetic fixtures; OGDC 2026 values read from the printed notes. IAS 7.7 maturity test NOT verifiable: note 26.1 prints maturities up to six months. Disposable Turso suite NOT RUN (no target configured) |
| LUCK (cement) standalone statements, Annual Report 2026 (upload part 9acdac22-3.pdf, PDF pp. 34-41, note pages 56, 74, 79): balance sheet, P&L, cash flow and comprehensive income (2026) reconcile; note 11 trade debts (gross, provision, net) reconcile; ageing NOT disclosed (all brackets null); cash equivalents (note 36.2) explained by short-term investments, IAS 7 maturity test not verifiable; 2 KAMs read by word coordinates (roman-numbered headings). 2025 OCI resolved from the page (PDF p. 40): (938,127) + 365,870 + 27,678 + (3,460) = (548,039); TCI 32,544,123 with zero delta. The earlier statement that the engine reports a conflict is NOT reproduced: the pipeline gives RECONCILED with no conflicts. Pinned in `tests/test_real_report_regression.py`. Disposable Turso suite NOT RUN | `engines/financials.py` (dotted note refs), `engines/statement_pipeline.py`, `engines/trade_debts_note.py`, `engines/cash_equivalents.py`, `engines/page_layout.py`, `config/account_mappings.json` | `tests/test_trade_debts_cash_note.py` | TESTED on one real corporate report; not validated on other companies |
| OCI parent binding (a tax effect binds to the component printed above it; both rows kept with their context), inferred OCI and current-subtotal totals, IAS 7 audit output (arithmetic separate from the maturity status: VERIFIED / NOT_VERIFIABLE_FROM_DISCLOSURE / DOES_NOT_MEET_DISCLOSED_MATURITY_CRITERION), core ratio layer partitioned by framework (null with a reason when an input is missing) | `engines/ratios.py`, `engines/cash_equivalents.py`, `engines/statement_pipeline.py`, `engines/financials.py`, `scripts/financial_intake.py` | `tests/test_ratios_and_oci_binding.py`, `tests/test_trade_debts_cash_note.py` | TESTED offline; regressions on UBL 2025, OGDC 2026, LUCK 2026 and LUCK 2025 listed in the commit. Disposable integration suite: DISPOSABLE_INTEGRATION_SUITE: NOT_RUN (No disposable credentials set) |
| Source retrieval (polite, permission-gated): registry with paused defaults, per-host interval (>= 3 s), one active connection per host, 429 with Retry-After / exponential backoff and jitter, conditional requests, PDF-only with content check, atomic SHA-256 vault storage with duplicate skip, diagnostic intake dispatch and ingestion log | `services/source_fetcher.py`, `config/sources_registry.json` | `tests/test_source_fetcher.py` | TESTED offline with mock HTTP only. NO source is permitted or fetched: all registry entries are paused with null endpoints (owner to supply and permit). The external scheduler (polling_schedule) is not built |
| PSX offline export parsers: listed-company directory (567 rows) and announcements feed (205,970 rows), read in memory from the supplied ZIP-named files, latin-1, frozen dataclasses (not Pydantic: the independence guard does not admit it), malformed rows logged and skipped; the supplied announcements carry NO document ID, so none is built | `engines/psx_exports.py`, `docs/PSX_EXPORT_FORMATS.md` | `tests/test_psx_exports.py` | TESTED offline; supplied files parsed completely. Pydantic is NOT a dependency: it is absent from requirements.txt and pyproject.toml and from the reviewed import list |
| M2 multi-period annual series from promoted metrics: gaps, unreconciled exclusions, restatement conflicts | `engines/financial_series.py` | `tests/test_financial_pipeline.py` | TESTED offline with synthetic data; not validated on real company data |
| Dual database: separate main and archive connection handlers, role checks, archive schema (`archive_migrations/`), archive repository (`database/financial_repo.py`) | `database/connection.py`, `database/financial_repo.py`, `database/archive_migrations/0001_financial_archive.sql` | `tests/test_dual_database.py` | TESTED offline on two SQLite files. Archive database NOT created: BLOCKED (owner to create it and set PSXNI_ARCHIVE_TURSO_URL / _AUTH_TOKEN). Staging line items still written to main: follow-up needs owner approval |
| Archive DDL gate (approval string `yes-execute-archive-migration-ddl`), preflight, read-only probe | `database/archive_migrations/archive_gate.py`, `scripts/archive_probe.py` | `tests/test_archive_turso_integration.py` (offline layer always runs) | TESTED offline. Real archive: read-only probe and dry run EXECUTED 2026-11-10, empty database, 2 migrations pending (`docs/ARCHIVE_PROBE_2026-11-10.md`). DDL NOT executed: awaiting owner approval |
| Archive schema v2: document registry, line items with page and note evidence, notes, reconciliation results, reviews, processing history | `database/archive_migrations/0003_document_registry.sql`, `0004_extraction_evidence.sql`, `database/financial_repo.py` | `tests/test_archive_records.py` | TESTED offline on SQLite. NOT applied to the real archive; NOT verified on Turso: BLOCKED (disposable archive-test DB) |
| Migration safety: derived schema fingerprint, name and gap checks, drift refusal, read-only dry run, approval gate | `database/archive_migrations/archive_gate.py`, `database/migrate.py`, `scripts/archive_migrate.py` | `tests/test_archive_safety.py` | TESTED offline with recorded-SQL dry-run proof. Production DDL NOT executed; awaiting owner approval (`docs/ARCHIVE_MIGRATION_APPROVAL_PACKAGE.md`) |
| Cash-flow reconciliation identity (opening + movement + FX effect on cash = closing) | `engines/statement_reconciliation.py` (`cash_flow`), `engines/financials.py` (`identity_checks`) | `tests/test_layout_fallback_and_banking.py`, `tests/test_archive_records.py` | TESTED with synthetic values |
| Archive Turso integration tests | `tests/test_archive_turso_integration.py` | same | Gated by PSXNI_ARCHIVE_TEST_TURSO_URL / _AUTH_TOKEN; refuses the real archive, operational and look-alike hosts. Not yet run: needs a disposable archive-test database |
| Announcement routing (metadata to main, parsed structure to archive, history attached): permitted routes only, fail closed | `engines/announcement_routing.py`, `database/financial_repo.py` (`archive_disclosure`, `disclosures`) | `tests/test_announcement_archive.py` | TESTED offline with synthetic records passed directly. NO live PSX collection: the announcements portal is RESTRICTED (`docs/SOURCE_ACCESS_REGISTER.md`); a live worker is NOT BUILT and needs written permission or an authorised feed |
| Historical non-PDF loader: JSON summaries to the archive, dry run by default, synthetic refused unless allowed | `scripts/load_historical_statements.py`, `database/financial_repo.py` (`validate_summary`, `archive_summary`) | `tests/test_announcement_archive.py` | TESTED offline. Owner-supplied data NOT loaded: BLOCKED on owner summaries and archive database creation |
| Unified history entry point: archive first, source labelled, main fallback labelled | `engines/history.py` | `tests/test_announcement_archive.py` | TESTED offline. NOT yet wired into `engines/fundamentals.py` or valuation: they still read the operational database directly |
| M3 fundamentals, dimensions A–C | `engines/fundamentals.py`, migration 0012 | `tests/test_m2_m3_financials.py` | TESTED offline; bands BLOCKED (U9) |
| M4 market intelligence, dimensions I–J | `engines/market_intel.py` | `tests/test_m4_m5_market_valuation.py` | TESTED offline; benchmark BLOCKED (U5) |
| M5 valuation, dimension D | `engines/valuation.py`, migration 0012 | `tests/test_m4_m5_market_valuation.py`, `tests/test_pr40_review_regressions.py` | TESTED offline; consensus BLOCKED (U6) |
| Dimensions E, F, G, H, K, L in `dimension_assessments` | not implemented (F, G and K exist only as Stage 2 impact assessments) | — | NOT STARTED |
| M6 macro series and vintages | `engines/macro.py`, migration 0013, `config/macro_series.json` | `tests/test_m6_m9_macro_validation_portfolio_reports.py` | TESTED offline; automation BLOCKED (U2) |
| M7 validation runs, walk-forward, event study | `engines/backtest.py`, migration 0014 | same | TESTED offline; no labels (U10) |
| M8 portfolio, theses, alerts (separate database) | `engines/portfolio.py`, `database/portfolio_migrations/` | same | TESTED offline; U8 open |
| M9 integrated reports and snapshots | `engines/reports.py`, migration 0014 | same | TESTED offline |
| M10 activation runbook and rehearsal evidence | `docs/OPERATIONS_RUNBOOK.md` | disposable Turso, 18/18 (2026-11-09) | IMPLEMENTED; nothing activated |
| M10 read-only integrity check | `engines/integrity.py` | `tests/test_integrity.py` | TESTED offline |
| M9 dashboard pages: financial statements, fundamentals, valuation, market behaviour, macro, integrated report | `engines/research_views.py`, `app.py` | `tests/test_research_views.py` | TESTED offline; pages show "awaiting migration" until 0011–0014 are approved for production |
| M3 efficiency and dividend sustainability (asset turnover, receivable / inventory days, payout, FCF dividend cover) | `engines/fundamentals.py` | `tests/test_pr40_review_regressions.py` | TESTED offline |

## Port of fundamental_engine (ADR-0001 scoped exception)
| Item | Code | Tests | Status |
|---|---|---|---|
| Relevance pre-filter, ported from the owner-approved scoped exception (ADR-0001, 2026-11-09) | `engines/relevance_prefilter.py`, `config/relevance_rules.json` (`relevance@v2`) | `tests/test_relevance_prefilter.py` (10 tests) | TESTED offline; not yet wired into extraction |

## Migration collision remediation (version 11), 2026-11-09
| Item | Code | Tests | Status |
|---|---|---|---|
| A2 remediation script (retire the foreign version 11) | `scripts/remediate_migration_collision_a2.py` | `tests/test_turso_disposable_a2_rehearsal.py` (SQLite leg) | TESTED offline (Option B guard); Turso rehearsal PASSED 2026-11-09 on a disposable database (26 passed; guard Option B proven on Turso); production EXECUTED 2026-11-09 and verified (`docs/MIGRATION_COLLISION_A2.md`) |

## Financial PDF reconciliation (2026-11-12, branch feature/financial-pdf-reconciliation)
Evidence: `docs/coverage/EXTRACTION_FINDINGS-2026-11-12.md`. Live fetch: no network fetch in this pass. No production or Turso write. No OCR.

| Item | Status | Evidence |
|---|---|---|
| De-shadow of copy-columns, distinct-column gate, glued-heading split | IMPLEMENTED and TESTED with synthetic fixtures | `engines/layout_words.py`, `tests/test_deshadow.py`, `tests/test_layout_words.py` |
| Interim income statement, four-column period roles from header groups | IMPLEMENTED and TESTED with synthetic fixture (a). Not yet wired into the batch gate; real-page header detection fails on most NRL pages | `engines/position_identities.py`, `tests/test_position_identities.py` |
| Independent total equity (SOCE closing balance, balance-sheet components, printed subtotal; never assets minus liabilities) | IMPLEMENTED and TESTED with synthetic fixtures (b), (c), (d). Component matching is unreliable on some NRL pages (surplus row dropped) | `engines/position_identities.py`, `tests/test_position_identities.py` |
| Deterministic extraction on the three pilots (UBL, OGDC, LUCK) | TESTED: 30 of 30 cells green from owner-supplied PDFs | `docs/coverage/EXTRACTION_COVERAGE.md`, `tests/test_real_report_regression.py` |
| HUBC annual 2026-06-30 | NOT PROVEN: identity checks requires_review | identity run (throwaway, not committed) |
| HUBC quarterly | needs_OCR (image-only) | `config/ir_registry.json` (`period_status`) |
| PSO | needs_OCR (vector-outline, no text layer) | `config/ir_registry.json` |
| NRL | needs_manual (shadow-corrupted text layer). Balance sheet 2026-09-30 reconciles on components (flagged); key totals keyed by hand; identities hand-verified | `config/ir_registry.json`, findings doc |
| LUCK live fetch | needs_manual (report host robots-disallowed). Pilot figures come from the owner's upload | `config/ir_registry.json` |

**Open owner decision (not acted on):** Acquisition strategy for scale: authorized data vendor (structured financials and announcements) vs free manual-import watchlist. Pending owner decision.

## Investify fundamentals, profile, competitors and industry (2026-11-12, first slice)
Consent: `docs/consent/investify-fundamentals-2026-11-12.md` (owner-reported expansion; the email is not in the repository). Code: `collectors/investify_fundamentals.py`, shared policy `collectors/investify_policy.py`, announcements job wiring `collectors/investify_job.py`. Seed source `investify_fundamentals` is DISABLED until the owner approves the gate.

| Item | Status | Evidence |
|---|---|---|
| Consent recorded (use, event-only refresh, 15-minute cap, ETag/If-Modified-Since, robots, backoff, attribution) | DOCUMENTED; owner-reported | `docs/consent/investify-fundamentals-2026-11-12.md` |
| Rule (a): fundamentals fetched only for a NEW financial-result announcement queued by the announcements job; none otherwise | IMPLEMENTED and TESTED offline | `tests/test_investify_fundamentals.py` |
| Rule (b): profile, competitors and industry backfilled once; manual refresh only; never polled | IMPLEMENTED and TESTED offline | same |
| One request per 15 minutes across all Investify endpoints (one state file) | IMPLEMENTED and TESTED offline | same |
| 304 is a recorded no-op (no write); 429/503 back off and keep the trigger pending; robots disallow and stale robots block | IMPLEMENTED and TESTED offline | same |
| Every stored record carries `source = investify.pk` and the attribution string | IMPLEMENTED and TESTED offline | same |
| Storage to the operational/news database only; no archive import | TESTED (AST check) on local SQLite with real migrations and seed | same |
| Endpoint paths for fundamentals, profile, competitors, industry | NOT CONFIRMED: `None` in code; requests refused until the owner confirms | consent record, open item 1 |
| Live proof on one watchlist company | BLOCKED: needs confirmed paths and owner confirmation that investify.com and investify.pk are one operator. No live request has been made | acceptance gate below |
| Production or Turso writes | NONE. The local SQLite used for the gate is in memory | — |

**Acceptance gate (for owner approval before scaling to the full watchlist):** the flow ran end to end on synthetic bodies (profile backfilled once; one financial-result trigger; one fundamentals fetch 16 minutes after the profile request; a later profile request skipped as already backfilled). The audit trail shows the two requests 16 minutes apart. Real Investify data has NOT been fetched. To proceed, the owner must (1) confirm the four endpoint paths, (2) confirm the investify.com / investify.pk entity, and (3) decide whether the raw page body (which may include Investify's summary text) is stored, and approve enabling the seed entry.

### Update 2026-11-12: source enabled; live HUBC proof IN PROGRESS
- `investify_fundamentals` is ENABLED in the seed (owner approval, 2026-11-12). Its consent record now carries the owner confirmations: operator investify.pk; fundamentals and competitors paths confirmed; profile path inferred and verified only by one conditional GET (unset on 404); no industry endpoint; STRUCTURED FIELDS ONLY.
- Storage now persists only metadata and the SHA-256 of each response body. The raw body and Investify's summary text are not persisted. Field extraction is NOT yet written: it waits for the page samples from the live proof.
- Live: robots.txt fetched once (HTTP 200, 2026-11-12T07:53:42Z); it allows all three company paths. The announcements page, the profile verification, the HUBC competitors and fundamentals requests are NOT yet made. Acceptance gate not yet reached.

### Update 2026-11-12 (08:33Z): profile extractor and profile backfill
- Profile path VERIFIED: one policy-compliant GET returned 200 (2026-11-12T08:32:17Z). Profile backfilled as structured fields only (sector from the page's embedded company index; leadership; market structure; share float split; registered address; website). The company description is deliberately NOT extracted, because it may be Investify-generated text; owner to confirm.
- Extractors: `engines/investify_extract.py` (profile written; competitors, fundamentals and the announcements parser pending the page mapping). Tests: `tests/test_investify_extract.py` on SYNTHETIC fixtures in `tests/fixtures/investify/` (invented values, not live data).
- Pending: announcements parser fix and trigger, fundamentals, competitors, acceptance gate.

### Update 2026-11-12 (10:05Z): Investify HUBC pilot, status
- Fundamentals: IMPLEMENTED and TESTED. First fill from the most recent financial result (2026-10-28), fetched 2026-11-12T09:09:24Z; 25 metric cards stored as structured fields.
- Announcements: IMPLEMENTED and TESTED. Structured parser; re-fetched 2026-11-12T09:27:13Z; no trigger queued (no HUBC result newer than the first fill).
- Competitors: IMPLEMENTED and TESTED (SECTOR-DERIVED peers). Stored 2026-11-12T10:05:30Z: 16 same-sector companies; Investify's displayed tab curates to 14, so the derived set is a superset by two.
- Profile: IMPLEMENTED and TESTED. Fields stored earlier (08:32Z) without the description; a re-fetch to add the description is pending at >= 10:20Z.
- Storage: structured fields only, in the metadata JSON; the raw body is never persisted. Every record is tagged source = investify.pk. The fundamentals trigger follows the first-fill and refresh rules, deduplicated by symbol, date and headline.
- Gate: pending owner approval. Archive, production and Turso: not touched. Scaling to the full watchlist is NOT started.
- 2026-11-12T10:24:38Z: profile refreshed as a MANUAL refresh (owner-authorized) to add the description; stored as structured fields. Earlier profile rows (08:32Z) and the earlier announcements (08:50Z) and the early fundamentals store belong to a pre-fix, hash-only throwaway database and are NOT part of the gate evidence.
- Storage fix: structured fields are kept in the metadata JSON. Refreshed snapshots use a timestamped identifier because the table is append-only.
- Audit note: the 09:47:26Z competitors request is logged manual=true by mistake; it was the first backfill. All other gaps are at least 16.9 minutes.

## Checkpoint 2026-11-12: branch `feature/financial-pdf-reconciliation` (NOT merged)
Handover: `docs/handover/PILOT-CHECKPOINT-2026-11-12.md`.

| Subsystem | State |
|---|---|
| Investify HUBC pilot (announcements, fundamentals first fill and refresh, profile with description, competitors sector-derived) | IMPLEMENTED and TESTED. Gate evidence in the operational SQLite, not in the throwaway pre-fix file |
| Investify first-fill and refresh rules; competitors as sector-derived (16 vs displayed 14) | Owner-confirmed; recorded in `docs/consent/investify-fundamentals-2026-11-12.md` |
| Investify private retention and analysis-output restriction (no verbatim public reproduction) | Owner-confirmed; recorded in the consent record |
| Investify audit label (09:47:26Z competitors) | Corrected: code records manual only for genuine manual refreshes; correction line in the audit log |
| IR fetcher (robots, interval, backoff, vault) | IMPLEMENTED and TESTED; live on four companies |
| PDF extraction and de-shadow engine | IMPLEMENTED and TESTED with synthetic fixtures; pilots reconcile (UBL, OGDC, LUCK) |
| Interim income-statement roles; independent equity | IMPLEMENTED and TESTED with synthetic fixtures; not yet wired into the batch gate |
| NRL, LUCK, HUBC quarterly, PSO | needs_manual / needs_OCR (see handover) |

**Deferred:** watchlist scale-up (needs owner approval); on-demand PDF-upload tab (separate phase); acquisition-strategy decision (owner); OCR (not approved); archive and production migrations (awaiting owner approval).
**Merge to main:** an owner decision. Not done.

## Company intelligence view (feature/company-intelligence-view), local and private
| Item | State |
|---|---|
| Read-only company data layer over stored Investify records (`engines/company_intelligence.py`) | IMPLEMENTED and TESTED (synthetic fixtures) |
| Descriptive screening signals with owner-visible thresholds (`config/screening_thresholds.json`): Low P/E, High net margin, Strong ROE, Positive earnings growth, Comfortable liquidity | IMPLEMENTED and TESTED; each shows the criterion and the observed value; no action language |
| Company intelligence page in the main app (`app.py`, "Company intelligence" page): profile, fundamentals grouped as on the source, peers, announcements, company picker; attribution on every view | IMPLEMENTED and TESTED (AppTest, navigation included); reads the configured operational database through SELECT-only queries; the standalone page was retired |
| Not-yet-collected handling (no number filled in for a missing dataset or metric) | IMPLEMENTED and TESTED |
| Dashboard sharing or publication | NOT IMPLEMENTED and NOT PERMITTED: private research use only |
| Live fetching | NONE. The page reads stored data only |
| SQLite handle across Streamlit reruns | FIXED: `check_same_thread=False` on the SQLite handle (the app caches it); existing pages rendered against a local file before this fix would fail on the second rerun |

## Investify Phase 1: finish ingestion (feature/investify-phase1-ingestion). GATE: owner review.
| Item | State |
|---|---|
| Announcement taxonomy: Financials, Material, Actions, Insiders, Meetings, Briefings, Other; total mapping; the group is stored per record (`engines/investify_taxonomy.py`) | IMPLEMENTED and TESTED (synthetic mix). HUBC stored data: Financials 8, Material 6, Actions 8, Insiders 1, Meetings 7, Briefings 9, Other 1 (sum 40) |
| Completeness against the page's filter counts | NOT YET VERIFIED: needs one announcements fetch inside the trading window; the stored counts are not compared with the page's own filter tabs |
| Insider transactions: record model, required fields, refusal of guesses, dedupe by (symbol, insider, date, action) (`engines/investify_insiders.py`) | Record model IMPLEMENTED and TESTED. Payload mapping NOT DONE: needs one fetched insider sample inside the trading window. HUBC's one Insiders item is a `dps:image` disclosure, so its text may not be readable; verify on the sample |
| Material, actions, meetings: stored categorized with structured fields | Stored with group and sub-type (existing announcements records). Routing to a notable-events layer NOT BUILT (no such layer exists yet) |
| News extractor behind a disabled flag (`config/investify_flags.json`, `news_enabled: false`) | Flag and refusal IMPLEMENTED and TESTED (refused before any request; also refused while the path is unconfirmed). Extractor body NOT BUILT: needs one News page sample, and owner confirmation that News is in scope of the consent |
| Nothing written to archive, production or Turso | Confirmed: Phase 1 modules import no archive or production connection (tested); the gate used the local operational SQLite, read-only |

**Gate evidence (HUBC, stored data):** 40 announcements; group counts above; 0 insider transaction records; News off.
**Blocked on the next trading window (Fri 13 Nov, 04:00 to 11:30 UTC):** the filter-count check, one insider sample, one News sample.

### Roadmap (approved-pending owner approval; NOT started)
- **Phase 2:** free macro-factor feed (Brent, SBP policy rate, SBP FX reserves, policy items; manual analyst intake).
- **Phase 3:** per-company dossier and analytical layer (baselines, narrative threads, driver model, context-aware ingestion, grounded research brief).
- **Phase 4:** scale across the validated watchlist (cap-gated), wire macro routing and manual intake into dossiers, surface only in the private local app.

## Phase 1 close (Part A): scheduled for the trading window, Fri 13 Nov 04:05Z. GATE: owner review.
| Item | State |
|---|---|
| Notable-events routing (`engines/notable_events.py`): categorized announcements and insider records routed as VERIFIED; commentary as UNVERIFIED; Other not routed; no generated text on any routed event | IMPLEMENTED and TESTED (synthetic) |
| Filter-count verification against the page's own tabs | SCHEDULED: one HUBC announcements fetch in the window; not yet run |
| Insider payload mapping; image disclosure | SCHEDULED with the same fetch. No OCR engine exists in the repository and OCR is not approved, so an unreadable insider disclosure is stored as `{type: image_disclosure, machine_readable: false}` |
| News | NOT FETCHED. Consent not confirmed by the owner; flag off; no request made |

## ROADMAP (approved-pending; NOT started; owner approval required for each phase)
- **Phase 2: Free macro-factor feed.** Brent, SBP policy rate, SBP FX reserves, IMF, budget and power-policy items from free primary sources. Each factor is linked to stocks through the driver model. Manual intake for pasted analyst takes (logged and classified). No paid API and no disallowed scraping.
- **Phase 3: Per-company dossier and analytical layer.** Static facts, financial time series, baselines and norms, narrative threads, expectations, driver model, descriptive screening signals, context-aware ingestion (beat or miss, thread update, routine or notable), and a grounded research-brief generator that narrates computed numbers with cited sources. HUBC is the reference.
- **Phase 4: Scale.** The dossier and signals across the validated watchlist, in the background and gated by the cap. Macro routing and manual intake wired into each dossier. Surfaced only in the private local app.
- **Phase 5: Event-impact and forecasting engine** (capstone, on the dossier, factors and a technicals feed).
  (a) Event-impact per material item: materiality against the earnings base; direction and rationale; certainty and timing (confirmed, probable or speculative; when it reaches earnings); priced-in check against consensus or recent action; dependencies; link to the driver model and threads. A structured verdict.
  (b) Technicals engine: OHLCV to accumulation and distribution (OBV, A/D line, volume trend), support and resistance; flags fundamental-versus-technical divergence.
  (c) Scenario synthesis: bull, base and bear, combining the driver-based earnings path, a valuation range, the catalyst calendar, technical positioning and macro state, each with named swing factors and rough probabilities.
  (d) Guardrails, non-negotiable: scenario-based only, never a point prediction or certainty; every estimate labelled with its assumptions; every fact traceable; observation separated from inference; confidence and "what would make this wrong" always stated; never buy or sell.

## Architecture blueprint
The full agreed system design (data layer, exposure map, dossier, macro and market-flow layers, event-transmission, composite and divergence, scenario and forecast engines, and the private dashboard), with the cross-cutting guardrails and the phase sequence, is recorded in `docs/architecture/INTELLIGENCE_BLUEPRINT.md`. The blueprint is a design record. It changes no runtime behavior. Phases 2 to 5 remain approved-pending.

**Blueprint status (2026-11-12):** `docs/architecture/INTELLIGENCE_BLUEPRINT.md` is complete as of the completeness pass. It now includes the tiered understanding model, the knowledge base ("the brain"), the technicals engine, the paste intake, the sources policy, and worked transmission examples. It is a design record and changes no runtime behavior. Phases 2 to 5 remain approved-pending.

## Investify good-citizen policy (feature/investify-good-citizen): IMPLEMENTED and TESTED against fixtures; GATE: owner review
Record: `docs/ops/INVESTIFY_GOOD_CITIZEN.md`. Policy: `config/investify_good_citizen.json`. Code: `collectors/investify_good_citizen.py`.

| Guarantee | State |
|---|---|
| One request in flight process-wide; 15-minute gap across all resources | IMPLEMENTED, TESTED |
| Fail-closed budgets (daily and weekly ceilings; halt; WARN at 60%) | IMPLEMENTED, TESTED |
| Event-driven only; no polling; workflow dispatch only | IMPLEMENTED, TESTED |
| Off-peak quiet window; jitter; trading hours | IMPLEMENTED, TESTED |
| Cache-first TTLs; ETag and If-Modified-Since; 304 no-op | IMPLEMENTED, TESTED |
| Multi-hour cooldown (floor 4 h) on 403, 429, 503; owner alert; breaker on the first signal | IMPLEMENTED, TESTED |
| Backfill yields, pausable, reserve, counts to budget | IMPLEMENTED, TESTED |
| Cache-only mode: zero Investify calls | IMPLEMENTED, TESTED |
| Kill switch, instant | IMPLEMENTED, TESTED |
| Footprint and weekly observability from the audit log | IMPLEMENTED, TESTED |
| Fail-safe defaults: cache-only, collectors off | IMPLEMENTED, TESTED |

**Changes to earlier behaviour (deliberate):** the announcements cron is removed (dispatch-only); backoff is a multi-hour cooldown rather than 60 minutes; a single block trips the breaker; the cadence test now asserts no schedule. **Caveats:** a state file without weekly counters refuses until reset; the validation driver on its own branch must treat "queued" and "cooldown" as waits when it merges.
