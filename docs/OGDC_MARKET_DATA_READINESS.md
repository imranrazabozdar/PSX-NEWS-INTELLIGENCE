# OGDC market-data inventory and repricing readiness (Part 10, partial)

Status: **production inspection blocked**. The owner declined the secure request for the read-only production token on this run ("Denied by user"). No production connection was made in this batch. The only evidence is a previously saved extract, below.

## 1. Evidence available

Scratch file: `prod_extract.json` (scratchpad of the earlier read-only check; 1,239 OGDC daily bars from source `scs_chart`, retrieved 2026-11-08T13:26:45Z). Not re-run and not current beyond 2026-11-06.

| Item | Finding |
|---|---|
| Daily bars | 1,239, session dates 2021-11-09 to 2026-11-06 |
| Intraday | Not in the extract; not assessed |
| Gaps > 4 calendar days | 11, mostly around Eid/holiday periods; not yet checked against `config/psx_calendar.json` |
| Moves above 15% in one day | None found; not sufficient to prove price adjustment |
| Corporate-actions table | **Absent**: SQLite error "no such table: corporate_actions" in the extract. Corporate-action adjustment cannot be verified |
| Benchmark (KSE-100) | Not in the extract; not assessed |
| Volume | Present per bar; not yet tested for consistency |
| Ingestion run 24 (`market_ohlcv`, 2026-11-08) | **Status partial**: 1,722 fetched, 1,648 accepted; stopped by "database budget reached" to keep the finalisation reserve. Collection was incomplete at the time of the extract |
| Identifier | PSX ticker OGDC mapped to `cmp-ogdc`, verified 2026-11-07 |

## 2. Assessment against the Part 10 questions

- **Can OGDC prices be adjusted for corporate actions?** No. The corporate-actions table is absent in the inspected extract, so adjustment factors cannot be validated. Dividends and bonus issues therefore cannot be distinguished from price moves.
- **KSE-100 benchmark available?** Not established. Benchmark-adjusted returns are **insufficient_data**.
- **Can an event study be performed reliably?** No. Without adjusted prices and a benchmark, abnormal returns and event windows are not computed.
- **Daily returns, drawdowns, volatility:** raw close-to-close returns could be computed from the extract, but they are not corporate-action adjusted and must not be presented as total returns.
- **Announcement timestamps vs trading sessions:** not tested. The extract has session dates but no announcement timestamps.

## 3. Event-level results

None computed. Event-day returns, 1/5/20/60-day post-event returns, volume and volatility changes, and delayed-repricing tests are **insufficient_data** for every event listed in the batch (annual results, quarterly results, dividend announcements, tax disclosures, receivables and circular-debt developments, production and exploration announcements, policy developments).

## 4. Owner action required

1. Supply a database-scoped read-only token for the production host, through the secure form, to run the seven queries in `validation/readonly_inspection_queries.sql`.
2. Confirm whether the corporate-actions table exists in production under another name, or supply a verified corporate-action record (dates, types, ratios) for OGDC.
3. Confirm the collection budget situation for run 24 and whether the remaining OGDC bars were stored.
4. Supply or authorise a KSE-100 benchmark source.
