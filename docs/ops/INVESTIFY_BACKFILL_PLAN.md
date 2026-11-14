# Investify live backfill plan (GATE: owner approval required before tomorrow's start)

Status: PLAN ONLY. Nothing has started. Default remains cache-only (`config/investify_good_citizen.json`).

## Gate results (tonight, no Investify traffic)

| Item | Result |
|---|---|
| Turso library secret set in this environment | NO. `PSXNI_TURSO_*` and `PSXNI_LIBRARY_TURSO_*` are unset. Owner must set the library URL and token through the secure secret flow. Name needed: `PSXNI_LIBRARY_TURSO_DATABASE_URL` and `PSXNI_LIBRARY_TURSO_AUTH_TOKEN` (names proposed; owner to confirm). Never paste them in chat |
| Target guard (`engines/investify_library.py`) | Implemented and tested: refuses a missing URL, production and data-capture names, and any URL that does not name the library. Returns the name only |
| Live link test (write one record, read it back, delete it) | NOT RUN. Blocked by the missing secret. Also blocked by design: `source_items` is append-only, so the test row cannot be deleted. A safe test needs a non-append-only probe table, which requires a migration the owner must approve |
| Synthetic end-to-end dry run | PASSED on a disposable in-memory database: fixture parsed (4 metric cards), distilled, stored, read back, verified; symbol `ZZTEST`. Not written to Turso (no secret) |
| EOD progress report | IMPLEMENTED and TESTED on synthetic data (see sample below) |
| Live Investify request tonight | NONE. The gate refuses outside the quiet window; tested with a permissive policy at 17:00 PKT |

## EOD report (sample, synthetic data)

```
Investify EOD, 2026-11-10 (Pakistan time). Private research use; attribution: investify.pk.
Backfill: library coverage 60.0% (3 of 5); pass 1 breadth 40.0%; pass 2 depth 20.0%.
Announcements today: 1. Financials 1
  ! AAA [Financials] Financial Result For The Quarter Ended Synthetic 30, 2026
Footprint: 6 requests today, 6 this week, 304 share 0.0%, errors 0.
  WARN: 6 of 8 daily requests today
Private research use. Announcements are the stored records as of their fetch time; they are not live.
```

## Live backfill plan (for approval)

- **Scope:** 108 watchlist companies.
- **Order, fundamentals first, core names first:**
  1. one global announcements page per trading day (covers every watchlist company in one request);
  2. fundamentals first fill for companies with a financial result (core names first: MEBL, LUCK, OGDC, FFC, APL, then the rest);
  3. profile, once per company;
  4. competitors, once per company.
- **Requests needed:** about 216 one-time (profile and competitors), plus up to 108 first fills, plus one announcements page a day.
- **Daily budget:** the policy's daily ceiling is 12. One announcements page takes one, so 11 remain for backfill.
- **Window:** quiet mid-session, 10:00 to 15:30 PKT. At the 15-minute gap that allows at most 22 requests a day, so the daily ceiling binds. Requests are spread across the window with jitter.
- **Estimated duration:** about 30 trading days (about six weeks), depending on how many companies have a financial result.
- **Resumable and pausable:** progress is kept in the state file and the Turso library. Backfill yields to pending event triggers and keeps a daily reserve of 2.

## Blockers to clear before the live start

1. **Global announcements page parser.** The earlier global page fetch parsed 0 watchlist announcements with the legacy parser. The company page is structured; the global page needs the same structured parser, which needs one sample inside the trading window.
2. **Turso library secret** (above), set by the owner.
3. **Probe table** for the Turso link test (append-only constraint), approved by the owner.


## Second gate pass: target is psx-library (owner-confirmed)

**Target:** `psx-library-turso202601` (`libsql://psx-library-turso202601.aws-us-east-1.turso.io`), the dedicated library
database. Separate from psx-data-capture (production and ingestion) and psx-data-archival-test (rehearsal). The backfill
writes only here.

**Secrets (owner action, through the secure secret flow, never in chat):** `PSXNI_LIBRARY_TURSO_DATABASE_URL` and
`PSXNI_LIBRARY_TURSO_AUTH_TOKEN` (a token generated in the Turso dashboard for psx-library). **Status: NOT SET in this
environment.** The link test cannot run until both are set. Per the instruction, no other database is used as a fallback.

**Target guard (`engines/investify_library.py`):** the host must contain `psx-library`. The guard refuses any URL that
contains `data-capture`, `data-archival`, `archival`, `archive`, `production`, `prod` or `capture`. Tested:
- accepts `psx-library-turso202601`, returns only the name;
- refuses `psx-data-capture`, `psx-data-archival-test`, `psx-archive`, `psx-prod`, `psx-production`, and a library name
  with a production marker;
- refuses an unnamed or missing URL.

**Link test (approved probe table `library_probe`):** writes one synthetic record (under 1 KB, `source="test"`), reads it
back, and deletes it in a finally block. Tested on an in-memory copy. The live run is skipped until the secrets are set.

**Calendar and fetch window (no-fetch-when-uncertain):** a fetch is allowed only on a trading day, inside the recorded
hours (`config/psx_calendar.json`), and outside the Friday break. Refuses on weekends, holidays, unrecorded hours, an
unreadable calendar, and the Friday break.
- **Discrepancy to resolve:** the owner's stated hours are 09:15 to 16:30 PKT. The calendar records Mon to Thu 09:15 to
  15:50 and Friday 09:00 to 16:50, from the PSX Trading Hours page. The calendar is owner-maintained, so it was not changed.
- **Jumma break (pending):** no official break time is recorded. The policy refuses Friday 12:00 to 15:00 PKT until the
  owner confirms the official window.

**Plan, unchanged:** 108 companies, fundamentals first and core names first; daily ceiling 12; one global announcements
page per trading day; resumable; cache-only until approved.

**Blockers before the live start:** the library secrets (owner); the global announcements parser (needs one in-window
sample); the Jumma break window (owner); the 15:50 versus 16:30 close discrepancy (owner).
