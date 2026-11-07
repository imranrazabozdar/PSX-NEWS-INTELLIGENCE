# Delayed, scheduled collection strategy

Design proposal only (2026-11-07). Nothing is scheduled or activated by this document.

**Owner preference:**
- delayed batch collection, not real time;
- roughly 15-minute processing during PSX market hours (5–15 minutes where feasible);
- a comprehensive after-close batch;
- overnight reconciliation.

**This is a goal, not an SLA.** Each source runs only at its permitted interval and only once
approved (lifecycle ACTIVE).

## 1. Windows (Pakistan time, PKT = UTC+5)
PSX trading hours must be confirmed from PSX's official calendar before scheduling. They are
**UNCONFIRMED** here, so the windows are configuration, not code.

| Window | Proposed PKT | Purpose |
|---|---|---|
| Market hours | trading session (e.g. ~09:15–15:30 Mon–Fri; Friday break; **confirm**) | 15-minute incremental batch |
| After close | ~1 hour after the session ends | Comprehensive daily batch |
| Overnight | ~01:00–05:00 | Reconciliation and maintenance |
| Weekends and holidays | — | Hourly or daily low-frequency checks only |

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

## 3. Infrastructure fit (existing components)
| Component | Fit | Notes |
|---|---|---|
| GitHub Actions `schedule` | Yes, with caveats | **Caveats from GitHub's documentation:** the shortest interval is 5 minutes; scheduled runs can be **delayed during periods of high load** (the start of each hour is busiest); they run on the default branch only; and in public repositories they are **disabled after 60 days without repository activity**. Use minute offsets (e.g. `7,22,37,52`) rather than `:00`. Standard runners are free for public repositories. Expect occasional delays or skipped runs, which is why the after-close batch re-scans. |
| Concurrency | Yes | One `concurrency` group per window prevents overlapping runs (already used by `scheduled-jobs.yml`). |
| Turso (free tier) | Yes | Per-run budgets (`PSXNI_DB_MAX_ROWS_READ/WRITTEN/REQUESTS`) and the kill switch already exist. Conditional requests and skip-unchanged keep writes small. **Migrations 0006–0008 must first be verified on a disposable Turso database, then approved.** |
| Collector framework | Yes | `authorise()` gate, robots, per-host rate limit, retries, checkpoints, `due_sources()` |
| Phase 3 extraction | Yes | Pre-filter and cache; live LLM **not connected** (needs the D2 decision). Until then, extraction can only be recorded as `llm_unavailable`. |
| Phase 4 exposure mapping | Yes | Idempotent re-runs; `exposure_candidates_current` view for consumers |

**Cost:** no new paid infrastructure. Runs per day at a 15-minute market cadence are about
25 market + 1 after-close + 1 overnight + weekend hourly checks. Each run stays well inside public
runner limits; the minutes are free for public repositories.

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
| Pakistani news RSS (Dawn, BR, Tribune) | every 15 min | full rescan | dedup and reconcile |
| PBS RSS | every 60 min | daily | — |
| EIA API | — | daily | weekly series refresh |
| World Bank / IMF APIs | — | — | weekly or monthly |
| Official PDFs (OGRA, NEPRA, FBR) where permitted | — | daily metadata check | — |
| YouTube Data API (7 channels) | hourly (quota) | daily | — |
| Manual imports | — | processed in this batch | retries |
| Licensed provider webhook (if contracted) | push (no polling) | REST reconciliation | — |
