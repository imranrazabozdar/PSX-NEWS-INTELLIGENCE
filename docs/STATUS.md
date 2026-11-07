# Implementation status register

Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED · TESTED (spec "Document status").
A feature is complete only when code **and** tests prove it. A page or placeholder doesn't count.

## Phases

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Specification and repository bootstrap | TESTED, approved and merged (PR #1) | See Phase 0 checklist below |
| 1 | Data foundation (Turso, migrations, company master) | TESTED, approved and merged (PR #2, merge commit 108cdd6) | See Phase 1 checklist below |
| 2 | First source collectors | NOT STARTED | |
| 3 | Event extraction and verification | NOT STARTED | |
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

## Requirements traceability

The full matrix, covering every section of the specification, is in [`TRACEABILITY.md`](TRACEABILITY.md).
