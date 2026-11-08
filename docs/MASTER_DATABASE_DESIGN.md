# Master database design (proposed; no migration is created by this document)

Status: DESIGN (main `012a6bf`). Turso Starter limits apply: 500M rows read and 10M rows written per month, and 5
GB storage. Measured on 2026-11-08: about 3 billed rows written per bar insert (table plus indexes), and 1.97 MB
used in total. Any migration below is a **proposal**. Each needs its own PR, a disposable-Turso verification and
owner approval (`MASTER_SECURITY_AND_OPERATIONS.md` §4).

## 1. Reuse first: existing tables and their future role
| Domain | Existing objects (migration) | Future use |
|---|---|---|
| Sources and raw documents | `sources`, `source_items`, `source_item_versions`, `collector_checkpoints`, `collector_runs`, `dataset_loads` (0001/0005/0006) | All acquisition; financial PDFs are `source_items` (hash, URL, retrieval_method `pdf`) |
| Company master | `companies`, `company_identifiers`, `company_aliases`, `company_status_history`, `company_classifications`, `sectors`, `index_memberships` (0001) | Universe expansion: ticker and name history, delistings, sector changes |
| Segments and relationships | `company_segments` (0001), `company_relationships` (0008) | Segment revenue shares; subsidiaries and associates |
| Financial metrics | `financial_metrics` (0003): company, period_end, period_type, metric, value, unit, currency, basis, calculation_method, source_item | **Canonical** reported and calculated values (long format) |
| Sector metrics, commodities | `sector_metrics`, `commodity_prices` (0003) | Sector volumes; commodity benchmarks |
| Funds | `funds`, `fund_holdings` (0003) | Optional: institutional holdings, if a source is approved |
| Research views | `research_views` (0003) | Third-party analyst views, attributed, never mixed with our outputs |
| Forecasts and outcomes | `alerts_predictions`, `market_outcomes` (0003) | Predictive records and their evaluations (workstream F) |
| Analyses | `analyses` (0003) | Retained for Phase 3 compatibility; new work uses the dedicated tables below |
| Events and evidence | `events`, `event_revisions`, `event_evidence`, `event_extractions`, `story_clusters*`, `llm_calls` (0002/0007) | Unchanged |
| Exposure and impact | `exposure_*`, `company_exposures`, `impact_*` (0008/0009) | Unchanged; quantified magnitude later reads `financial_metrics` |
| Market | `market_bars`, `market_bar_corrections`, views (0010) | Unchanged; universe grows within budget (§6) |
| Watchlist | `user_watchlist` (0004) | The owner's priority list, kept separate from liquidity qualification |

## 2. Proposed additions (by milestone)
**Legend:** **E** = essential for its milestone; **O** = optional.

| Table | Milestone | Why existing tables can't hold it | Main fields | Relationships / indexes | Retention | Write load | E/O |
|---|---|---|---|---|---|---|---|
| `financial_reports` | M2 | `source_items` is document-level, without period, scope or audit metadata | report_id, company_id, source_item_id, doc_type (annual / half / quarterly), period_end, period_months, scope (consolidated / unconsolidated), currency, unit_scale, audit_status (audited / reviewed / unaudited), auditor_opinion (unmodified / qualified / adverse / disclaimer / emphasis), restates_report_id, extraction_status, created_at | FK company, source_item; UNIQUE (company_id, doc_type, period_end, scope, source_item_id); index (company_id, period_end) | Permanent | ~4 per company per year | **E** |
| `financial_line_items` | M2 | `financial_metrics` holds canonical values only; raw labels, page and table coordinates and confidence need their own append-only table | line_id, report_id, statement (IS / BS / CF / note), raw_label, canonical_code (nullable until mapped), column_period_end, value, unit_scale, page, table_ref, extraction_method (text / ocr / manual), confidence, review_status | FK report; index (report_id, statement); index (canonical_code) | Permanent | ~150–400 per report | **E** |
| `account_mappings` | M2 | Versioned label-to-canonical dictionary, per framework | mapping_id, framework (bank / insurer / corporate), raw_label_normalised, canonical_code, version, approved_by, approved_at | UNIQUE (framework, raw_label_normalised, version) | Permanent | Small | **E** |
| `corporate_actions` | M2 / M4 | Nothing stores dividends, bonus shares, rights issues or splits | action_id, company_id, action_type, ex_date, record_date, ratio_or_amount, currency, source_item_id, status | FK company; index (company_id, ex_date) | Permanent | Small | **E** |
| `report_disclosures` | M2 | Contingencies, litigation, related parties, auditor text | disclosure_id, report_id, kind, text_span (≤ 2,000 chars), page, source_item_id | FK report; index (report_id, kind) | Permanent | Small | O |
| `macro_observations` | M6 | `commodity_prices` is for commodities only | obs_id, series_code, reference_period, value, unit, release_date, vintage, source_item_id | UNIQUE (series_code, reference_period, vintage); index (series_code, reference_period) | Permanent (all vintages) | Small | **E** |
| `macro_series` | M6 | Series metadata | series_code, name, unit, frequency, source_id, definition | — | Permanent | Tiny | **E** |
| `dimension_assessments` | M3 | Dimensions A–L have no store; `impact_assessments` is event × mechanism only | assessment_id, company_id, dimension (A–L), as_of_date, band (or state), components_json, evidence_json, engine_version, data_state, created_at | UNIQUE (company_id, dimension, as_of_date, engine_version); index (dimension, as_of_date) | Permanent (history) | ~12 per company per run | **E** |
| `valuations` | M5 | No store for method, inputs, ranges or sensitivity | valuation_id, company_id, as_of_date, method, inputs_json (ids), assumptions_json, conservative / base / optimistic, sensitivity_json, data_quality, state (ok / not_applicable / insufficient_data), engine_version | UNIQUE (company_id, as_of_date, method, engine_version); index (company_id, as_of_date) | Permanent | ≤ 5 per company per run | **E** |
| `market_metrics_daily` | M4 | Avoid recomputing 20-session ADV, liquidity and returns on each page view (read budget) | symbol, session_date, adv20_shares, traded_value20, return_1d, adj_close, liquidity_qualified, engine_version | PK (symbol, session_date, engine_version) | Rolling, rebuildable | 1 per symbol per day | O (cache) |
| `labels` | M7 | The JSON label file stays the human-maintained source; a DB copy enables joins and history | label_id, kind, subject_ref, expected_json, labeller, labelled_at, source_note, version | index (kind) | Permanent | Small | O |
| `validation_runs` | M7 | Store measured metrics and FP/FN with the code version | run_id, engine_versions_json, label_version, metrics_json, created_at | — | Permanent | Tiny | **E** |
| `report_snapshots` | M9 | Reproducible reports | snapshot_id, kind, subject, generated_at, input_versions_json, content_sha256, body (Markdown, compressed if needed) | index (kind, subject, generated_at) | Configurable (owner) | Per report | **E** |
| **Portfolio DB** (separate Turso database): `portfolios`, `positions`, `transactions`, `theses`, `alert_rules`, `alert_events` | M8 | User data must be isolated from shared research data | user-scoped keys; theses link to company ids and assumptions; alert rules reference dimensions and events | Own DB, own token (`PSXNI_PORTFOLIO_*`) | Per user | Small | **E** for M8 |

