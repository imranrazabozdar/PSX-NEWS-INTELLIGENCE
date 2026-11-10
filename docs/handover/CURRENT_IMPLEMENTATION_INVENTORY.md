# Current implementation inventory

Last verified: 2026-11-10. News base: `origin/main` f2af9ed. Technical base: `main` 47e70e3.
Status classes: 1 not implemented · 2 scaffold only · 3 implemented, untested · 4 unit-tested · 5 integration-tested · 6 tested on real data · 7 production-validated · 8 blocked.
"On main" means present on that repository's `main`. Otherwise the branch named is where the code lives.

## A. News repository (PSX-NEWS-INTELLIGENCE)

### A1. Database and migrations
| Component | Path | Where | Status | Tests / evidence | Next action |
|---|---|---|---|---|---|
| Connection, ownership guard, purposes | `database/connection.py` | main; purpose guard on branch `feature/database-ownership` (PR #58) | 4 | `tests/test_database.py`; ownership tests on branch | Merge PR #58 |
| Migration runner | `database/migrate.py` | main | 5 | migration tests | keep |
| Migrations 0001–0014 | `database/migrations/` | main; applied to production | 7 (ledger check) | [PROD-RO 2026-11-10] | No new migration without the runbook |
| Seed loader | `database/seed_loader.py`, `database/seed/*.json` | main | 5 | seed tests | Expand universe (tasks) |
| Repositories (source items, events, evidence) | `database/repositories.py` | main | 5 | `tests/test_database.py`, `tests/test_intelligence.py` | keep |
| Seed validation | `database/validation.py` | main | 4 | seed validation tests | keep |
| Canonical timestamps | `database/canonical.py` | main | 4 | `tests/test_canonical.py` | keep |

### A2. Company master and entity resolution
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Company master: 51 records (50 listed, 1 delisted) | `database/seed/companies.json` | main; 50 seeded from PSX [REPORTED in STATUS] | 6 for those 50 | seed tests | Extend to whole PSX universe; source each record |
| Entity resolution | `engines/entity_resolution.py` | main | 5 | `tests/test_exposure_mapping.py` (entity resolution is exercised there and in `tests/test_impact_exposure_*.py`) | Add subsidiary and brand mapping |
| Direct company scan of text (evaluation) | `engines/evaluation.py` | branch `feature/evaluation-harness` (PR #60) | 4 | `tests/test_evaluation.py` (12) | Merge after review |

### A3. Collection and sources
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Collection engine (HTTP, robots, retries, budgets) | `collectors/engine.py`, `collectors/http.py`, `collectors/parsers.py`, `collectors/run.py` | main | 5 | `tests/test_collectors.py` | Keep; check robots rules on every change |
| Market OHLCV collector and orchestration | `collectors/market_ohlcv.py`, `collectors/market_orchestrator.py` | main | 5 (permitted sources only) | market tests | keep |
| Scheduled job workflow | `.github/workflows/scheduled-jobs.yml` | main; cron every 6 h | 3: production activation not verified [UNKNOWN] | none | Verify activation before relying on it |
| Source registry: 75 sources; 11 `verified_permitted` (metadata only) | `database/seed/sources.json` | main | 6 for permissions as recorded | seed tests | Re-verify permission text per source |

### A4. Relevance, extraction and LLM
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Relevance pre-filter (`relevance@v2`) | `engines/relevance_prefilter.py`, `config/relevance_rules.json` | main (PR #55) | 4 | `tests/test_relevance_prefilter.py` (10) | Wire into extraction |
| Extraction schema and validation | `engines/schema.py`, `engines/extraction.py` | main | 5 | `tests/test_intelligence.py` | keep |
| LLM gateway (protocol, budgets, kill switch, ledger) | `engines/llm.py` | main; the Claude provider is a stub that refuses | 5 with the fixture provider | `tests/test_intelligence.py` | keep |
| Live providers Groq, Gemini, OpenRouter with fallback and quotas | `engines/llm_live.py`, `config/llm_providers.json` | branch `feature/port-llm-providers-v2` (PR #57, merge-ready) | 4; disabled | `tests/test_llm_live.py` (21, fake HTTP) | Owner enablement only (LLM runbook) |
| Quarantine of legacy extraction records | `engines/quarantine.py` | branch `feature/candidate-quarantine` (PR #59) | 4 | `tests/test_quarantine.py` (13) | Merge; extend to other legacy tables (task 3) |

### A5. Events, verification, exposure and impact
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Event intelligence and headline events | `engines/event_intel.py`, `engines/headline_events.py` | main | 5 | `tests/test_event_intel.py`, `tests/test_headline_events.py` | keep |
| Similarity and clustering | `engines/similarity.py` | main | 4 | `tests/test_intelligence.py` | keep |
| Verification and corroboration | `engines/verification.py` | main | 4 | `tests/test_intelligence.py` | keep |
| Exposure mapping | `engines/exposure_mapping.py`, `engines/exposure_rules.py`, `engines/exposure_taxonomy.py` | main | 4 synthetic; real company relationships are 8 (blocked: no approved source) | `tests/test_exposure_mapping.py` | Source real segment and relationship data |
| Impact T1–T9 framework | `engines/impact_intel.py` | main | 4 | `tests/test_impact_*.py` (9 files) | Needs sourced inputs before any quantitative claim |
| Human review of candidates | `engines/review_revalidation.py` | main | 4 | review tests | Owner decides; no automatic decision |

### A6. Financial analysis
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Statement import with rights attestation, mapping, reconciliation, promotion (M2) | `engines/financials.py` | main | 5 offline; no real report imported [UNKNOWN] | `tests/test_m2_m3_financials.py` | Import a real report (owner supplies) |
| Ratios, growth, FCF, dimensions A–C (M3) | `engines/fundamentals.py` | main | 4 | `tests/test_m2_m3_financials.py`, `tests/test_pr40_review_regressions.py` | Owner sets bands (U9) |
| Valuation: multiples, DCF, scenarios (M5) | `engines/valuation.py` | main | 4 | `tests/test_m4_m5_market_valuation.py` | Inputs must be sourced; dimensions E, F, G, H, K, L not implemented (STATUS) |
| Macro series registry (M6) | `engines/macro.py`, `config/macro_series.json` | main | 4 (definitions only, no values) | `tests/test_m6_m9_macro_validation_portfolio_reports.py` | Source values |
| Backtest and validation (M7) | `engines/backtest.py`, `engines/validation.py` | main | 4 | `tests/test_m6_m9*` | No labels yet (U10) |
| Reports and snapshots (M9) | `engines/reports.py`, `engines/research_views.py` | main | 4 | `tests/test_research_views.py` | awaiting data |
| PDF reading and extraction | `engines/pdf_reader.py`, `engines/pdf_extraction.py`, `engines/document_intake.py` | main; reader is the owner-approved pinned pdfplumber | 4 | `tests/test_pdf_extraction.py` | Real report needed |
| Earnings quality and audit signals | `engines/earnings_quality.py` | branch `feature/earnings-quality` (PR #61) | 4 (synthetic inputs) | `tests/test_earnings_quality.py` (18) | Merge; connect to real report facts |
| Segment reconciliation | `engines/segments.py` | branch `feature/segments-and-notes` (PR #62) | 4 (synthetic) | `tests/test_segments_and_notes.py` (14) | Merge; use a real segment note |
| Notes extraction with page evidence | `engines/notes_extraction.py` | branch `feature/segments-and-notes` (PR #62) | 4 (synthetic text) | same | Run on a real report (blocked) |
| Multi-year normalisation; receivable ageing; auditor and KAM text extraction | not implemented | — | 1 | — | See tasks |

### A7. Dashboard and app
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Streamlit app (one tabbed app) | `app.py`, `engines/dashboard_views.py` | main | 5 via AppTest | `tests/test_app_skeleton.py` | Spec's 14-page layout is not built |

### A8. Code from the technical repository on main
None. The news `main` contains no code from the technical repository. Ported code lives on the branches listed above.

## B. Technical repository (PSX-INTELLIGENCE-NEW-2026)
| Component | Path | Where | Status | Tests | Next action |
|---|---|---|---|---|---|
| Technical indicators, scanners, Wyckoff, patterns | `fire_engine/`, `backend/` | main | 5 for their own tests [REPORTED] | their test files | Keep in this repo only |
| Patterns tab redesign | Patterns tab modules | PR #59, open | 4 [REPORTED: 23 AppTest tests] | [REPORTED] | Owner review; preserve |
| Investify pilot, parser, ingester (read-only, restricted source) | `backend/investify_*.py` | main (PR #61) | 6 for the 21-row run [REPORTED] | 40 offline tests [REPORTED] | Restricted; no scheduled collection |
| SCS chart OHLCV pilot | `backend/ohlcv_pilot.py` | main (PR #60) | 6 for the 120-row run [REPORTED] | 8 tests [REPORTED] | Wrote to the shared DB historically (incident) |
| Manual PDF vault and ingester | `backend/manual_pdf_ingester.py` | main (PR #61) | 5 [REPORTED] | [REPORTED] | keep |
| Company-master stub loader | `backend/company_master_loader.py` | main (PR #62) | 6 for 16 stubs [REPORTED] | part of 54 backend tests [REPORTED] | Historical writes to the news DB (incident) |
| `fundamental_engine/` baseline, router, providers | `fundamental_engine/core/`, `fundamental_engine/llm/`, `fundamental_engine/migrations/0010_baseline_snapshot.sql` | main (PR #63) | 4–5; 246 collected, 242 passed, 4 skipped [TEST] | `fundamental_engine/tests/` | Port only under the ADR-0001 exception |
| Relevance pre-filter, provider cascade | `fundamental_engine/extract/relevance.py`, `llm/` | main (PR #64) | 4 | `fundamental_engine/tests/` | Ported copy exists in news (PR #55) |
| Review workflow | `fundamental_engine/review/accept.py`, `fundamental_engine/review/queue.py` | main (PR #65) | 4 | `fundamental_engine/tests/test_review.py` | Its migration 0011 must never be applied to the news DB |
| Extraction quality: dedup, entity resolution, acquisition, evaluation | `fundamental_engine/extract/dedup.py`, `fundamental_engine/extract/entities.py`, `fundamental_engine/extract/evaluate.py`; `fundamental_engine/sources/acquire.py` | PR #66 branch only, open | 4 [REPORTED: 233 tests] | in PR #66 | Review, then port (tasks) |
| Shared-database guard | `fundamental_engine/core/db_guard.py`, `backend/turso_db.py` | PR #67 branch, open | 4 (9 tests) | `fundamental_engine/tests/test_db_guard.py` | Merge |
