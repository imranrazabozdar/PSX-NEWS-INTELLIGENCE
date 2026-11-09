# Operations runbook: module readiness and controlled activation (M10)

Status (2026-11-08): **nothing in M1–M9 is active in production**, and migrations 0011–0014 are not applied to
Turso. Each activation below needs a separate, explicit owner approval. A merged PR is not approval.

## 1. Procedure for every activation (`MASTER_SECURITY_AND_OPERATIONS.md` §4)
1. **Backup:** back up the production database and record its SHA-256.
2. **Rehearsal:** apply the pending migrations to a **disposable** Turso database and run the module's tests and one
   limited run there. Then delete that database and rotate its token.
3. **Migrate production:** run `python -m database.migrate` against production. It is additive, and checksums are
   recorded in `schema_migrations`.
4. **Limited first run:** keep within the per-run budget (5,000 rows written, 50,000 read, 2,000 requests).
5. **Evidence:** record the run id, row counts and quota usage in this file.
6. **Widen:** only after the owner reviews the evidence. Rollback is to disable the job, or restore the backup.

## 2. Module readiness
| Module | Production prerequisites | Inputs the owner supplies | Rows written (estimate) |
|---|---|---|---|
| M1 priority list | Owner approval | The 100+ ticker list (`engines.universe.add_priority`) | ~100 |
| M1 X manual import | Owner approval | Post records with attestation (`docs/X_WATCHLIST.md`) | ~5 per post |
| M2 financial reports | Migration 0011; U3 (PDF libraries) for PDF input; R1 per company | Report JSON or extracted text, plus the document SHA-256 | ~150–400 lines per report |
| M3 fundamentals | Migration 0012; M2 data | — | 3 per company per period |
| M4 market intelligence | M2 corporate actions for adjustment; U5 for a benchmark | Corporate-action notices | 2 per company per run |
| M5 valuation | Migration 0012; M2–M4 data | Model assumptions (low, base, high) | ≤ 8 per company per as-of date |
| M6 macro | Migration 0013; U2 for EIA / World Bank automation | Official release values | Small |
| M7 validation | Migration 0014; U10 labels; U5 for outcome checks | Human labels | Tiny |
| M8 portfolio | A **separate** portfolio database and `PSXNI_PORTFOLIO_*` secrets; U8 | Transactions, theses, owner thresholds | Small |
| M9 reports | Migration 0014 | — | 1 snapshot per report |

## 3. Commands (development and rehearsal databases only, until approved)
* **Status:** `python -m engines.x_watchlist status` shows X watchlist status.
* **Python API, from a shell:**
  * `engines.financials.import_report` and `promote`
  * `engines.fundamentals.assess`
  * `engines.market_intel.assess`
  * `engines.valuation.value`
  * `engines.macro.import_observations`
  * `engines.reports.snapshot`

  There is no scheduled job for these modules, and none should be added without approval.

## 4. Point-in-time use
Backtests must call `engines.valuation.value(..., strict_point_in_time=True)`. That excludes reports with no
recorded filing date. Outside strict mode such reports are used and flagged as a possible look-ahead.

**DCF basis.** `assumptions["dcf"]["basis"]` must be declared, as `"fcff"` or `"fcfe"`. It is never inferred from
statement labels. The base cash flow is an owner-prepared FCFF or FCFE figure; the engine does not derive one from
CFO − capex, because companies treat interest differently in those lines.

| Basis | Discounted at | Gives | Equity value |
|---|---|---|---|
| FCFF | `wacc` | Enterprise value | EV − net debt − other claims. Net debt comes from reported borrowings and cash, or from an owner input. Other claims must always be stated (0 is allowed). |
| FCFE | `cost_of_equity` | Equity value directly | Net debt is not deducted again. |

* **Mixed rates are refused:** supplying the other basis's rate returns `insufficient_data`.
* **Terminal value:** a Gordon value on the final explicit-year cash flow, at the same rate and terminal growth.
  The rate must exceed terminal growth, otherwise the result is `not_applicable`.
* **Sensitivity:** every cell of the grid applies the same EV-to-equity conversion.

**ROE.** `roe` uses closing equity and is unchanged; it overstates ROE when equity grew during the year.
`roe_average_equity` uses the average of opening and closing equity. It is `insufficient_data` until the prior
fiscal year has been imported. Reports show both, each with its formula.

## 5. Monitoring
* Collection health uses the existing operations tab (schedule health, gaps, readiness).
* Manual imports record a `collector_runs` row (`x_manual_import`) or a `source_items` row with
  `retrieval_method = 'manual'`, with the importer and attestation in `source_metadata_json`.
* Report snapshots can be re-verified with `engines.reports.verify_snapshot`. `inputs_changed` means the stored
  inputs changed after the snapshot was taken.

## 6. Must stay disabled
X automated collection, EIA / World Bank automation, PSX / SBP / SECP automation, any paid provider, the optional
AI gateway, and order execution (never built).
