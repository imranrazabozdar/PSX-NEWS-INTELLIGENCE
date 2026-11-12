# Autonomous good-citizen fetcher: runbook (BUILT in cache-only mode; GATE: owner)

## What runs, and where
- Scheduled job: `.github/workflows/psx_fetch.yml`, every 30 minutes on weekdays (UTC). Each run is one tick
  (`python -m engines.autonomous_tick`). A tick decides whether to act and acts at most once.
- Scheduled runs use the **default branch**. The workflow takes effect only after the PR is merged.
- All state is in **psx-library** (`database/library/0001_fetch_state.sql`, PROPOSED). The state tables must be
  approved and applied before any tick can act. Until then every tick is a clean no-op.

## Consolidation (exactly one scheduler)
- Removed: nothing.
- Kept, and flagged for the owner's decision: `.github/workflows/scheduled-jobs.yml` runs the production collection
  every 6 hours with production secrets. It is not an Investify fetcher, and removing it would stop production
  collection. The owner must decide whether it stays alongside this job or is retired. It is not changed here.
- `investify-collect.yml` is dispatch-only (no schedule).

## State schema (psx-library)
- `fetch_control`: key, value. Keys: fetch_mode, kill_switch, breaker_tripped, cooldown_until_utc,
  global_last_request_utc, daily_day_pkt, daily_count, robots_txt, robots_fetched_utc, first_live_day.
- `fetch_progress`: resource_key, status, last_result, etag, last_modified, updated_utc.
- `fetch_log`: ts_utc, event, detail.

## Tick logic (fail-closed at every step)
1. Kill switch (library row or env) or fetch_mode not live: no-op.
2. Breaker tripped and still cooling: no-op.
3. Calendar: trading day; owner window Mon-Thu 09:32-15:30, Friday 09:32-12:00 and 14:32-15:30; first and last 15
   minutes trimmed; the Jumma break 12:00-14:32 excluded. Unreadable calendar: no-op.
4. Throttle: at least 15 minutes since the last request, across all resources.
5. Daily ceiling: day 1 of live running is 2; thereafter 12.
6. robots.txt: refreshed first when stale (it counts as the one request). Disallowed paths never fetched.
7. Pick the next pending resource: fundamentals first, core names first, then profile and competitors.
8. Write the throttle **before** the request. Then fetch once.
9. 200: store distilled fields only (never raw pages). 304: recorded no-op. 403, 429, 503 or network error: trip the
   breaker for a multi-hour cooldown (floor 4 hours) and stop.

## DRY tick result (tonight, no Investify traffic)
- `tests/test_autonomous_tick.py`: every guard (kill switch, cache-only, calendar, weekends and holidays, window
  trims, Jumma break, throttle, day-1 ceiling, breaker cooling, robots, progress skip), exactly one request when
  clear, the throttle written before the request, the breaker on 403, 429, 503 and network error, the 304 no-op,
  the 200 store path, the core-first order, the state round trip on the migration (in memory), the clean no-op
  without the library variables, the honest User-Agent, and the end-of-day log. All passed.

## Owner steps (in this order)
1. **Merge the PR** to the default branch, so the scheduled workflow exists there.
2. **GitHub repo secrets** (Settings, Secrets and variables, Actions, Secrets):
   `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `PSXNI_LIBRARY_TURSO_AUTH_TOKEN` (write-scoped to psx-library).
3. **GitHub repo variables** (same page, Variables tab):
   `PSXNI_CONTACT_EMAIL` (for the honest User-Agent; no contact means no live request),
   `PSXNI_FETCH_MODE` = `cache_only` to start.
4. **Approve and apply** the state migration `database/library/0001_fetch_state.sql` to psx-library, and make sure the
   operational tables the fundamentals store uses are present there too.
5. **Link test:** run the workflow manually (workflow_dispatch) with fetch_mode cache_only. The log shows
   "no-op" and the host, and confirms the library connection. Then run `python -m engines.library_db` if you want
   the probe round trip.
6. **Go live (owner decision):** set `PSXNI_FETCH_MODE` = `live` AND the library `fetch_control` row `fetch_mode` =
   `live`. The first in-window tick then fetches one resource (day-1 ceiling 2).
7. **Kill switch:** set the library `fetch_control` row `kill_switch` = `true`, or `PSXNI_FETCH_MODE` to anything
   other than `live`. Either halts all fetching at the next tick.

## Open items
- The global announcements parser still needs one in-window sample.
- Hours discrepancy: the owner's stated hours are 09:15-16:30 PKT; the owner-maintained calendar records Mon-Thu
  09:15-15:50 and Friday 09:00-16:50. The fetch window is the stricter owner window above.
- The Friday break is 12:00-14:32 (owner-approved). The policy's `friday_break_pkt` in config is still
  12:00-15:00 and is pending owner confirmation; the tick uses the owner window.