**Change to an existing table** (proposed, additive):
* `financial_metrics` gets `report_id` (nullable, FK `financial_reports`), `scope`, `supersedes_metric_id` and
  `state` (§6 data states). This is additive, and existing rows remain valid.

## 3. Relationships (logical)
```
companies ─┬─ financial_reports ── financial_line_items ──(account_mappings)──▶ financial_metrics
           ├─ corporate_actions                                                   │
           ├─ market_bars ──▶ market_metrics_daily                                │
           ├─ exposure_candidates ── impact_assessments (T1–T9)                   │
           ├─ dimension_assessments (A–L) ◀── financial_metrics, market_metrics_daily, impact_assessments
           ├─ valuations ◀── financial_metrics, market_bars, corporate_actions, macro_observations
           └─ alerts_predictions ── market_outcomes
macro_series ── macro_observations ──▶ impact transmission (stated change / magnitude)
report_snapshots ◀── all of the above (by version id)
```

## 4. Idempotency and corrections
* **Ingestion keys:** every ingestion uses a natural UNIQUE key (above) plus a processing record. Re-runs are
  no-ops.
* **Corrections and restatements:** a new row with `supersedes_*` or `restates_report_id`. Readers use the
  latest non-superseded row, and history is never deleted.
* **Engine versions:** engine outputs carry their `engine_version`. A ruleset change writes new rows under the
  new version, so old outputs stay reproducible.

## 5. Indexing and read efficiency
* Every dashboard query is keyed on (company_id, date), (symbol, date) or (dimension, date), with matching
  indexes as listed.
* Aggregates (coverage, ADV) come from `market_metrics_daily` or indexed MIN/MAX, as in Stage 1, never from
  full scans.
* Pagination is used everywhere, with a cache of 5–15 minutes.

## 6. Write and storage budget (estimates; measure after each milestone)
Estimates use the measured ~3 billed rows per row inserted (table plus two indexes).

| Domain | Volume | Billed rows written |
|---|---|---|
| Daily bars, 600 symbols | 600 × ~21 sessions | ~38k / month |
| 1-minute bars, 600 symbols | 600 × ~375 × ~21 | ≈ **14M / month: exceeds the 10M quota** |
| 1-minute bars, 120 symbols (illustration of a 100+ priority list) | 120 × ~375 × ~21 | ~2.8M / month |
| 1-minute bars, 25 symbols (capacity illustration only) | 25 × ~375 × ~21 | ~0.6M / month |
| Financial line items, 600 companies | 600 × 4 reports × ~300 lines / year | ≈ 2.2M / year, mostly one-off backfill |

* **1-minute bars for all ~600 symbols exceed the quota,** so the intraday universe is bounded. The 25- and
  120-symbol rows are capacity illustrations, not an approved universe; the actual intraday size is an owner
  decision (U7).
* **The manually curated priority list (100+ stocks) is never reduced or filtered** by this budget or by
  liquidity qualification (20 sessions, initial 100,000-share ADV threshold, with traded value and other
  liquidity measures). News, fundamentals, macro and event monitoring stay broad and independent of
  liquidity filters.
* **Storage:** per-row size isn't measured reliably yet. Measure `storage_bytes` after M2 and M4 backfills before
  widening.

## 7. Migration sequence (proposed)
| Migration | Contents | Milestone |
|---|---|---|
| 0011 | `financial_reports`, `financial_line_items`, `account_mappings`, `corporate_actions`, `report_disclosures`, `financial_metrics` additions | M2 |
| 0012 | `dimension_assessments`, `valuations` | M3 / M5 |
| 0013 | `macro_series`, `macro_observations` | M6 |
| 0014 | `validation_runs`, `labels` | M7 |
| 0015 | `market_metrics_daily`, `report_snapshots` | M4 / M9 |
| Portfolio DB schema | Separate | M8 |

Each migration is additive, with append-only triggers where history matters.
