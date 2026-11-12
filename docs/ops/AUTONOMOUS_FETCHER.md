# Autonomous good-citizen fetcher: runbook (live by default; stop controls below)

## What runs, and where
- Scheduled job: `.github/workflows/psx_fetch.yml`, every 30 minutes on weekdays (UTC). Each run is one tick
  (`python -m engines.autonomous_tick`). A tick decides whether to act and acts at most once.
- Scheduled runs use the **default branch**. The workflow takes effect only after the PR is merged.
- All state is in **psx-library** (`database/library/0001_fetch_state.sql`, PROPOSED). The fetcher is live by
  default, with no mode toggle. Every tick first checks that psx-library answers, and it stops before any Investify
  request if it does not. It also stops if the state tables are missing, which is the case until the owner
  approves and applies the migration. Until then every tick is a clean no-op.

## Consolidation (exactly one scheduler)
- Removed: nothing.
- Kept, and flagged for the owner's decision: `.github/workflows/scheduled-jobs.yml` runs the production collection
  every 6 hours with production secrets. It is not an Investify fetcher, and removing it would stop production
  collection. The owner must decide whether it stays alongside this job or is retired. It is not changed here.
- `investify-collect.yml` is dispatch-only (no schedule).

## State schema (psx-library)
- `fetch_control`: key, value. Keys: kill_switch, breaker_tripped, cooldown_until_utc,
  global_last_request_utc, daily_day_pkt, daily_count, robots_txt, robots_fetched_utc, first_live_day.
- `fetch_progress`: resource_key, status, last_result, etag, last_modified, updated_utc.
- `fetch_log`: ts_utc, event, detail.

## Tick logic (fail-closed at every step)
0. Library first: psx-library must answer a SELECT 1 and the state tables must exist. Otherwise: no-op, and no
   Investify request is made.
1. Breaker tripped and still cooling: no-op.
1a. Kill switch (library row `kill_switch` = true, or env `PSXNI_INVESTIFY_KILL` / `PSXNI_KILL_SWITCH` = true): no-op.
3. Calendar: an official OPEN session, read from `config/psx_calendar.json` (`open_sessions`). Mon-Thu 09:32-15:30;
   Friday 09:17-12:00 and 14:32-16:30. The Jumma break (Friday 12:00-14:32) is no trading. Close is exclusive. Weekends,
   holidays and an unreadable calendar: no-op. The policy's `friday_break_pkt` must agree with the calendar (tested).
4. Throttle: at least 15 minutes since the last request, across all resources.
5. Daily ceiling: day 1 of live running is 2; thereafter 12.
6. robots.txt: refreshed first when stale (it counts as the one request). Disallowed paths never fetched.
7. Pick the next pending resource: fundamentals first, core names first, then profile and competitors.
8. Write the throttle **before** the request. Then fetch once.
9. 200: store distilled fields only (never raw pages). 304: recorded no-op. 403, 429, 503 or network error: trip the
   breaker for a multi-hour cooldown (floor 4 hours) and stop.

## DRY tick result (tonight, no Investify traffic)
- `tests/test_autonomous_tick.py`: every guard (kill switch, breaker cooldown, library unreachable before any
  request, calendar, weekends and holidays, window
  trims, Jumma break, throttle, day-1 ceiling, breaker cooling, robots, progress skip), exactly one request when
  clear, the throttle written before the request, the breaker on 403, 429, 503 and network error, the 304 no-op,
  the 200 store path, the core-first order, the state round trip on the migration (in memory), the clean no-op
  without the library variables, the honest User-Agent, and the end-of-day log. All passed.

## Self-test (before merge, then on demand)
- `.github/workflows/library-selftest.yml`: runs `python -m engines.library_db` (target guard, SELECT 1, probe round trip)
  with the library secrets. Turso only; no Investify. On a green self-test it then applies the approved state migration
  (`scripts/apply_library_migration.py`: psx-library only, `CREATE TABLE IF NOT EXISTS` only).
- The temporary push trigger on this branch is removed after the merge; the workflow_dispatch trigger stays.

## Owner steps (in this order)
1. **Merge the PR** to the default branch, so the scheduled workflow exists there.
2. **GitHub repo secrets** (Settings, Secrets and variables, Actions, Secrets):
   `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `PSXNI_LIBRARY_TURSO_AUTH_TOKEN` (write-scoped to psx-library).
3. **GitHub repo variables** (same page, Variables tab):
   `PSXNI_CONTACT_EMAIL` (for the honest User-Agent; no contact means no request is made).
4. **Approve and apply** the state migration `database/library/0001_fetch_state.sql` to psx-library, and make sure the
   operational tables the fundamentals store uses are present there too.
5. **Link test (self-test):** run `python -m engines.library_db` in the Actions workflow_dispatch with the library
   secrets. It must print the connection OK line. If authentication fails, the error is printed and nothing runs.
6. **Live:** there is no mode switch. Once the migration is applied, the next in-window tick fetches one resource
   (day-1 ceiling 2, then 12 a day).

## Stop controls
- **Automatic:** a 403, 429, 503 or network error trips the breaker for a multi-hour cooldown (at least 4 hours),
  and the fetcher makes no requests until it clears.
- **Manual pause:** disable the "PSX good-citizen fetcher (autonomous)" workflow in the GitHub Actions UI
  (Actions, the workflow, the ... menu, Disable workflow). Re-enable it the same way.
- **Manual halt in the library:** set `fetch_control` row `kill_switch` = `true`, or the env kill flags above.

## Open items
- The global announcements parser still needs one in-window sample.
- Grading hours (`regular_hours`, pre-open to post-close, used by market-data quality checks) are unchanged; only
  fetching uses `open_sessions`. Owner to confirm that split.
