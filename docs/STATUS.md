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

## Backfill setup (feature/investify-good-citizen): GATE, owner approval before the live backfill
Plan and gate results: `docs/ops/INVESTIFY_BACKFILL_PLAN.md`.

| Item | State |
|---|---|
| Turso library link test | BLOCKED: the library secret is not set in this environment; the owner must set it through the secure secret flow. Live test also needs a non-append-only probe table (owner approval) |
| Library target guard (refuses prod and data-capture; names the library; never returns credentials) | IMPLEMENTED, TESTED |
| Synthetic end-to-end dry run (parse, distill, store, read back, verify) | PASSED on a disposable in-memory database; not written to Turso |
| EOD progress report (backfill coverage, breadth and depth, today's announcements grouped and highlighted, footprint, persisted per day) | IMPLEMENTED, TESTED on synthetic data |
| Live Investify requests tonight | NONE. Gated by the quiet window; tested |
| Live backfill | NOT STARTED. Requires owner approval of the plan |
| Global announcements page parser | OPEN: needs a structured parser and one sample in the trading window before the live start |

### Second gate pass (feature/investify-good-citizen): target psx-library
| Item | State |
|---|---|
| Target: psx-library-turso202601 (dedicated library DB; separate from data-capture and archival-test) | Owner-confirmed |
| Secrets `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `PSXNI_LIBRARY_TURSO_AUTH_TOKEN` | NOT SET. Owner to set through the secure secret flow |
| Target guard: accepts psx-library only; refuses data-capture, archival and production markers | IMPLEMENTED, TESTED |
| Link test on the approved probe table (write, read back, delete; under 1 KB; test-marked) | IMPLEMENTED; tested on an in-memory copy; live run BLOCKED on the secrets |
| Calendar: trading days, recorded hours, Friday break (pending owner confirmation), no fetch when uncertain | IMPLEMENTED, TESTED |
| Hours discrepancy (owner 09:15-16:30 versus calendar 15:50 and 16:50) | OPEN, owner to resolve |
| Jumma break window | PENDING owner confirmation (refused 12:00-15:00 Friday until confirmed) |
| Live backfill | NOT STARTED; requires owner approval of the plan |

### Definitive library integration (feature/investify-good-citizen): GATE, auth not yet proven
| Item | State |
|---|---|
| Single connection module `engines/library_db.py`: the only place a library client is built; reads both variables from the environment; fail-closed; target guard (psx-library only; refuses data-capture, archival and production markers); logs the host only | IMPLEMENTED, TESTED |
| Auth and placement check (`python -m engines.library_db`): SELECT 1, host print, probe round trip (insert, read back exactly one, delete in finally) | IMPLEMENTED; NOT RUN LIVE. In this session `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `PSXNI_LIBRARY_TURSO_AUTH_TOKEN` are not visible, so it refuses cleanly (exit 2) |
| Probe round trip on an in-memory copy | PASSED in tests |
| Single-path rule (no other module constructs a Turso client) | TESTED |
| Token scope (psx-library, write only, not account-wide) | To be confirmed by the owner in the Turso dashboard; not verifiable from here |
| Live backfill | NOT STARTED. Requires owner approval after the auth check passes |

**Next step (owner):** confirm both variables are visible in a new session of this environment (names only), then run `python -m engines.library_db`. Report the exact output. If auth fails, the verbatim error is printed.

### Autonomous fetcher (on main): IMPLEMENTED and TESTED; live by default (no mode toggle)

Verified on main (commit a8e544c):
- Self-test (`library-selftest.yml`, workflow_dispatch on main, run 43277037666): `library connection OK -> host=psx-library-turso202601.aws-us-east-1.turso.io`; probe `inserted/read_back_rows=1/exactly_one/matched/deleted` all true; `migration applied ...: 3 statement(s)`; `state tables present: ['fetch_control', 'fetch_progress', 'fetch_log']`.
- Dry run (`tests/test_tick_dry_run.py`, mocked Investify transport, network blocked): in-window = exactly one request (robots); outside window, unreachable library, or no contact address = zero requests; kill switch defaults off.
- Tick run on main (run 43277115897, 23:10 PKT, outside window): library and state tables confirmed, then `no-op: PSXNI_CONTACT_EMAIL is not set; no request is made without a contact address` (superseded: the contact now defaults to the repository URL). No Investify request.
- Contact: no setting is needed. The User-Agent contact defaults to the repository URL (`DEFAULT_CONTACT`). `PSXNI_CONTACT_EMAIL` is an optional override, validated (plausible email or https:// URL; anything else is a clean no-op). Dry run with the variable unset: User-Agent carries the repository URL, 0 requests, tick reaches the calendar stage (`tests/test_contact_default.py`, `tests/test_tick_dry_run.py`).
- Scheduler audit: `psx_fetch.yml` is the only scheduled workflow; `scheduled-jobs.yml` is dispatch-only.
Runbook: `docs/ops/AUTONOMOUS_FETCHER.md`.

| Item | State |
|---|---|
| Scheduled runner `.github/workflows/psx_fetch.yml` (every 30 min weekdays UTC; dispatch; library secrets only) | BUILT. Takes effect only after merge to the default branch |
| Single scheduler consolidation | Nothing removed. `scheduled-jobs.yml` (production collection, every 6 h) flagged for owner decision |
| State schema in psx-library `database/library/0001_fetch_state.sql` | PROPOSED; NOT applied (owner approval) |
| Tick logic: library-first, breaker cooldown, kill switch, official open-session calendar, throttle, day-1 ceiling, robots, one resource, throttle before request, breaker on 403/429/503/error | BUILT, TESTED (30 tests) |
| 304 no-op; 200 stores distilled fields only | TESTED |
| Clean no-op without library variables; contact required for any live request; no request when psx-library is unreachable | TESTED |
| End-of-day fetch log (renderer) | BUILT, TESTED; the scheduled write is not yet wired |
| Live fetching | Live by default. Gated only by structural guards; the state migration must be applied first (until then every tick no-ops). Manual pause: disable the workflow in the Actions UI |
| Library self-test (`library-selftest.yml`: `python -m engines.library_db`, then guarded migration) | PASSED pre-merge: connected to psx-library-turso202601, probe clean, 3 state tables present. Now workflow_dispatch on main |
| Trading hours | One source: `config/psx_calendar.json` `open_sessions` (Mon-Thu 09:32-15:30; Fri 09:17-12:00, 14:32-16:30; Jumma 12:00-14:32). Policy break agrees (tested). Grading `regular_hours` unchanged |

### HUBC research (pilot, one company)

| Item | State |
|---|---|
| Research folder `docs/research/hubc/` (five files, byte-identical to the uploads) with README and disclaimer | IMPLEMENTED, TESTED |
| `research_fact` table: `database/library/0002_research_fact.sql` | PROPOSED; NOT APPLIED. Waiting for the owner's approval |
| Row rules: every fact needs a source name and a source date; analyst views labelled `analyst_view`; 300-character limit | IMPLEMENTED, TESTED (`engines/research_facts.py`) |
| `research_fact` schema applied to psx-library (CREATE TABLE IF NOT EXISTS only, guarded connection) | DONE, run 43292869225 on main, host psx-library-turso202601.aws-us-east-1.turso.io |
| Distilled HUBC rows in psx-library | DONE: 23 rows inserted (sourced, dated; analyst views labelled `analyst_view`). Counts per topic: analyst_thesis 1, associate_cash 1, associate_share 1, balance_sheet 3, dividend 2, eps 2, ev_plan 1, ev_policy 1, ev_target 1, finance_costs 1, land_optionality 1, net_profit_owners 2, operating_cash 1, policy_rate 1, rating 1, receivables 1, revenue 2 |
| Per-company pattern (other companies) | CONFIRMED by the owner on HUBC: folder `docs/research/<ticker>/` plus `research_fact` rows keyed by ticker. No company gets a new table or structure. Other companies are NOT added yet |

### Phase 2 macro factors: PLAN ONLY (not built)
- Plan: `docs/plans/phase2_macro.md`. Status: awaiting owner approval; build not started.
- Investify is not a consented source for rates, commodities or sentiment. Phase 2 uses manual import of official releases.
- Blocked: SBP automated access (R3), EIA and World Bank (U2). Gaps: petrol, diesel, gold, silver and Fear & Greed have no named source.

### Investify consent scope (expanded approval)
- The consent record matches the owner's expanded-scope approval email: ten categories, exactly as the approval names them. Original four: Announcements, Fundamentals, Profile, Competitors. Expanded six: Market & Index, Sectors, Technicals, News, Sentiment, Rates & Commodities. Files: `config/investify_consent.json`, `docs/consent/investify-expanded-scope.md`.
- Approval date: 2026-11-12 (owner-reported, "12-11-26", day-month-year).
- Per-category enablement is still PENDING and stays OFF. Current flags: `collectors_enabled` all false; `news_enabled` false. The five categories with no collector have no fetch path. Enabling any category is a separate, approved step.
- Tests: `tests/test_investify_consent_scope.py`.

### Tick store fix (research_fact)
- Incident: manual run 43373355669 (13 Nov 2026, 10:38 PKT) made one live request, then failed storing it: `no such table: source_items` (the tick wrote to a table that is not in psx-library). The body was discarded, so no Investify data was saved. Requests today: robots.txt and that one resource (the daily ceiling of 2 is used).
- Fix: distilled fields are written as sourced, dated rows of `research_fact` (`engines/research_facts.py`, `rows_from_fields`, `insert_rows`). Metric label, value, unit and period are kept. Investify's description text is never stored.
- A failed store is logged (`store_failed`) and leaves the resource pending, so the next run retries it. A successful store marks it done.
- Tests: `tests/test_tick_store_research.py` (no network): rows are sourced and dated, no description text, rows land in research_fact only, success marks done, failure stays pending.
- Live fetching resumes in the next trading window (not before).
- Request limits (12 per day, 60 per week, 15-minute gap) are set by the OWNER. Investify's approval does not state a daily number.

### Live run and open items (13 Nov 2026)
- Live run 43377979015 (manual dispatch, 11:20 PKT, inside the Friday window): `tick: fetch: stored MEBL:fundamentals`. One request. Rows written to research_fact before the run was marked done. Not yet read back: a read-only check workflow (`library-readonly-check.yml`) is added for that.
- Requests today: robots.txt, the earlier failed fetch, and the MEBL fundamentals fetch (three of the owner's cap of 12; the one-day exception lifts today's first-day cap of 2).
- Open: (1) the scheduled tick has never fired since it reached main (zero scheduled runs; cron re-registered in PR #75). Needs a check of the Actions tab or an external dispatcher. (2) Monday 16 Nov: trading window 09:32-15:30 PKT, one session, no break. Trigger a run in the window if the scheduler is still silent. (3) Calendar: today is recorded as a trading day; a closure needs an official PSX notice before it is entered.
- Monday's window is continuous 09:32-15:30 PKT. The Jumma break (12:00-14:32) applies to Fridays only.

### Scheduler: CONFIRMED WORKING (13 Nov 2026)
- Root cause of the silent cron: both schedules fired at exactly :00/:30 UTC, GitHub's busiest minutes, where scheduled runs are dropped or delayed. Moved off-peak in PR #80 (tick 17,47; dispatcher 7,37; hours 1-11 UTC, weekdays).
- First scheduled runs, 13 Nov: Tick dispatcher 16:42 UTC (`PSXNI_DISPATCH_TOKEN is set`, tick dispatched, token works) and the tick's own cron 16:45 UTC (`noop: outside an official open session` — correct, 21:45 PKT is after close). Both success.
- The chain is proven end to end: GitHub cron -> tick directly, and GitHub cron -> dispatcher -> token -> tick. Guards behaved correctly.
- Weekends: no runs by design (crons are Mon-Fri). First in-window scheduled fetch: Monday 16 Nov, ~09:37 PKT onward (window 09:32-15:30 PKT).
- Token expiry reminder: PSXNI_DISPATCH_TOKEN expires 15 Dec 2026; regenerate before then.

### Pilot pages copied into psx-library (14 Nov 2026)
- The 12 Nov 2026 pilot pages had been saved only in a local SQLite file in the session scratchpad (never in Turso; see docs/handover/PILOT-CHECKPOINT-2026-11-12.md). Copied into psx-library with `scripts/import_pilot_pages.py`, without any Investify request: HUBC fundamentals (25 rows), announcements (40), competitors (18), profile (12); MEBL announcements (52). Each page is marked done, so the tick does not fetch it again. Source date kept as the original fetch date, 2026-11-12.
- psx-library now holds HUBC 118 rows (23 research + 95 Investify) and MEBL 68 rows (16 fundamentals + 52 announcements).
- Mapping fix: profile and competitors have dedicated mappings (leadership, market structure, float split, peers). The company description, which is Investify's own text, is never stored; neither is the extractor's own note.

### Annual-report facts in psx-library (14 Nov 2026)
- The owner's uploaded PDFs cover OGDC, UBL and Lucky Cement (no HUBC report was ever uploaded; HUBC's data is the research briefs plus the Investify pages). The extracted figures lived only as reconciliation fixtures in the repo, not in Turso.
- `scripts/import_report_facts.py` distils those fixtures into psx-library: LUCK 15 rows (13 figures, 2 KAMs), OGDC 12 (8, 4), UBL 8 (6, 2). Each row is one printed figure or key audit matter with its page cited, the statement date as source date, and the figure as a number in PKR thousands. Values printed but not cross-checked are flagged in the text.
- No PDF text and no page images are stored, per the owner's rule that documents must not fill the Turso account. psx-library holds 221 rows in about 50 KB.
- Totals: HUBC 118, MEBL 68, LUCK 15, OGDC 12, UBL 8.

### HUBC YouTube commentary in the brain (14 Nov 2026)
- 87 distilled rows loaded under `commentary.*` from owner-supplied YouTube transcripts: analyst SOTP (Abdul Rehman Najam), the CFO interview (Muhammad Saqib) and the CEO interview (Kamran Kamal), plus one unidentified compilation. Each row carries its video timestamp.
- All 87 are `analyst_view`, never `fact`: commentary and management guidance, not audited filings. HUBC now holds 205 rows, 114 fact and 91 analyst_view.
- Source dates are the date the material entered the system, because the video publication dates are unknown; `as_of` is left empty. The unidentified compilation is labelled as such and needs a link from the owner.
- Conflicts are recorded on both sides rather than resolved: SECMC stake (8% per CFO and brief vs 17.5% per analyst), CPHGC stake (47.5% / 46% / 50%), and whether the base plant is active in FY2027.
- `scripts/load_research_facts.py` gained `--scope`, so a company can gain a new body of knowledge without reloading what is already there.


## News collector (Mettis, Express Tribune, Dawn, Business Recorder, Profit): IMPLEMENTED and TESTED; live runs done; GATE: owner review

- `engines/news_collector.py`, migration `database/library/0008_news_item.sql` (`news_item`, `news_progress`), workflow
  `.github/workflows/news_collect.yml` (dispatch only; started by the external timer), runbook `docs/ops/NEWS_COLLECTOR.md`.
- Tests (`tests/test_news_collector.py`, offline fake network): parsing, robots.txt (wildcards, longest match, a named
  crawler beats `*`), a disallowed URL is never fetched, unreadable robots.txt fetches nothing, daily ceiling, idempotence,
  request spacing, new articles first.
- Live (16 Nov 2026, manual runs): 195 rows in `news_item` (Mettis 69, Business Recorder 44, Dawn business 30, Tribune
  business 27, Profit 25); every row has a title, a UTC publication date and a link; snippets are at most 300 characters.
- Limits found: Mettis's sitemap stopped listing articles after about 1 Dec 2025 and `/latest` has no pagination, so its history
  covers 16 Nov to 1 Dec 2025 plus everything from the first live run. Express Tribune, Dawn, Business Recorder and Profit
  are collected forward only: Dawn's archive paths are blocked by its robots.txt, Business Recorder's feeds hold hours,
  and Profit's history needs an owner decision (20 days of slow page fetches, or a URL-and-date index).
- Not built: fact extraction from these headlines into `research_fact` (next phase, needs owner approval); the second
  cron-job.org job that starts `news_collect.yml` every 30 minutes (owner step in the runbook).

### News headlines to facts: BUILT and TESTED; dry run only; GATE: owner approval to load and automate
- `engines/news_facts.py`, `scripts/build_news_capsule.py`, `tests/test_news_facts.py` (17 tests). Dry run on 344 stored
  headlines: 97 became rows (112: 42 company, 24 sector, 46 macro); the 42 company rows were checked by eye after tightening
  (headline-only matching, sponsor mentions ignored, one-word names only from confirmed aliases).
- Found and fixed on the way: the shared keyword matcher (`engines/freshness.py`) matched by prefix, so "ban" matched
  "bank" and tagged bank headlines as regulation. Words under five letters now match whole words only; this also affects
  the council's relevance ranking.
- Not done: loading the rows into `research_fact`; running the build after each collector run in Actions; sending material
  news to the council.

## News back-fill (Profit and Tribune, one month) - IMPLEMENTED, TESTED (offline), not yet run live
Sitemap-based 30-day back-fill added to `engines/news_collector.py` (owner-approved 16 Nov 2026); 2 new tests.
Mettis Dec 2025 to Nov 2026 remains a gap; no emails to outlets (owner, 16 Nov 2026).

## News rollup and signals - IMPLEMENTED, TESTED (offline); dry run only, load and Actions step await owner OK
`engines/news_rollup.py`, `scripts/build_news_rollup.py`, `database/library/0009_news_rollup.sql`, macro copy in
`engines/news_facts.py`. Not loaded into Turso; no workflow added yet.

## News facts, rollup and signals - LOADED and AUTOMATED (16 Nov 2026)
168 `research_fact` rows (company, sector, `MACRO:PAKISTAN`) and 41 `news_rollup` rows loaded with owner approval;
`news_collect.yml` repeats the steps after every collector run. Signals appear once there are 14+ days of history.

## research_fact company index - APPLIED to psx-library 16 Nov 2026 (PR #111)
`database/library/0010_research_fact_index.sql`, `scripts/apply_research_fact_index.py` (one allowed statement),
`research_facts.facts_for` / `sector_names`; the absorb loader and the council pack read only the entities they need.
Apply once, right after a collector run, after the PR merges; then measure rows read.
Measured on the live table (25,752 rows): a read of HUBC + MACRO:PAKISTAN + NBP went from 25,752 rows read to 8,752
(8,746 matching; HUBC is large); the SECTOR name list from 25,752 to 4,808. Building the index itself counted
about 52,000 rows read and 25,753 written, once.

## Entity folds from the owner's screenshot review - APPLIED (16 Nov 2026)
21 names folded onto PSX tickers (BAFL, PAEL, GWLC, SSOM, BNWM, POWER, CEPB, ATRL, AICL, ILP, HMB, SITC, ISIL, PKGP,
PGLC); rows unchanged (25,763), entities 610 -> 590. Held items are listed at the end of docs/research/entity_review.md.
Collector: the back-fill stops at the sitemap file where its window ends (no wasted 5 MB read per run).

## Investify export (owner's investify_psx.db, 17 Nov 2026) - LOADED (owner approved)
`scripts/build_investify_capsule.py`: 20,899 distilled rows for 566 companies (11,768 fundamentals metrics, 4,070 dated
announcements, 5,061 profile facts incl. sector for 562 companies). Loaded 17 Nov 2026: 20,613 new rows written, 329
near-duplicates skipped; research_fact is now 46,376 rows across 914 entities. News headlines (1,217) and the 60 symbols
not in the listing snapshot are not yet added. Full-table scans now cost about 46,000 of the 50,000-row read budget, so every
read must go through the company index (the news step's sector list was fixed to use an index range).

## Read/write economy pass (17 Nov 2026) - IMPLEMENTED, TESTED; index applied to psx-library
See `docs/ops/DB_BUDGET.md`. New index (company, source_date) replaces (company, topic); loaders read a date window;
sector list by loose scan; collector checks only candidate URLs; rollup writes only changes. An automatic news run
now reads about 6,100 rows (was about 25,000). The 60 Investify symbols are in `owner_confirmed`; the matcher now also
uses the company names inside `owner_confirmed` notes (they never matched before).

## PSX News Intelligence Council V1 - dry-run stage IMPLEMENTED, TESTED; production storage NOT activated
Seven importance rules, event de-duplication and versions, caps (6 a day, 2 an execution), queue, per-call ledger,
read-only connection, 10-headline review and a 7-day automatic dry-run workflow. See `docs/COUNCIL_NEWS_V1.md`.
Awaiting the owner's review of the 10-headline test and the seven-day results.

## PSX announcement feed (owner-supplied export, 17 Nov 2026) - converter IMPLEMENTED, TESTED; dry run only, NOT loaded
`engines/psx_announcements.py`, `scripts/build_psx_announcement_capsule.py`: 15,574 rows (results with figures, dividends,
bonus, rights, book closures, meetings) for 509 companies from 1 Jan 2023. No automated fetch from PSX (its Terms prohibit
it); refresh = the owner supplies a newer file. See `docs/ops/PSX_ANNOUNCEMENT_FEED.md`. Awaiting the owner's approval to load.

## Roadmap approved by the owner (2026-11-17): from collection to analysis
Order (one phase at a time, each stops at an owner gate):
1. Council V1 seven-day dry run and owner review. IN PROGRESS (first automatic run 2026-11-17). No production analytical writes until the owner approves.
2. Price facts through the owner-export route (a file the owner supplies; converter loads dated facts). NOT STARTED, BLOCKED on the owner's price file. No live link to the technical engine (ADR-0001 stands).
3. Materiality scoring (new figure vs the company's own history) and the company radar. NOT STARTED.
4. "Why did it move" explanations with sector and macro context; ranked hypotheses with evidence, "no identified cause" when nothing fits; no buy/sell. NOT STARTED.
5. One company page: news, results, price, technical signals. NOT STARTED (only built from implemented modules).

## Technical link (ADR-0008, signed 2026-11-17) and price/signal facts
- Read-only link to the technical engine's database: IMPLEMENTED and TESTED (PRs #116 to #119). Schema discovery done (27 tables). Schedule A approved (9 tables); predictions, runs, dss_history, its own news, intraday/candle tables are excluded.
- `price_daily` (migration 0012, last 120 sessions) and technical facts (`price.move` as fact; `technical.wyckoff` and `technical.pattern` as analyst_view with the engine's scan date): IN PROGRESS. First applied load of 5 symbols (HBL, NBP, OGDC, PSO, TRSM): 600 bars, 87 facts, 0 duplicates. Full load (148 symbols) and the daily refresh await the owner's go-ahead.
- Not read: FIRE (last scan 2026-11-03, stale), `snapshots` (empty), backtest reliability (per pattern, not per company; not loaded yet), volatility engine (no table found).

## Materiality scoring and company radar (owner approved 2026-11-17)
- `engines/materiality.py` + `scripts/build_radar.py` + dispatch-only `company_radar.yml`: IMPLEMENTED and TESTED. Read only (no database writes); report in the run summary and an artifact. No dashboard page yet (needs the owner's gate).
- Drivers: results (+ like-for-like EPS change when a same-period prior-year pair exists, else "size unknown"), corporate actions, price move with volume, news volume vs the company's own baseline, technical heuristics (labelled). Scores order attention only; not forecasts or recommendations.
- Limits: the results size is mostly unknown until the PSX announcement feed (15,574 facts, awaiting the owner's yes) is loaded; Investify announcement facts are dated by their announcement date (period), not the load date; companies the technical engine does not cover have no price driver.
- Verified live 2026-11-17 09:01 UTC: the first automatic runs of `tech_link_daily.yml` (idle check found nothing new: no capsule, no writes) and of the council dry run (second execution of day one: 137 headlines, 23 flagged, 40 queued, 0 rows written).

## PSX announcement feed loaded; "why did it move" (owner approved 2026-11-17)
- PSX announcement feed: LOADED. 15,510 facts for 509 companies since 2023-01-02 (results.annual 2,345; half_year 2,310; quarterly 2,303; nine_months 2,260; corporate_action book_closure 2,787, meeting 2,091, dividend 1,300, bonus 67, rights 47). 64 duplicates skipped. Source: owner-supplied export of announceWithSymbol.lis. The radar's EPS comparison now reads these periods ("nine months ended 2026-09-30") on the same basis only (consolidated vs unconsolidated, never mixed).
- `engines/move_explainer.py` + `scripts/explain_moves.py` + dispatch-only `why_did_it_move.yml`: IMPLEMENTED and TESTED. Read only. For each notable move: results/corporate events up to 2 days before, company news, sector and market moves, labelled macro and technical context; says "no identified cause in the evidence on file" when nothing fits. Not proof of cause, no recommendations.
- Finding: over 15 days, 56 of 60 notable moves had no cause on file and 4 were sector moves. Small caps get little news coverage, so most unexplained moves are a data-coverage limit, not a model failure.

## Company brief page (owner approved 2026-11-17)
- `engines/company_brief.py` + a "Company brief" page in `app.py`: IMPLEMENTED and TESTED (3 new tests plus the existing app tests). One company: price series and 1/5/20-day change, notable moves with the explainer's evidence, results and like-for-like EPS change, corporate actions, news, technical heuristics, fundamentals snapshot, and "what we do not know". Read only; cached 30 minutes; needs `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `_AUTH_TOKEN` in the Streamlit deployment (owner action). No buy or sell view.
- `docs/ops/SMALL_CAP_COVERAGE_PLAN.md`: proposal only; awaiting the owner's decisions.

## Investify announcements into the library (owner approved 2026-11-17)
- `collectors/investify_library_job.py` + dispatch-only `investify_library.yml`: IMPLEMENTED and TESTED offline (7 tests). Same consent-bound client and good-citizen gate as `collectors/investify_job.py`, but the result goes to psx-library as dated facts (`announcements.<Investify label>`, '<date>: <title>', source "Investify (investify.pk), announcements listing"), never to the older news database (whose `PSXNI_TURSO_*` secrets were never set up; the 13 November runs failed on that). Metadata only; no Investify summary text, no PDFs. At most one request per run.
- NOT LIVE: the shipped policy keeps `announcements` OFF (two tests pin it). A first live request needs the owner to enable it in `config/investify_good_citizen.json`, inside the trading window and outside the 10:00-15:30 PKT quiet window (so 09:00-10:00 or 15:30-16:30 PKT). Not yet requested: no request to Investify has been made by this code.

## Explainer evidence widened; explanation scoring (owner approved 2026-11-17; FIRE dropped by the owner)
- Explainer: material Investify announcements (management change, material disclosure, financing, M&A, legal, capacity, operations, unusual-movement reply, buyback, split, rating, scheme, rights/bonus) count as company evidence; routine scheduled notices (board meeting, AGM, book closure, dividend) count only as "scheduled notice" and never as a cause; report transmission, briefings, auditor certificates, insider lines and "Other" are ignored. The report lists the unexplained moves. IMPLEMENTED and TESTED.
- `engines/explanation_scoring.py`, `scripts/score_explanations.py`, dispatch-only `score_explanations.yml`: IMPLEMENTED and TESTED. Read only. First run (local, real data): 2,055 notable moves, 2026-05-21 to 2026-11-16: 62% had no cause on file, 22% were shared with the sector or market, 9.5% had a result on file, 3% other company evidence, 3.6% only scheduled notices. Next-day carry-on: results 57% (n=195), company evidence 61% (n=59), shared 39%, scheduled only 30%, no cause 50%, all 48%. Five-day figures show no clear pattern. Descriptive only; small buckets and overlapping windows; not a rule or a forecast.

## Daily digest (owner approved 2026-11-17)
- `engines/daily_digest.py`, `scripts/build_digest.py`, dispatch-only `daily_digest.yml`: IMPLEMENTED and TESTED (3 tests; local run on real data: about 91,000 reads, 0 writes). Sections: data freshness, market breadth for the latest trading day, radar top 10, notable moves with the evidence on file, the unexplained list. Read only; report goes to the run summary and an artifact; it is not sent to anyone (no email). Automatic once per trading day (owner approved 2026-11-17): it starts after `Technical link daily`, asks for the newest stored price day (a one-row read), and stops at once if a digest for that day already exists (Actions cache key `digest-<day>`); otherwise it builds and keeps the report as an artifact. Weekends and idle runs cost a few reads. Nothing is emailed or sent.

## EPS basis matcher (owner approved 2026-11-17)
- `materiality.eps_pair` (used by the radar, the explainer and the company brief): pairs Investify's newest EPS (latest quarter, year-to-date, annual) with last year's PSX figure ONLY when like-for-like can be shown: the PSX prior-year figure exists on exactly one basis (an unlabelled PSX result counts as its own basis), and Investify's own figures agree with PSX on that basis wherever they overlap (at least once, never a disagreement, within 2%). Investify mixes bases within one company (HBL: annual matches PSX unconsolidated, year-to-date matches PSX consolidated), so a company with two bases is never paired. A jump above 4x last year's figure is not used (NRL 12.82 -> 144.68 looked like a source slip). Fiscal years other than December are mapped from the PSX year-end (a June-year company's "2027 1Q" is the quarter ending 30 Sep 2026). IMPLEMENTED and TESTED (12 new tests).
- Measured on the library: of 414 companies with Investify EPS, 343 already had a like-for-like result and still do; the matcher replaces an older comparison with the newest one for 6 of them (EFUL, GHNI, PICT, SINDM, STJT, UPFL) and unlocks no new company. Honest reading: the PSX file already covers most; the gain is recency for a few names, not coverage. Refreshing the PSX file remains the real fix.
- Incident 2026-11-17, found on the first live data day: `Technical link daily` failed three times (11:31, 12:02, 12:31 UTC) and then on a manual run. Two causes, both fixed: (1) an informational `SELECT DISTINCT company FROM research_fact` scanned the whole fact table (over 160,000 rows); removed. (2) The technical `daily_ohlc` is keyed by symbol first, so the date filter reads the whole table (about 166,000 rows) once per new data day and hit the daily workflow's 120,000-read cap; the cap is now 400,000 (about 0.03% of the technical account's monthly reads per new-data day; idle runs read two rows). No bad data was written; prices for 17 November were not yet loaded until the fix.

## Announcements surfaced in the radar and the company brief (owner report 2026-11-17: HUBC)
- Gap found: HUBC's 16 Nov "Operations Update" announcement (smelter feasibility study) WAS in the brain (Investify snapshot) but neither the company brief nor the radar score showed it (only results, dividends/corporate actions, news and price counted). Fixed: `materiality.MATERIAL_LABELS` / `SCHEDULED_LABELS` are now shared; the radar gets an `announcement` driver (15 points for a material announcement in the window, 5 for routine scheduled notices only; report transmissions, briefings, certificates and insider lines never score); the company brief and page list "Announcements (last month)" (material first, then scheduled; routine ones counted, not listed). IMPLEMENTED and TESTED. HUBC 14-day radar score 75.7 -> 90.7 (rank 12 -> 11 of 163).
- Still a limit: the Investify snapshot ends 16 Nov 23:55 UTC and the PSX file ends 10 Nov, so anything announced on 17 Nov or later is not yet in the brain until the live Investify collector runs (first dry run tomorrow, 09:34 PKT).

## Rename gap: Mari Energies (owner report 2026-11-17)
- The news collector captured four stories on MARI's 13 Nov copper-gold discovery (Profit, Dawn, Tribune) and an Ivanhoe Mines exploration agreement, but none reached MARI's file: the news vocabulary only knew "Mari Petroleum" (the old name). Added aliases "Mari Energies" and "Mari Minerals" (its wholly owned subsidiary) to `docs/research/arn/entity_aliases.json`, with a test. Revert the subsidiary alias if a separate entity is wanted.
- Wider finding: of 566 current company names in the Investify snapshot, 93 do not resolve to their own symbol in the news vocabulary (some are preference or right shares, many are small caps such as Agha Steel, Ansari Sugar, Colgate-Palmolive, Chenab, First Capital Securities). This is one reason many small-cap moves show "no cause on file". A safe derivation of aliases from the current names is proposed, not applied.

## Announcement substance for every stock (owner direction 2026-11-17: "not just MARI, all the stocks")
- `engines/announcement_substance.py` (+ `engines/company_names.py`): reads the quantities stated in each announcement's text (a stake percentage, a rupee amount), sets them against the company's own size (market cap on file) and reports a size band (major / significant / moderate / minor) WITH the numbers behind it; no quantity stated means "unquantified" (8 points), never an invented size. Deal roles are respected: a stake is graded only for the company shown to be the target (acquirer: "X intends to acquire up to 60% of Y" grades Y; seller side: "Y's shareholders agree to sell 51% stake to X" grades Y). Replaces the flat 15 points in the radar (announcement driver cap now 25) and adds the size band and basis to the company brief and page. Bands are plain ratios in one place, not calibrated to outcomes. IMPLEMENTED and TESTED (8 new tests).
- Measured on the library (announcements dated since 27 Oct): 1,805 announcements, 184 material across 128 companies; only 19 of the 184 state a quantity in the title (13 major, 1 significant, 4 moderate, 1 minor); 165 are unquantified. Headlines cannot carry substance for about 90% of material announcements; the original document or its summary is needed. The consent keeps documents browser-only, so owner-supplied documents are the route (proposed: a document intake with grounded quotes).
- Radar limit: its candidate list is priced symbols plus companies named in the last days of news; an announcement-only company with no price and no recent news is not scored yet.

## Investify addendum (17 Nov 2026): Highlights stored; documents stay manual
- Consent: `docs/consent/investify-2026-11-17-highlights.md` (owner-supplied written addendum): the card's Highlights text may be stored for private, non-commercial research with attribution and the unchanged one-request-per-15-minutes limit; the "Original PDF" links are PSX-hosted, Investify hosts no copies and offers no API or bulk feed; opening PDFs manually in a browser is acceptable. The collector therefore still never downloads PDFs.
- Built: the card parser reads the key-facts line and summary paragraph (`highlights`, `summary`, not in the dedup hash); the library job stores them only when `highlights_allowed(now)` (record exists and on or after 2026-11-17) as private `announcement_highlights` facts, source "Investify (investify.pk), announcement highlights", in up to two 285-character chunks linked to the announcement by a hash of its title (no characters spent repeating the title). IMPLEMENTED and TESTED.
- Loaded: the owner's 16 Nov snapshot, 5,659 Highlights facts for 515 companies (the snapshot was extracted before the addendum and stored after it; the topic can be removed in one statement if that is not wanted).
- Substance engine now reads the Highlights text and the STAGE the company itself states (preliminary: evaluate, due diligence, in-principle, feasibility, proposes, intends to, seeks approval; definitive: agreed, signed, completed, approved), counting a preliminary item at 0.6 of its size points and quoting the phrase behind it. Quantified material announcements rose from 19 to 33 of 184 once the Highlights were read. NRSL (60% stake, in-principle approval to evaluate and conduct due diligence): major, preliminary, 15 points. MARI (discovery; the filing says further drilling and resource estimation are needed to determine scale and economic potential): unquantified, preliminary, 4.8 points. Bugs found by running on real data and fixed: a stray "Rs," produced an empty number; "subject to" wrongly marked a signed sale as preliminary.
- Reports quote numbers, size bands and the stage phrase, not Investify's text (private use only).
- Capture window (owner rule, 2026-11-17: "only the previous three months and the latest, not history, so we cannot overload their servers"): `investify_policy.CAPTURE_WINDOW_DAYS = 92` and `capture_cutoff(now)`; the library job and the snapshot builder drop any announcement older than the cutoff (live: 2026-08-17 on 17 Nov); the live job fetches one page (the latest) per run and never pages back. Trimmed: 390 Highlights facts dated before 2026-08-17 were deleted (5,269 remain, 2026-08-17 to 2026-11-16). The Investify announcement TITLE facts loaded earlier from the owner's snapshot (395 older than the cutoff, back to Nov 2025) were left in place pending the owner's decision. IMPLEMENTED and TESTED.

## Focused council dry run (owner request 2026-11-17: assess the MARI discovery with the company's full data)
- `council_news_dryrun.py --mode ten --focus MARI[,SYM]` and the workflow input `focus`: assesses the real events that name the chosen companies (`council_news.pick_focus`: best-corroborated and newest first, up to `--count`), instead of the usual ten. Read only; no production writes. In focus mode the pack uses `build_pack(mapped_first=True)`: facts with no lens (price moves, technical rows) are dropped BEFORE the per-company cut, so a busy company's pack is not filled with rows no lens can read (the running dry run keeps the old order). IMPLEMENTED and TESTED.
- Highlights to the council: ALLOWED by the owner on 2026-11-17 (private use; recorded in `docs/consent/investify-2026-11-17-highlights.md`, with the caveat that free-tier provider terms differ and were not verified). `announcement_highlights` now maps to the announcement lens, in every council pack, including the running seven-day dry run from this point on. (Superseded line: Highlights had been withheld: `announcement_highlights` had no lens.) The addendum permits private research use; whether sending that text to third-party free-tier providers is within it is the owner's call. Other Investify-sourced structured facts (announcement titles, fundamentals, profile) are already part of every council pack; the owner has been asked to confirm that too.
- Highlights reach the pack (fix after the first rerun): the pack takes each company's 40 newest rows, and MARI's newest rows (a fundamentals load, news, commentary) filled all 40, so the 13 Nov Highlights were cut and the council's second answer was still headline-only. `build_pack` now reserves up to 6 extra slots per company for its newest Highlights (`RESERVED_HIGHLIGHTS`), in every council pack. Test added.

## Announcement gate into the council (rule 8) - IMPLEMENTED, dry run only
- `engines/announcement_events.py` turns recent material announcements into council events when the numbers
  engine grades them major/significant or the stock reacted (volume >=5x 20-session average or move >=4%).
  Owner-directed addition to the seven rules (rule 8). Same queue, same caps (6/day, 2/execution), scanned at
  most every 6 hours, failures isolated and recorded in the execution summary. No production writes.
- `contradiction()` flags council-vs-numbers disagreement (function and tests; not yet shown in the digest).
- NOT DONE: digest "Council (dry run)" section (needs the ledger cache in the digest workflow).

## Investify old title facts trimmed (owner decision 2026-11-17) - IMPLEMENTED
- 395 announcement title facts dated before 2026-08-17 deleted from psx-library via `scripts/trim_investify_titles.py` (dry run counted 395, apply deleted 395, 0 remain older than the cutoff). Only research_fact rows from the Investify sources, topic announcements.*, announcement date before the capture cutoff.

## Entity aliases derived from current Investify names (owner, 2026-11-17) - IMPLEMENTED
- Owner: "Ltd" and "Limited" are the same (the matcher already drops legal suffixes); keep ETFs and REITs; leave preference/right shares out. 109 aliases (name without "Ltd" -> symbol) added to `docs/research/arn/entity_aliases.json` for multi-word names that did not resolve to their symbol. Left out: 15 preference/right/class shares, 23 one-word names (Systems, Packages, Thal, Loads... the matcher refuses bare one-word names by design), 3 collisions with another symbol (AHL/AHCL, PIAHCLB/PIAHCLA, WAVESAPP/WHALE). 46 of the names are not in the KSE listing at all; about 50 differ from it only by typos in that listing.
- No database rows were deleted. The alias fold into stored research_fact rows (`scripts/apply_entity_aliases.py`) is a separate, still-unrun step.

## Owner-confirmed one-word names (2026-11-17) - IMPLEMENTED
- Owner confirmed Systems Limited = SYS, Packages Limited = PKGS, Loads Limited = LOADS, Treet Corporation = TREET. A confirmed one-word alias written with its legal suffix now matches only WITH the suffix ("Systems Limited"/"Systems Ltd"), so "Payment Systems" is never a company. Test added. The other 19 one-word names await the owner.

## One-word names, second confirmation (owner, 2026-11-17) - IMPLEMENTED
- Owner accepted all remaining one-word names: AGP, AMTEX, BLUEX, BNL, CHBL, HAFL, TELE, TOWL, ZAL, PREMA, ASC, SPEL, TPL, THALL, TCORP, WAVES, IML, GOC, ZIL (each matched only with its legal suffix). WAVESAPP is not aliased: its Investify name "Waves Home Appliances" is identical to the KSE listing name of WHALE, so the name cannot point to two symbols; owner to say which symbol the name belongs to.

## Waves / Tariq Glass corrections and Market dashboard (owner, 2026-11-17) - IMPLEMENTED
- WAVESAPP = Waves Home Appliances; WHALE excluded (not a company; added to the ticker stoplist and its alias removed); TGL = Tariq Glass Limited. Waves Corporation = WAVES, Thal Limited = THALL, Tariq Corporation = TCORP were already in.
- New Streamlit page "Market dashboard" (`app.py` `_market_dashboard`, `engines/market_dashboard.py`): latest price/news day, breadth, radar table, notable moves with a cause on file, unexplained moves. Read only, cached 30 minutes, same engines as the daily digest. Needs the library secrets in the Streamlit deployment (`PSXNI_LIBRARY_TURSO_DATABASE_URL`, `PSXNI_LIBRARY_TURSO_AUTH_TOKEN`), as the Company brief does. Tests render it against a seeded library.

## Dashboard works with a read-only token (2026-11-17) - IMPLEMENTED
- First live run of the Market dashboard on Streamlit failed with "SQL write operations are forbidden": the shared Turso client sends `PRAGMA foreign_keys = ON` with every request, which a read-only token refuses. Added `database.connection.TursoReadOnlyDatabase` (SELECT/WITH only, no PRAGMA) and `library_db.get_library_readonly_connection()`; the app's library handle uses it. Tests added.

## Dashboard made phone-friendly (owner screen recording, 2026-11-17) - IMPLEMENTED
- Found from the recording: a one-line conditional expression made Streamlit print its own documentation under the radar table (a bug); wide tables were cut off on a phone; the sidebar opened on pages that only said "no database configured".
- Fixed: Market dashboard is the first page and the older Overview / Company intelligence pages appear only when the news database is configured; the radar and moves are tap-to-open cards (every driver with date and source) instead of wide tables; unexplained moves are a short list; the three header numbers are one line.

## Dashboard redesigned, phone-first (owner, 2026-11-17: "see how beautiful Investify is built") - IMPLEMENTED
- Own design (no Investify branding or code): status bar, market breadth bar (advanced/unchanged/declined), top-movers rows (symbol, company name, close, coloured move, volume against usual) with Most active / Gainers / Losers, and tabs Market / Watch list / Why it moved. Radar and move entries are tap-to-open cards with every driver, its date and source. `engines/dashboard_html.py` (HTML, all dynamic text escaped), `engines/market_dashboard.py` (movers). Checked in a phone-width browser render of sample data; not yet seen on the live Streamlit app.
- Limits of Streamlit: no fixed bottom navigation bar, no live intraday chart, no company logos; the index chart and Fear & Greed gauge in Investify are not built (no index data or gauge methodology in the brain).

## Setups tabs: Technical / Fundamental / Fund + Tech, top 10 each (owner, 2026-11-17) - IMPLEMENTED
- `engines/setups.py` (deterministic, no model, tested): technical pillar = 20-session price change, position in the recent range, volume against usual, plus the technical engine's own Wyckoff / pattern scores when on file; fundamental pillar = return on equity, P/E, P/B, dividend yield, debt/equity and the like-for-like EPS change; combined = average of both pillars and a stock needs both. Each pillar is 0-100 over the items that are MEASURED (an item not on file is left out and listed as "not on file", never zero). Floors: at least Rs 25m traded a day, price at least Rs 10, 25 sessions; values that are artefacts (negative equity or earnings, ROE over 60%, P/B over 8) make the fundamental side not usable. Scores are equal-weight and uncalibrated, not forecasts, not advice.
- The dashboard's first three tabs show them as tap-to-open cards with the evidence and the unknowns. Not yet seen on the live app; the dashboard read budget was raised to 400k rows for it.
- Known limit: a stock with no engine scan is scored on price items only, which can rank it above one whose engine scores are moderate. A weighting that corrects this needs the owner's decision and the backtest data.

## Setups now use announcements and news; "Check a stock" (owner, 2026-11-17) - IMPLEMENTED
- Owner asked whether the Fundamental setups take company news and today's announcements into account and why HUBC/MARI were not in the top picks. Answer: the first version did not. The fundamental pillar now adds three event items from the company radar's own graded drivers: a recent material announcement (size, stage and recency already in its points; up to 10), unusual news flow (5), a recent corporate action (5). No event on file = item unknown, not zero.
- "Check a stock" box (Fund + Tech tab) shows one symbol's technical, fundamental and combined scores with ranks and evidence, or why it is not scored (no price series, thin, low price, fewer than 25 sessions).
- Known gaps: news and announcements after 16 Nov are not in the brain until the live Investify collector runs (dry run scheduled 2026-11-18); the PSX feed ends 10 Nov; the technical engine has no signal for MARI; weights are uncalibrated.

## Setups fixes after the MARI/HUBC trace (owner, 2026-11-17) - IMPLEMENTED
- Trace on live data (Actions "Setups check"): no symbol is named in the scoring code; MARI ranked on real price/volume numbers, HUBC's announcement was counted. Two weaknesses fixed: (1) events window widened from 3 to 7 calendar days (`market_dashboard.EVENT_DAYS`), so MARI's 13 Nov discovery counts; (2) an item not on file now counts at the midpoint of its range (not zero, not a bonus) instead of being left out, so a stock with no technical-engine scan is not ranked above one with moderate scans; a bad scan lowers a score, a good one lifts it. Tests added. The Watch list tab now shows the last week.
- Also fixed a latent test that failed after 19:00 UTC (the council record day follows the real clock).

## Investify dry run, first attempt skipped (2026-11-18) - NOTE
- The scheduled dry run at 04:34 UTC (09:34 PKT) made 0 requests: the good-citizen gate allows requests only INSIDE 10:00-15:30 PKT (the "quiet mid-session window", away from the open and close bursts) and only in an open session (Mon-Thu 09:32-15:30). My earlier statement that the usable window was 09:32-10:00 was wrong. The audit trail records the skip; nothing was fetched or stored. Retry scheduled for 05:06 UTC (10:06 PKT), apply=false.

## Investify: robots refresh and page fetch in one run (owner, 2026-11-18) - IMPLEMENTED
- A run that finds the 24-hour robots.txt copy stale now refreshes it, waits 15 min 30 s, then fetches the page, instead of ending after robots and needing a second dispatch. The one-request-per-15-minutes limit and every other gate are unchanged (the second request re-runs the gate). `collectors/investify_library_job.py` (`AFTER_ROBOTS_WAIT_S`), workflow timeout 10 -> 45 min, test added. Consent record updated with the owner's operating decision.
- 2026-11-18 dry run: attempt 1 skipped (my window error, 0 requests); attempt 2 refreshed robots.txt (HTTP 200, 1 request); page fetch scheduled for 05:27 UTC.

## Investify dry run 2 (2026-11-18 05:29 UTC): page returned, 0 announcements parsed - BLOCKED (diagnosis)
- Audit: robots.txt (05:09:58) and the announcements page (05:29:46, HTTP 200, 495,814 bytes): two requests in total, 20 minutes apart. The parser found 0 watchlist announcements in it. Cause unknown until the page text is seen (the page changed since the 11 Nov fixture, or is built differently).
- Fixes: a dry run now keeps the page (investify_page.html, 3-day private artifact) when nothing parsed; a dry run no longer stores the ETag/Last-Modified (otherwise a later real load could be told "unchanged" about announcements never loaded); `--unconditional` / workflow input forgets stored validators so a page, not a 304, comes back.

## Investify parser fixed against the live page (2026-11-18) - IMPLEMENTED
- Dry run 3 (05:51 UTC, 1 request) returned the page and kept it. Cause of "0 parsed": Investify changed the announcement headings from h3 to h2. Both are read now; run offline on the saved live page it parses 22 of 25 announcements (3 are outside the watchlist). Test added.
- Finding: the "Highlights" key-line is no longer in the static page (it sits behind a button), so only the title and Investify's one-line summary are captured. The summary is stored under the same private-use consent as Highlights (the job already stores highlights + summary). Owner to confirm that is acceptable, or to turn it off.
- The live list holds only the newest 25 (17-18 Nov); 16 Nov and older came from the owner's snapshot (to 16 Nov 23:55 UTC), so there is no gap.

## Investify announcements loaded (owner approved, 2026-11-18) - IMPLEMENTED
- Live load at 08:06 UTC (13:06 PKT, 1 request): 19 announcements parsed, 47 facts written to psx-library (titles plus Investify's one-line summaries, private use). Requests today before it: 4 (robots.txt 05:09, pages 05:29, 05:51, 06:15 UTC), all inside the window and at least 15 minutes apart.
- Gap found: the page lists only the newest 25, so by 13:06 PKT the 17 Nov items seen at 05:51 UTC had scrolled off. Closed WITHOUT a new request: `scripts/investify_page_to_facts.py` + workflow `investify_saved_page.yml` turn the page saved by the 05:51 dry run (artifact, 3 days) into facts; exact repeats are skipped.
- Lesson for the schedule: the page holds the newest 25 only, so on busy days it must be read often enough that nothing scrolls off (within the 15-minute floor and 12/day limits).

## Dashboard keeps itself current (owner, 2026-11-18: "Why it moved has old data") - IMPLEMENTED
- Cause: the library already held 18 Nov prices (written 16:32 PKT, after the close; 278 bars), but an open Streamlit page never re-reads by itself, and the data was cached 30 minutes. A trading day's prices only arrive after the close plus the technical engine's update (about an hour after).
- Fix: the dashboard body is a fragment that re-runs every 10 minutes over a 15-minute cache, has a "Refresh now" button, and states "prices to / news to / read at" with the reason prices lag. Tests pass.

## "Why it moved" shows every day's moves (owner screenshots, 2026-11-19) - IMPLEMENTED
- The tab listed only moves that already had a candidate cause and put unexplained ones in a separate list at the bottom, so 18 Nov moves with no cause on file (for example 786 up 10%) were hidden below 17 Nov ones. Now grouped by day, newest first, biggest first within a day, every notable move shown; unexplained ones say "no cause on file yet".

## Investify scheduled reads (owner approval 2026-11-19) - IMPLEMENTED
- `investify_library.yml` now also runs on a schedule (cron 7,37 UTC, 05-10 UTC, Mon-Fri = 10:07-15:37 PKT) and loads the facts. The gate in code decides whether a request is made, so cron slots outside the window, in the 15-minute floor or past a ceiling end with no request. Kill switch: repository variable PSXNI_KILL_SWITCH=true. Reason: the page holds only the newest 25 announcements, so unread slots lose items.
- Council view on the dashboard: BLOCKED on a storage decision (see report); technical-engine signals already appear in the setups cards and move evidence.

## Council fixes after the 18-verdict review (owner, 2026-11-19) - IMPLEMENTED (dry run only)
- Review of the first 18 verdicts: petrol-price and "PSX rally fizzles" repeats used the 6-a-day cap; only 2 of the assessments named a company; 8 were market-wide.
- `council_ledger.reserve_batch`: a queued story similar to one assessed within the last 36 hours (same figure and subject, same companies; different companies never match) or already taken in the same batch is marked "covered" with a note, kept in the queue, and not run again (`COVER_HOURS`). `news_importance.priority`: a headline event naming a listed company gets +10, a market-wide-only one -5, so company stories run first.
- The announcement gate was verified live: it scans every 6 hours and found 3-6 material announcements per scan (18-19 Nov); they join the same queue under the same cap.
- Still true: one free model answers every lens; the 7-day report is due about 24 Nov; production storage stays OFF until the owner approves.

## Calibration of the technical setups score, first result (2026-11-19) - IMPLEMENTED (read only)
- `engines/setups_calibration.py`, `scripts/calibrate_setups.py`, workflow `setups_calibrate.yml`. Walk-forward on 121 stored sessions (25 May to 19 Nov 2026), 148 symbols, price items only (fundamentals cannot be tested on the past: the ratios on file are today's values).
- Result: top-10 by the technical score beat the whole eligible group by +0.22% (1 session), +0.87% (5), +2.46% (10); beat it on 53%, 64% and 83% of days. But the rank correlation over the whole group is only -0.02, -0.01 and +0.03: the edge sits in the top end, not in the ranking as a whole. Item by item: 20-session change +0.034 and position in range +0.052 at 10 sessions; volume against usual is NEGATIVE at every horizon (-0.03 to -0.05: heavy-volume days were followed by weaker returns).
- Cautions: the 10-session windows overlap, so the printed t-stats overstate certainty (an overlap-adjusted t is roughly 8.8/sqrt(10) = 2.8); one market regime; no costs or slippage; many small caps in the top end are limit-move names; universe is today's symbols. Indicative, not proof. Not yet done: a first-half versus second-half stability check, the market's own drift over the period, a higher liquidity floor, and a lower weight for the volume item (nothing was fitted).

## Robustness of the technical setups score (2026-11-19) - IMPLEMENTED (read only)
- Market drift: the eligible group FELL on average over the period (-0.44% per 5 sessions, -0.81% per 10). The top-10 by score earned +0.43% and +1.65%: relative strength in a falling market, not a rising one.
- Overlap-aware t (days h sessions apart): 5 sessions 0.5 (n 19, not significant); 10 sessions 2.8 (n 9, weak: few independent samples).
- Both halves positive (excess +1.29pp then +0.59pp at 5 sessions; +3.59pp then +1.63pp at 10): the effect weakened in the second half. A Rs 100m liquidity floor keeps it (+1.93pp at 10). Removing or halving the volume item raised the excess (+3.05pp, +2.93pp vs +2.46pp): consistent with its negative rank correlation, but chosen after seeing the data, so NOT adopted. Weights unchanged.
- Next: forward (out-of-sample) tracking of the live top 10, recorded daily, before any weight change.

## Forward (out-of-sample) tracking of the setups (owner approval 2026-11-19) - IMPLEMENTED
- `engines/setups_forward.py`, `scripts/setups_forward.py`, workflow `setups_forward.yml` (weekdays 12:41 UTC, after that day's prices are in; also dispatch). Each day the live top 10 of the three tabs plus the volume-removed technical variant are recorded with the whole eligible group in a PRIVATE file (Actions cache + 90-day artifact); nothing is written to psx-library. Snapshots are scored against the next 1, 5 and 10 sessions as they mature. A verdict needs at least 20 scored snapshots per horizon (about a month); no weights change before then.

## Council seven-day dry-run evaluation (2026-11-19) - DONE; recommendation C
- Report: `docs/COUNCIL_DRYRUN_EVALUATION_2026-11-19.md`; separate minimal dashboard proposal: `docs/DASHBOARD_PROPOSAL_MINIMAL.md`. Production storage NOT activated; no weights changed; dry-run records preserved; no paid API. Recommendation C (remediate, then another dry run): corporate-action rule missing (43 material-looking unflagged), Mettis timestamps about +5 h, single model so disagreement unmeasurable, council ran only 3 days. Awaiting the owner's decision; no activation without explicit approval.
