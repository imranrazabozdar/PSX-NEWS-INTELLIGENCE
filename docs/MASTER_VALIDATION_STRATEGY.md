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

## 5. Labelling programme (U10)
* **Guide:** a per-kind guide (event type, companies, independence, exposure, impact direction).
* **Labeller identity:** recorded on every label.
* **Double labelling:** a 10% sample is labelled twice to measure agreement.
* **Pace:** labelling starts now, in parallel with M1. At 30 per metric, the first measured scores need at least
  about 30 labelled events with impacts.

## Update (OGDC pilot finalisation): real-document validation rules

- Figures are compared only with values read from the original page image. The reader's own output is never the ground truth.
- Every identity check reports its own result: pass, fail, or `not_checkable` when a component is missing. A missing component is never treated as zero.
- Consolidated and unconsolidated reports are checked independently. A difference between them is recorded, not assumed immaterial.
- M3 ratios are verified by hand from the stored inputs. Each result states its formula, its period basis (annualised or day-scaled), and whether it is an approximation.
- OCR figures are validated only against manually verified truth and are never promoted automatically.
- Synthetic fixtures are never counted as real-world accuracy.


## Update (2026-11-09): sector validation status

- Each sector's validation status is in `docs/SECTOR_TEST_DATA_SPEC.md`. Only the OGDC oil and gas pilot has real documents.
- Synthetic tests check logic and are never reported as real accuracy. Real-data claims require manually verified figures.
- Ratio applicability is checked by tests against the matrix (banks, insurers and industrials).
