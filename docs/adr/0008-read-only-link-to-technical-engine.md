# ADR-0008: Read-only link from the technical engine's signals to this project

* **Status:** ACCEPTED 2026-11-17 (signed by the owner in chat, see Owner sign-off). Schema discovery only until Schedule A is approved.
* **Date proposed:** 2026-11-17
* **Supersedes (in part, once signed):** the "Data exchange: none" and "Database" rows of ADR-0001, for the single interface below only.

## Context
The owner's technical engine (separate repository, database and app) already computes technical modules: Wyckoff
accumulation, volatility intelligence, chart and candlestick patterns, the FIRE engine, market regime and more.
This project holds news, results, announcements and (planned) prices. The owner wants the technical engine to keep
running exactly as it is, and this project to read its outputs so a company's news, price move and technical state
can be shown together and so "why did it move" can use technical evidence.

## Decision (applies only once signed)
One read-only, one-way link: this project may READ a small allowlist of the technical engine's output tables or views.
Nothing flows the other way.

| Area | Rule |
|---|---|
| Direction | Read only. This project never writes to, alters, or triggers anything in the technical engine (no DDL, no inserts, no workflow dispatch, no commits). |
| Credential | A NEW read-only database token the owner creates for this purpose (scoped to read, ideally to named tables or views). Stored here only as `PSXNI_TECH_LINK_URL` and `PSXNI_TECH_LINK_TOKEN`. No existing technical-engine secret is ever reused. The owner can revoke it at any time. |
| Allowlist | Only the tables or views the owner names in the Schedule below. Anything else is refused in code. The list is part of this ADR and changes only by amendment. |
| Access code | One module, `engines/technical_link.py`, using the same read-only wrapper as the council dry run (only SELECT/WITH pass). It fails closed if the database identity is not the one recorded in the Schedule or an allowlisted object is missing. |
| No code reuse | Nothing is imported, copied, vendored or executed from the technical engine's repository. This project reads its data only and does not open its repository. Indicator maths is not reimplemented from it. |
| Load limits | Per-run caps on rows read and requests, small daily cadence, off-peak. A failure here never affects the technical engine, and the technical engine's availability never blocks this project's other jobs. |
| What is stored | Dated facts in this project's own `research_fact`: symbol, scan date, module, signal or class, score, direction, stated components, plus the source name "Technical engine (read-only link)". Every row keeps the technical engine's own scan date so stale scans (for example a scan two weeks old) are never shown as current. |
| Language | Pattern, class and score only. Action words such as BUY, SELL or WAIT are never stored or displayed here. Scores are heuristics, not probabilities, and are labelled so. |
| Gaps | A symbol or module the engine does not cover stays unknown, never neutral or zero. |
| Rule check | `scripts/check_independence.py` gets exactly two narrow allowances, added in the same pull request that implements the link: the two secret names above and the single module name. Its other rules, and the base-branch guard, stay unchanged. |
| Review and expiry | Reviewed on 2027-02-17 or after any schema change in the technical engine. Ends on revocation of the token. |

## Schedule A: allowlisted objects (APPROVED by the owner 2026-11-17: "approve Schedule A as proposed")
Database identity: `psx-intelligence-v2-imranraza054.aws-ap-northeast-1.turso.io` (host only; found by schema discovery, 27 tables).

| Object | Meaning | Key columns | Use here |
|---|---|---|---|
| `stocks` | symbol list | symbol, name | map symbols to our companies |
| `daily_ohlc` | daily prices | symbol, trade_date, open, high, low, close, volume | the price series |
| `wyckoff_accumulation`, `wyckoff_scans` | Wyckoff accumulation | symbol, scan_date, accumulation_score, signal_type, component scores | technical signal |
| `chart_patterns` | chart patterns | symbol, pattern_type, signal_date, confidence_score | technical signal |
| `fire_events` | FIRE setups | symbol, event_date, event_type, fire_score | technical signal |
| `snapshots` | latest quote and sector | symbol, sector, ldcp, price, pct, vol | sector and the day's move |
| `backtest_pattern_stats`, `backtest_runs` | measured pattern win rates | pattern, horizon, n, win_rate, low_sample | reliability of each pattern |

Excluded on purpose: `predictions`, `runs`, `dss_history` (entry, stop, target and final-action language), the engine's own `news`,
intraday and candle tables (`intraday_bars`, `intraday_alert`, `market_candles`, `ohlcv_4h`), `analysis_cache`, `daily_reports`,
`config`, `sentiment`, `volume_baseline`, `indicator_accuracy` and the rest. No table for the volatility intelligence engine was
found; it may be inside `analysis_cache` and needs a separate discovery and approval.

## Consequences
* The two systems become coupled by one schema: a column rename in the technical engine breaks the link here. The link must fail visibly, and does.
* Reads cost the technical engine's Turso read quota. The caps above keep that small and the owner may lower them.
* The technical engine runs unchanged. The owner remains its only operator.
* If the owner prefers no live link, the file-export route (owner exports tables, a converter here loads them) needs no ADR and remains available.

## Implementation (after signing, one phase, one pull request)
1. Owner completes Schedule A and creates the read-only token and secrets.
2. Dry run: read-only identity check, row counts and sample rows printed, nothing stored.
3. Owner reviews, then the converter loads dated facts with source provenance.
4. Tests: allowlist enforcement, read-only enforcement, identity mismatch fails closed, stale-scan labelling, no action words, caps.

## Owner sign-off
- [x] 2026-11-17, in the session chat, the owner wrote: "I sign ADR-0008, schema discovery first" and confirmed that the
  secrets `PSXNI_TECH_LINK_URL` and `PSXNI_TECH_LINK_TOKEN` were added. This authorises the read-only link described here.
  Step 1 is schema discovery only (table and column names, nothing stored). Data tables may be read only after the owner approves
  the list in Schedule A; until then the allowlist in `engines/technical_link.py` is empty and the code refuses data reads.
