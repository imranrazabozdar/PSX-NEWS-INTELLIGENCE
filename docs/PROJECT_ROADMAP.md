# Project roadmap

Single source for where the project stands. Detail lives in the linked documents; status rules in `STATUS.md`.

## Stage 1: Data architecture: COMPLETE (code); operational acceptance pending
* **Done (main `a3724a0`):**
  * acquisition: RSS metadata, SCS OHLCV 1m/1h/4h/1d;
  * orchestration: single-writer lease (verified on real Turso), continuation, backoff, trigger tracking;
  * 1-minute-first backfill;
  * official PSX calendar (hours and fixed-date 2026 holidays);
  * completeness grading, gap recovery, cheap coverage, operations tab;
  * run 11 corrected.

  See `COLLECTION_ORCHESTRATION.md`, `EXTERNAL_DISPATCH.md`, `PSX_CALENDAR_MAINTENANCE.md`.
* **Operational acceptance conditions (production evidence still needed):**
  1. A scheduled run of the new code succeeds.
  2. A continuation after a budget stop is observed.
  3. The backfill covers all five symbols (OGDC, HBL, LUCK, ENGROH, PSO).
  4. The external dispatcher is live (needs the owner's token and scheduler).
  5. Moon-dependent holidays and Ramadan timings are entered from PSX notices.

## Stage 2: News intelligence: DESIGNED, not implemented
Design: `STAGE_2_NEWS_INTELLIGENCE_DESIGN.md`. It connects live headlines to the existing event (Phase 3),
exposure (Phase 4) and impact (Phase 5 / 0009) substrate. No new migration is needed for the first components.

| # | Component | Status |
|---|---|---|
| 1 | Headline event builder (`engines/headline_events.py`) | TESTED offline (local / CI only); not run in production |
| 2 | Rule classification + status stage (`engines/event_classification.py`, `engines/event_intel.py`) | TESTED offline; not run in production |
| 3 | Company / entity mapping (same modules) | TESTED offline; not run in production |
| 4 | Evidence assessment / verification state (same modules) | TESTED offline; not run in production |
| 5 | Exposure candidates from events (Phase 4 `map_event`, reading batch-1 entities) | TESTED offline; not run in production |
| 6 | T1–T9 impact engine (`engines/impact_intel.py`, scenario-only assessments) | TESTED offline; not run in production |
| 7 | Intelligence dashboard, company / sector reports, review queue, validation, readiness (`engines/dashboard_views.py`, `engines/research.py`, `engines/review_revalidation.py`, `engines/validation.py`, `engines/intel_pipeline.py`) | TESTED offline; not run in production |
| 8 | Optional AI assist | BLOCKED (provider not approved) |
| 9 | Production activation (prepared: `engines/intel_pipeline.py`, `docs/INTELLIGENCE_ACTIVATION.md`) | BLOCKED (owner approval) |
| 10 | Validation and calibration framework (human labels) | TESTED offline; no labels yet, so no scores |

## Master programme (DESIGN, not implemented)
The complete target system and its single programme are defined in `MASTER_ARCHITECTURE.md` and
`MASTER_IMPLEMENTATION_PLAN.md`, with `MASTER_DATA_SOURCE_REGISTER.md`, `MASTER_DATABASE_DESIGN.md`,
`MASTER_VALIDATION_STRATEGY.md` and `MASTER_SECURITY_AND_OPERATIONS.md`.

| Milestone | Scope | Status |
|---|---|---|
| M0 | Stage 1/2 operational acceptance (owner actions) | IN PROGRESS (evidence pending) |
| M1 | Source access and company universe | IN PROGRESS (universe/liquidity engine and 33-account X watchlist TESTED offline; R1–R7 research and owner priority list pending) |
| M2 | Financial document acquisition and extraction | PARTIALLY COMPLETE: import, text parsing, mapping, reconciliation, restatement flags, promotion TESTED offline; PDF→text BLOCKED (U3); no real report imported (R1) |
| M3 | Fundamentals | PARTIALLY COMPLETE: bank / insurer / corporate ratios and dimensions A–C TESTED offline; bands BLOCKED (U9); no real data |
| M4 | Market intelligence | PARTIALLY COMPLETE: corporate-action adjustment, returns, volatility, drawdown, liquidity, dimensions I–J TESTED offline; benchmark BLOCKED (U5); no corporate actions recorded |
| M5 | Valuation | PARTIALLY COMPLETE: multiples and assumption-driven DDM / DCF / justified P/B TESTED offline; consensus BLOCKED (U6); assumptions are owner inputs |
| M6 | Macro and commodity series | PARTIALLY COMPLETE: registry, manual import with vintages, point-in-time reads, driver changes TESTED offline; EIA / World Bank automation BLOCKED (U2) |
| M7 | Labels, validation and backtesting | PARTIALLY COMPLETE: validation runs, walk-forward, look-ahead guard, event study, prediction scoring, label template TESTED offline; no human labels (U10); outcome checks BLOCKED (U5) |
| M8 | Portfolio and theses | PARTIALLY COMPLETE: separate owner-scoped portfolio DB, holdings, marking, theses, alerts TESTED offline; multi-user and UI BLOCKED (U8) |
| M9 | Integrated reports | PARTIALLY COMPLETE: 13-section company report, sector and market views, reproducible snapshots TESTED offline; dashboard page not added |
| M10 | Production activation per module | PREPARED: `docs/OPERATIONS_RUNBOOK.md`; nothing activated (owner approval per module) |

Critical path: M1 → M2 → M3 → M5. Owner decisions U1–U11 are listed in `MASTER_ARCHITECTURE.md` §9.

## Future stages (spec §14; now mapped into the master programme)
* Corporate / policy / government modules.
* Commodities and sector risk.
* Institutional research.
* YouTube / X (needs authorised access).
* Valuation and scenarios.
* Event investigator with optional market context drawn exclusively from market data independently collected
  and stored within PSX News Intelligence. No data, indicators, code or other material is imported from or
  exchanged with the separate technical-analysis project.
* Backtesting and alerts.

## Key architectural decisions
* ADR-0001 independence from the technical project is permanent.
* Deterministic first. AI is optional, cost-capped and never required.
* Append-only provenance and revisions. Duplicates never count as corroboration.
* No invented data, exposures or price targets.
* The manual priority universe is never filtered by liquidity.
* Production writes, activations and migrations each need explicit owner approval.

## Known limitations
* News is headline-only.
* There's no approved company-evidence or macro data source, so exposures and magnitudes stay low confidence.
* The GitHub cron is unreliable until the external dispatcher is live.

## Next approved task
None approved. Proposed next: owner review of the master programme, decisions U1–U4, and approval of M1
(source access and universe). In parallel: the M0 evidence, an optional intelligence activation
(`docs/INTELLIGENCE_ACTIVATION.md`) and labelling (`data/validation/labels.json`).
