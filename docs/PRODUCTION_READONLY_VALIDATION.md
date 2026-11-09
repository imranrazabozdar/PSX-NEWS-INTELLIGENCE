# Read-only production validation of SCS market data (M4/M5)

Status: **NOT PERFORMED. Blocked on the owner's read-only production credential.**

## Blocker (2026-11-09)
The credential was NOT supplied. The owner has clarified that the earlier secure request was **not** an owner
refusal: permission to request it has not been withdrawn, and the request will be made again. No production
connection was made, and no production read or write occurred. No other credential was used as a fallback.

## Target (verified from the repository and platform, names and hosts only)
* Database: `psx-news-intelligence`
* Host: `psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io` (matches `tests/turso_guard.py`)
* Symbols: OGDC, HBL, LUCK, ENGROH, PSO. Timeframes: 1m, 1h, 4h, 1d.

## Read-only query set
`validation/readonly_inspection_queries.sql` holds seven statements. The check run on the file found no writes or
DDL, no use of the `market_coverage` view (which groups over every bar), and no unbounded counts.

## Requirements to proceed
1. A database-specific token whose permissions are genuinely read-only. Verify it before use: the authoritative
   permission metadata, plus a harmless write attempt that the server must refuse.
2. Supplied only through the secure credential form. Never printed, logged, committed or placed in shell history.
3. No fallback to any write-capable credential. No other database.

## Procedure once authorised
1. Verify the token: permission metadata, then a refused write probe, then record the result (no token in logs).
2. Run the seven queries per symbol and timeframe, with the per-series bounded counts described in the query file.
3. Compare every stored bar against the official calendar (`config/psx_calendar.json`). Classify each gap as a
   non-trading day, a holiday, a provider outage, or a genuine anomaly.
4. Recalculate returns, volatility, drawdown and the 20-session liquidity measures independently from the stored
   closes and volumes, and compare with `engines/market_intel.py` and `engines/universe.py`.
5. Report every figure with its symbol, timeframe, sample size and observation period.

## Offline checks already completed (synthetic data)
* Macro point-in-time: revision timing, out-of-order rejection, never-released periods return None, null values
  rejected, provenance on every observation, older-period first release handled correctly.
* M5 safety: a price dated after the as-of date is not used; a missing price produces no multiple.
* Calendar: Friday 09:00–16:50, weekends and fixed holidays are non-trading.
