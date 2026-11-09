# Market OHLCV collector: investigation of the "1,648 accepted, budget reached" runs

Status: **explained; no defect found in the accounting.** Evidence is from a SELECT-only production read on 2026-11-09 and from the code at `origin/main` (213e2f9).

## Observation
Runs 22, 23, 24, 35, 36 and 37 (and 12) each reported `items_accepted = 1648` with status `partial`, error "database budget reached".

## Test: did the runs write 1,648 distinct bars each?
`SELECT collection_run_id, COUNT(*) FROM market_bars WHERE collection_run_id IN (...) GROUP BY collection_run_id`:

| run | bars stored by run | first bar | last bar |
|---|---:|---|---|
| 11 | 1,692 | 2025-11-10 03:00 | 2026-11-06 11:48 |
| 12 | 1,648 | 2021-11-09 00:00 | 2026-11-06 11:00 |
| 22 | 1,648 | 2026-11-04 04:30 | 2026-11-06 11:48 |
| 23 | 1,648 | 2026-11-04 04:30 | 2026-11-06 11:48 |
| 24 | 1,648 | 2026-08-11 04:00 | 2026-11-06 11:48 |
| 35 | 1,648 | 2025-11-10 03:00 | 2026-11-06 11:00 |
| 36 | 1,648 | 2021-11-10 00:00 | 2026-11-06 11:00 |
| 37 | 1,648 | 2021-11-10 00:00 | 2026-11-06 00:00 |

`SELECT COUNT(*) FROM market_bars` = **13,228** = 1,692 + 7 × 1,648. The runs wrote distinct bars; the count is not a repeated figure.

## Cause
- `database/connection.py`: `DEFAULT_MAX_ROWS_WRITTEN = 5_000` per run (env `PSXNI_DB_MAX_ROWS_WRITTEN`).
- `collectors/market_ohlcv.py`: `FINALIZE_RESERVE_ROWS_WRITTEN = 50`; each bar costs three metered rows in practice (run 24: `rows_written` 4,947 ÷ 1,648 bars ≈ 3.0), so a run stops at roughly (5,000 − 50) ÷ 3 ≈ 1,650 bars.
- The stop is raised as `BudgetReserveReached` and recorded as `partial` with `budget_stopped`. Runs progress through different windows (the first/last bars vary), so this is continuation, not a loop.

## Minor finding (not a defect of accounting)
`ROWS_WRITTEN_PER_BAR = 4` is a conservative estimate; the observed cost is 3. This can leave up to a few bars per run unwritten. It does not cause duplicates or wrong counts. Changing it would be a tuning decision, not a bug fix.

## Consequence for coverage
Each run stores about 1,650 bars, so full daily history for five symbols and short intraday series will need several runs. Collection is complete only when the series reach their current bar; run status alone does not show that.

## Not performed
- No collector was run and no scheduled job was activated.
- No production write was made.
