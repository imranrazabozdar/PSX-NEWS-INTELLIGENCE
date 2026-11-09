# Master implementation plan (one programme, milestones M0–M10)

Status: DESIGN (main `012a6bf`, 2026-11-08). This is a plan, not an authorisation. Each milestone starts only
with the owner's explicit approval and ends at its acceptance gate (CLAUDE.md: one approved phase at a time).
Concepts: `MASTER_ARCHITECTURE.md`. Sources: `MASTER_DATA_SOURCE_REGISTER.md` (R1–R6). Tables:
`MASTER_DATABASE_DESIGN.md`. Tests: `MASTER_VALIDATION_STRATEGY.md`. Controls:
`MASTER_SECURITY_AND_OPERATIONS.md`. Decisions: U1–U11 (architecture §9).

**Two kinds of completion, always reported separately:**
* **Code complete:** merged, tests pass in CI, `STATUS.md` = TESTED.
* **Operationally accepted:** observed working in production with evidence (run ids, row counts, screenshots),
  after a separate owner approval to activate. A merged PR never authorises production access.

Every milestone also has these standing items, not repeated below:
* `check_independence`, ruff and pytest stay green;
* no invented data (missing data is a typed state, never zero);
* no buy/sell instructions;
* `STATUS.md` and `PROJECT_ROADMAP.md` are updated.

---

### M0 — Stage 1 and Stage 2 operational acceptance (owner actions; runs in parallel)
* **Objective:** close the outstanding production evidence for existing code.
* **Items:**
  1. a scheduled run of the current collector code succeeds;
  2. a continuation after a budget stop is observed;
  3. the backfill completes for OGDC, HBL, LUCK, ENGROH and PSO;
  4. the external dispatcher is live (owner token and scheduler, `EXTERNAL_DISPATCH.md`);
  5. moon-dependent holidays and Ramadan hours are entered from PSX notices;
  6. optional: intelligence pipeline activation (`INTELLIGENCE_ACTIVATION.md`).
* **Reuse:** all existing; no new code is expected.
* **Database changes:** none.
* **Dependencies:** owner token, scheduler and approval.
* **Acceptance:** evidence recorded in `COLLECTION_ORCHESTRATION.md` §5.
* **Risks:** SCS outage; unreliable GitHub cron (the dispatcher mitigates it).
* **Evidence:** run ids, `collector_runs` rows, coverage-tab screenshot.

### M1 — Source access and company universe (decisions U1, U4; research R1, R5)
* **Objective:** know, per company, where its financial documents legally come from; define the universe.
* **Components:**
  * R1 IR review for the 51 master companies (URL, robots, terms, formats, history depth);
  * R5 SCS index and adjustment check;
  * universe register: manual priority list (`user_watchlist`) kept separate from liquidity qualification
    (ADV over 20 sessions ≥ 100,000 shares, initial threshold, U9).
* **Reuse:** `companies`, `company_identifiers`, `company_status_history`, `SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`.
* **New modules:** `engines/universe.py` (classification only, no collection).
* **Database changes:** none (existing tables).
* **Sources:** read-only reviews; the PSX site is read by a person, never automated.
* **Dependencies:** none; can start immediately.
* **Tests:** universe rules (priority never filtered out; illiquid flagged, not hidden; delisted kept with history).
* **Acceptance:** register rows upgraded to V or B per company, approved by the owner.
* **Risks:** many IR sites disallow automation, which pushes work to manual import.
* **Evidence:** updated register, approved list.

### M2 — Financial document acquisition and extraction (critical path; U3)
* **Objective:** reported statements as traceable line items, then canonical metrics.
* **Components:**
  * approved IR PDF collection through `collect_document`, plus manual import;
  * text PDF extraction (OCR optional, U3);
  * statement and table detection; scope (consolidated / unconsolidated) and unit-scale detection;
  * mapping through versioned `account_mappings` (bank / insurer / corporate);
  * reconciliation checks (balance sheet balances; subtotals; cash-flow tie-out; prior-period comparatives);
  * restatement handling; corporate actions from report notes and approved notices.
* **Reuse:** `source_items`, `dataset_loads`, `MANUAL_IMPORT_DESIGN.md`, `financial_metrics`.
* **New modules:** `collectors/financial_documents.py`, `engines/fin_extract.py`, `engines/fin_mapping.py`,
  `engines/fin_reconcile.py`.
