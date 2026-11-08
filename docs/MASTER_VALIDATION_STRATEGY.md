# Master validation strategy

Status: DESIGN (main `012a6bf`). This extends the existing harness `engines/validation.py`, which already provides:
* human labels only (`data/validation/labels.json`, currently empty);
* `MIN_LABELS = 30` per metric;
* FP/FN lists;
* market outcomes `not_evaluable` without a KSE-100 benchmark.

## 1. Principles
1. **Ground truth is human or primary-source evidence,** never an engine's own output.
2. **No score below the minimum sample.** Below `MIN_LABELS`, report `insufficient_labelled_data` with the count.
3. **Missing data is a state** (`data_unavailable`, `not_applicable`, `not_processed`…), never zero and never a
   pass.
4. **Tests use recorded fixtures.** No live network in CI, and no configured database: validation runs in
   isolated in-memory SQLite, as today.
5. **Every result records engine versions and label version** (`validation_runs`, M7).

## 2. Test layers per milestone
| Layer | What | Where |
|---|---|---|
| Unit | Each rule, ratio, mapping and state transition | `tests/` per module |
| Golden fixtures | Real public reports → expected line items and ratios, calculated by hand | M2, M3, M5 |
| Reconciliation | BS balances; subtotals; CF ties to cash change; comparatives match prior report | M2 (fail = `needs_review`) |
| Property / invariants | Adjusted price continuity across splits; ADV ignores missing sessions; append-only triggers hold | M2, M4 |
| Isolation and security | Independence guard; no cross-database joins; no secrets in logs | All |
| Labelled accuracy | Classification, entity, exposure, impact direction, calibration | Existing harness, M7 |
| Walk-forward / event study | Abnormal returns versus benchmark; no look-ahead | M7 (needs U5) |
| Reproducibility | Same inputs give the same report hash | M9 |
| Operational | Scheduled run, continuation, backfill, budget, rollback | M0, M10 (production evidence) |

## 3. Look-ahead and leakage controls (workstream F)
* **Point-in-time inputs:** every input carries its availability time (`published_at_utc`, report filing date,
  release date and vintage). Backtests only use rows available before the decision time.
* **Fixed splits:** walk-forward with fixed train and test windows; no parameter tuning on the test window.
* **Delisted companies stay in the history** (no survivorship bias, `company_status_history`).
* **Leakage tests:** shift an input's timestamp after the decision time and assert it disappears from features.

## 4. Acceptance thresholds
* Code acceptance is test-based (above).
* **Quality thresholds** (e.g. minimum direction accuracy before a predictive output is shown) are an owner
  decision (U9). None is set now, and until one is set, predictive outputs are not displayed.

## 5. Labelling programme (U11)
* **Guide:** a per-kind guide (event type, companies, independence, exposure, impact direction).
* **Labeller identity:** recorded on every label.
* **Double labelling:** a 10% sample is labelled twice to measure agreement.
* **Pace:** labelling starts now, in parallel with M1. At 30 per metric, the first measured scores need at least
  about 30 labelled events with impacts.
