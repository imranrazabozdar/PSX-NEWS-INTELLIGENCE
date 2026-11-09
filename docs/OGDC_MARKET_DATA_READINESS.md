# OGDC market-data inventory and repricing readiness (Part 10)

Status: **inventory complete (SELECT-only, live production read on 2026-11-09)**. Event study and benchmark-adjusted analysis: **insufficient_data**.

## 1. Access and method

- Host: psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io (owner-approved read-only token, supplied through the secure form on 2026-11-09).
- Only SELECT statements were run: schema listing, bounded per-series MIN/MAX/COUNT on `market_bars` (indexed by symbol), collector-run history, correction counts.
- **Not run:** the write-permission probe required by `docs/PRODUCTION_READONLY_VALIDATION.md` (it would attempt a production write). Token permissions are therefore **not** independently verified; the owner should confirm the token is read-only.
- **Not run:** Q4 of `validation/readonly_inspection_queries.sql` (corporate actions) — the table does not exist (see section 3).
- No writes, migrations, collector runs or deployments were made.

## 2. Market-data inventory (source `scs_chart`)

Symbols present: ENGROH, HBL, LUCK, OGDC, PSO. **No KSE-100 or other index price series exists in `market_bars`.** (`index_memberships` has 30 rows; it is membership data, not prices.)

| Symbol | 1d bars | 1d first | 1d last | 4h bars | 4h first–last | 1h bars | 1h first–last | 1m bars | 1m first–last |
|---|---:|---|---|---:|---|---:|---|---:|---|
| OGDC | 1,239 | 2021-11-09 | 2026-11-06 | 541 | 2025-11-10 → 2026-11-06 | 428 | 2026-08-11 → 2026-11-06 | 1,064 | 2026-11-04 → 2026-11-06 |
| HBL | 1,238 | 2021-11-10 | 2026-11-06 | 541 | 2025-11-10 → 2026-11-06 | 428 | 2026-08-11 → 2026-11-06 | 1,043 | 2026-11-04 → 2026-11-06 |
| LUCK | **635** | 2021-11-10 | **2024-06-04** | 541 | 2025-11-10 → 2026-11-06 | 428 | 2026-08-11 → 2026-11-06 | 1,058 | 2026-11-04 → 2026-11-06 |
| ENGROH | **0** | — | — | 541 | 2025-11-10 → 2026-11-06 | 426 | 2026-08-11 → 2026-11-06 | 1,056 | 2026-11-04 → 2026-11-06 |
| PSO | **0** | — | — | 541 | 2025-11-10 → 2026-11-06 | 426 | 2026-08-11 → 2026-11-06 | 1,054 | 2026-11-04 → 2026-11-06 |

Findings:
- OGDC daily history is continuous over five years (1,239 sessions). It matches the saved extract exactly (same count and endpoints).
- **LUCK daily series stops at 2024-06-04**, about 2.4 years before the latest session. The daily series is stale.
- **ENGROH and PSO have no daily bars at all.**
- Intraday history is short: 1m covers about three sessions (4–6 Nov 2026); 1h from 11 Aug 2026; 4h from 10 Nov 2025. No event window before Aug 2026 has intraday coverage.
- Corporate-action-dependent conclusions are restricted for all symbols (section 3).

## 3. Corporate actions and price adjustment

- `corporate_actions` **does not exist** in production (SQLite error on query; schema listing has no such table).
- Therefore no ex-date, bonus, rights or cash-dividend adjustment factors can be verified. Raw closes cannot be distinguished from adjusted closes.
- No corrections exist for OGDC (`market_bar_corrections` count = 0), so no revised bar history is recorded either.
- Conclusion: **prices cannot be validated as corporate-action-adjusted.** Returns over any window that contains a dividend, bonus or split are not reliable.

## 4. Collection health

Collector runs for `scs_chart` (last 8 of 12 shown; newest first):

| run | started (UTC) | status | items fetched | items accepted | error |
|---|---|---|---:|---:|---|
| 37 | 2026-11-09 06:33 | partial | 2,297 | 1,648 | database budget reached |
| 36 | 2026-11-09 06:32 | partial | 2,702 | 1,648 | database budget reached |
| 35 | 2026-11-09 06:31 | partial | 2,016 | 1,648 | database budget reached |
| 24 | 2026-11-08 22:08 | partial | 1,722 | 1,648 | database budget reached |
| 23 | 2026-11-08 22:07 | partial | 2,505 | 1,648 | database budget reached |
| 22 | 2026-11-08 22:07 | partial | 2,041 | 1,648 | database budget reached |
| 12 | 2026-11-08 13:26 | partial | 2,632 | 1,648 | database budget reached |
| 11 | 2026-11-08 12:46 | failed | 0 | 0 | owner-approved correction; end time unknown |

Findings:
- Every run since 8 Nov 2026 is **partial**: the storage budget was reached before the run finished.
- **Accepted count is 1,648 in every run**, regardless of items fetched. This is an identical figure across runs and should be investigated; it suggests repeated acceptance of the same batch rather than new data. Not resolved.
- Recent collection therefore cannot be assumed complete.

## 5. Readiness by question

| Question | Answer |
|---|---|
| Can OGDC prices be adjusted for corporate actions? | No (no corporate-action table). |
| KSE-100 benchmark available? | No. |
| Event study possible? | No (no adjusted prices, no benchmark). |
| Daily returns / drawdowns | Raw close-to-close only; not total returns. |
| History for event windows | 5 years daily for OGDC/HBL only; intraday too short for most windows. |
| Announcement timestamps aligned to sessions? | Not testable: no announcement table in the inventory. |
| Volume and volatility changes | Computable from daily bars, unadjusted; not assessed here. |

## 6. Event-level results

Not computed. For every listed OGDC event (annual results, quarterly results, dividend announcements, tax disclosures, receivables and circular-debt developments, production and exploration announcements, policy developments): **insufficient_data**.

## 7. Owner actions

1. Confirm the token is read-only (run the permission check the owner controls; a write probe was not run).
2. Supply or restore the corporate-actions data (ex-dates, ratios, types) for OGDC, HBL, LUCK, ENGROH and PSO.
3. Investigate why LUCK daily stopped in June 2024, and why ENGROH and PSO have no daily bars.
4. Investigate the repeated `accepted = 1,648` and the budget-limited partial runs before any further collection.
5. Supply a KSE-100 benchmark source (authorised; not scraped).
