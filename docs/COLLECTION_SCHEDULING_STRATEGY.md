# Delayed, scheduled collection strategy

Design proposal only (2026-11-07). Nothing is scheduled or activated by this document.

**Owner preference:**
- delayed batch collection, not real time;
- roughly 15-minute processing during PSX market hours (5–15 minutes where feasible);
- a comprehensive after-close batch;
- overnight reconciliation.

**This is a goal, not an SLA.**
- **Default:** 15-minute batches during market hours.
- **5-minute intervals:** only for a source where that is independently justified, permitted by its
  terms, and operationally reliable.
- Each source runs only at its permitted interval and only once approved (lifecycle ACTIVE). **No
  source is approved or ACTIVE today.**
- GitHub Actions start times are **not** processing or publication latency. **No 5–15 minute SLA is
  offered.**

## 1. Windows (Pakistan time, PKT = UTC+5)
PSX trading hours must be confirmed from PSX's official calendar before scheduling. They are
**UNCONFIRMED** here, so the windows are configuration, not code.

| Window | Proposed PKT | Purpose |
|---|---|---|
| Market hours | trading session (e.g. ~09:15–15:30 Mon–Fri; Friday break; **confirm**) | 15-minute incremental batch |
| After close | ~1 hour after the session ends | Comprehensive daily batch |
| Overnight | ~01:00–05:00 | Reconciliation and maintenance |
| Weekends and holidays | — | No routine polling. One daily check only for a source or event that justifies it (for example, a scheduled policy announcement). |

## 2. Run steps
**Market-hours batch (every 15 minutes):**
1. Select due sources: `due_sources()`, which picks ACTIVE sources whose per-source
   `collection_frequency_minutes` has elapsed. There is never one universal interval.
2. Make conditional requests (ETag / If-Modified-Since). A 304 response costs one request and **no
   database writes**.
3. Store new or changed items only. Canonical URL, GUID and content hash give deduplication, and
   versions are kept. Source publication time and retrieval time are stored separately (already in
   Phase 2).
4. Run a relevance pre-filter (no LLM). Only relevant new items go to extraction, which is cached by
   prompt, model and input hash (Phase 3) and capped by the daily cost limit and kill switch.
5. Run clustering, corroboration and exposure mapping (Phase 4). Write candidates only when something
   changed (idempotent).
6. Route uncertain, high-impact, rumour and single-source items to human review.

**After-close batch:**
- Rescan the same sources at a wider window (`since_utc` = session open) to catch missed items.
- Process document sources (official PDFs, metadata only) and any manual imports.
- Reconcile duplicates and publication times.
- Refresh macro and energy series via APIs (EIA, World Bank) at their own intervals.
- Write a daily intelligence snapshot (read-only views; no new paid infrastructure).

**Overnight batch:**
- Cross-day deduplication and reconciliation, and evidence revalidation (`revalidate()`, Phase 4).
- Retries only for transient failures (5xx, timeouts), bounded by the existing retry and backoff
  rules. Never retry 401, 403 or robots refusals.
- Source-health report (`source_health` view; failure counters).
- Pending extraction jobs, within the LLM budget.
- Turso quota summary from the usage meter.

## 2b. Scheduling reliability and recovery
| Concern | Behaviour | Mitigation |
|---|---|---|
| Delayed workflow starts | GitHub documents that scheduled runs may be delayed under high load, especially at the top of the hour | Off-peak minute offsets; publication time and retrieval time are stored separately, so the delay is measured, not hidden |
| Failed or skipped runs | A scheduled run can be dropped or fail (network, provider 5xx, runner) | Each run is idempotent; the next run picks up via checkpoints and conditional requests; failures are counted per source |
| Overlapping runs | A slow run could overlap the next schedule | One `concurrency` group per window with `cancel-in-progress: false`; a new run waits or is skipped, never runs twice in parallel |
| Recovery | Items missed during the day | The after-close batch rescans from session open (`since_utc`); the overnight batch reconciles across days |
| Source-specific intervals | Sources differ in update cadence and permission | `collection_frequency_minutes` per source; `due_sources()` selects only the due ones; there is no universal interval |
| Inactivity | Public-repository schedules are disabled after 60 days without repository activity | Owner-visible health report; re-enable procedure documented in operations (Phase 7) |
| Measured latency | The time from publication to processing | Reported per source from stored timestamps; this is an observation, not a guarantee |

## 3. Infrastructure fit (existing components)
| Component | Fit | Notes |
|---|---|---|
| GitHub Actions `schedule` | Yes, with caveats | **Caveats from GitHub's documentation:** the shortest interval is 5 minutes; scheduled runs can be **delayed during periods of high load** (the start of each hour is busiest); they run on the default branch only; and in public repositories they are **disabled after 60 days without repository activity**. Use minute offsets (e.g. `7,22,37,52`) rather than `:00`. Standard runners are free for public repositories. Expect occasional delays or skipped runs, which is why the after-close batch re-scans. |
| Concurrency | Yes | One `concurrency` group per window prevents overlapping runs (already used by `scheduled-jobs.yml`). |
| Turso (free tier) | Yes | Per-run budgets (`PSXNI_DB_MAX_ROWS_READ/WRITTEN/REQUESTS`) and the kill switch already exist. Conditional requests and skip-unchanged keep writes small. **Migrations 0006–0008 must first be verified on a disposable Turso database, then approved.** |
| Collector framework | Yes | `authorise()` gate, robots, per-host rate limit, retries, checkpoints, `due_sources()` |
| Phase 3 extraction | Yes | Pre-filter and cache; live LLM **not connected** (needs the D2 decision). Until then, extraction can only be recorded as `llm_unavailable`. |
| Phase 4 exposure mapping | Yes | Idempotent re-runs; `exposure_candidates_current` view for consumers |

**Cost:** no new paid infrastructure. At a 15-minute market cadence a trading day has about
25 market runs, 1 after-close run and 1 overnight run. There is no routine weekend polling. Each run
is short, and standard runner minutes are free for public repositories.

**Production readiness:** migrations 0006–0008 are blocked in production until they are verified on
a disposable Turso database and separately approved.

## 4. Efficiency rules
- No continuous polling: only scheduled, short-lived jobs.
- Conditional GETs, and a per-source `collection_frequency_minutes`.
- Never re-download archives: checkpoints and `since_utc`, with bounded backfills as separate,
  separately approved jobs.
- Database writes only for new or changed items (skip-unchanged is already implemented).
- LLM calls only for new, relevant, uncached items, under the daily cost cap.
- Failure isolation: one source's failure never stops the others; failures are counted per source.

## 5. Proposed per-source schedule (after approval only)
| Group | Market hours | After close | Overnight |
|---|---|---|---|
| Pakistani news RSS (Dawn, BR, Tribune) — **if rights are confirmed** | every 15 min | full rescan | dedup and reconcile |
| PBS RSS — if rights are confirmed | every 60 min | daily | — |
| EIA API | — | daily | weekly series refresh |
| World Bank / IMF APIs | — | — | weekly or monthly |
| Official PDFs (OGRA, NEPRA, FBR) where permitted | — | daily metadata check | — |
| YouTube Data API (7 channels) | hourly (quota) | daily | — |
| Manual imports | — | processed in this batch | retries |
| Licensed provider webhook (if contracted) | push (no polling) | REST reconciliation | — |
| Licensed market data, EOD (if contracted) | — | daily EOD pull | adjusted-price reconciliation |