* **Database changes:** migration 0011.
* **Dependencies:** M1, U3 (PyPI libraries only, owner-approved).
* **Tests:** golden fixtures from real public reports (stored with provenance); reconciliation failures become
  `needs_review`, never auto-filled.
* **Acceptance:** for a pilot of 5 companies × 3 years:
  * every canonical value traces to page and line;
  * reconciliation passes, or is flagged;
  * a human spot-check of ≥ 50 values.
* **Risks:** scanned PDFs; format drift; write budget during backfill (estimate in the database design §6).
* **Evidence:** pilot report, spot-check sheet.

> **Dimension letters (corrected 2026-11-09).** `MASTER_ARCHITECTURE.md` §5 defines the dimensions, and this plan
> follows it:
> * M3 writes A–C, M5 writes D, and M4 writes I–J.
> * The earlier labels "M3 B–F" and "M5 G" contradicted §5 and were a labelling error.
> * E (sector outlook), F (macro conditions), G (geopolitical), H (market sentiment), K (event opportunity) and L
>   (risk) are not yet written to `dimension_assessments`. F, G and K exist only as Stage 2 impact assessments
>   (T1–T9).

### M3 — Fundamentals (dimensions A–C)
* **Objective:** framework-specific ratios and dimension assessments with stated components.
* **Components:**
  * bank, insurer and general frameworks, plus sector overlays;
  * growth, profitability, balance sheet, cash quality and governance flags (auditor opinion, related parties);
  * reported, calculated, interpreted and estimated values kept separate.
* **Reuse:** `financial_metrics`, `company_classifications`.
* **New modules:** `engines/fundamentals/` (one module per framework).
* **Database changes:** 0012 (`dimension_assessments`).
* **Dependencies:** M2.
* **Tests:** hand-calculated expected ratios; `not_applicable` for bank ratios on non-banks; missing inputs give
  `insufficient_data`.
* **Acceptance:** pilot companies reproduce hand calculations exactly; the owner approves band thresholds (U9).
* **Risks:** threshold subjectivity, so bands stay descriptive with components shown.

### M4 — Market intelligence (SCS primary; parallel to M2–M3)
* **Objective:** adjusted prices, returns, liquidity and relative performance.
* **Components:**
  * corporate-action adjustment (from M2 `corporate_actions`, or SCS if R5 confirms it);
  * 20-session ADV and traded value; liquidity qualification flag;
  * volatility and drawdown (descriptive only);
  * benchmark-relative returns if U5 resolves;
  * universe expansion within the write budget (U7).
* **Reuse:** `market_bars`, `market_quality`, `market_calendar`, the collection orchestrator.
* **New modules:** `engines/market_intel.py`.
* **Database changes:** 0015 (`market_metrics_daily`) (optional cache).
* **Dependencies:** M1 universe; M2 for adjustments (unadjusted series are labelled as unadjusted).
* **Tests:** split and bonus adjustment fixtures; ADV with missing sessions excluded rather than zero-filled.
* **Acceptance:** adjusted series match a hand-adjusted fixture; the write budget is measured.
* **Risks:** no benchmark (market-relative checks stay `not_evaluable`).

### M5 — Valuation (dimension D; critical path)
* **Objective:** method-appropriate valuation ranges with assumptions and sensitivity, not price targets.
* **Components:**
  * P/E, P/B, EV/EBITDA, dividend yield, P/B–ROE for banks;
  * DCF / DDM only with owner-approved assumptions;
  * conservative / base / optimistic outputs; sensitivity tables.
* **Reuse:** M3 metrics, M4 prices.
* **New modules:** `engines/valuation.py`.
* **Database changes:** 0012 (`valuations`).
* **Dependencies:** M3, M4, U6 (no consensus means no forward multiples).
* **Tests:** hand-calculated; `not_applicable` (e.g. negative earnings P/E); assumptions are always shown.
* **Acceptance:** pilot reproduction; the owner reviews the wording (no buy/sell language).
* **Risks:** misreading as advice, so mandatory disclaimers and range-only outputs.

### M6 — Macro, commodity and sector series (parallel; U2)
* **Objective:** time series with vintages that feed impact transmission (T1–T9) magnitude.
* **Components:**
  * EIA connector (after key and terms);
  * World Bank Pink Sheet (after terms decision);
  * manual import of SBP / PBS / MoF release values;
  * sector series where a lawful source exists.
* **Reuse:** `commodity_prices`, `sector_metrics`, `impact_intel` mechanisms.
* **New modules:** `collectors/eia.py`, `collectors/worldbank.py`, `engines/macro.py`.
* **Database changes:** 0013.
* **Dependencies:** U2; independent of M2–M5.
* **Tests:** vintage handling (revision means a new row); recorded-response fixtures only, no live calls in CI.
* **Acceptance:** series loaded with provenance; one T-mechanism shows a quantified driver change.
* **Risks:** terms; lags.

### M7 — Human labels, validation and backtesting (start labelling now; U10)
* **Objective:** measured accuracy; walk-forward evaluation before any predictive output is shown.
* **Components:**
  * labelling guide and workflow;
  * `validation_runs`;
  * event-study harness (abnormal returns, needs benchmark U5);
  * walk-forward splits with a no-look-ahead check.
* **Reuse:** `engines/validation.py` (MIN_LABELS = 30), `alerts_predictions`, `market_outcomes`.
* **New modules:** `engines/backtest.py`.
* **Database changes:** 0014.
* **Dependencies:** labels (people); M4 for outcomes.
* **Tests:** leakage tests; insufficient labels give no score.
* **Acceptance:** ≥ 30 labels per reported metric; metrics published with FP/FN lists.
* **Risks:** labelling capacity is the real bottleneck, so it starts early in parallel.

### M8 — Portfolio, theses and opportunity screens (U8)
* **Objective:** the owner's holdings and theses checked against evidence; screens are descriptive filters, not
  recommendations.
* **Components:** separate portfolio database; thesis assumptions linked to dimensions; alert rules on events and
  dimension changes.
* **Reuse:** all assessment tables (read-only).
* **New modules:** `engines/portfolio.py`, `engines/alerts.py`.
* **Database changes:** portfolio DB schema (separate Turso database, `PSXNI_PORTFOLIO_*` secrets).
* **Dependencies:** M3–M5; U8.
* **Tests:** isolation (no cross-database joins); a thesis is broken when its evidence changes.
* **Acceptance:** owner walkthrough. No order execution exists or will be built.

### M9 — Integrated platform and reports (15 sections)
* **Objective:** reproducible company, sector and market reports built from stored assessments.
* **Components:**
  * report generator with sections: identity, business, events, exposure, impact, fundamentals, quality,
    valuation, market, macro links, risks, governance, scenarios, data gaps, sources;
  * `report_snapshots`; dashboard pages for implemented modules only.
* **Reuse:** `engines/research.py`, `dashboard_views.py`.
* **New modules:** `engines/reports.py`.
* **Database changes:** 0015 (`report_snapshots`).
* **Dependencies:** whichever modules are implemented; absent modules render as `not_processed`, never omitted
  silently.
* **Tests:** snapshot reproducibility (same inputs give the same hash); every number links to its source.
* **Acceptance:** owner review of pilot reports.

### M10 — Production activation and operational acceptance (per module)
* **Objective:** activate each module only after separate owner approval; observe it in production.
* **Process:** `MASTER_SECURITY_AND_OPERATIONS.md` §4:
  1. backup;
  2. disposable-database rehearsal;
  3. migration;
  4. limited run;
  5. evidence;
  6. widen.
* **Acceptance:** per-module operational evidence recorded; the rollback path is tested.

---

## Critical path and parallel work
```
M1 ──▶ M2 ──▶ M3 ──▶ M5 ──▶ M8 ──▶ M9
          └──▶ M4 (adjustments) ─┘
M0 (owner, now) ║ M6 (after U2) ║ M7 labelling (now) ──▶ backtesting (after M4, U5)
M10 follows each module separately.
```

| Route | Milestones |
|---|---|
| **Critical** | M1 → M2 → M3 → M5 |
| **Start immediately in parallel** | M0, R1/R5 research, M7 labelling, U-decisions |
| **Parallel after their decisions** | M4 (after M1), M6 (after U2) |

## Cost
| Item | Status |
|---|---|
| Sources | All free in this plan |
| Licensed provider (U1) | Quote required |
| Turso | Within the Starter plan given the U7 limits |
| PyPI PDF libraries | Free (U3) |
| AI | None (U11 not authorised) |

## Token-efficient delivery (for agent-assisted work)
* **One milestone per session.** Start from this plan and the milestone's section only.
* **Read narrowly:** grep for symbols and read the relevant ranges, not whole files.
* **Reuse existing modules and test fixtures;** don't re-derive designs these documents already settle.
* **Small PRs per component;** run the fast checks locally before pushing.
* **Use recorded fixtures,** never live sources, in tests.
* **Record decisions in the documents** so later sessions don't re-litigate them.
