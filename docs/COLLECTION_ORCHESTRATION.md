# Collection orchestration: architecture and roadmap

Status: Stage 1 (analysis) and Stage 2 (core orchestration), with the Stage 3 priority order, are
IMPLEMENTED and TESTED offline. Stages 4–5 are NOT STARTED. Nothing here has run against production.

## 1. Gap analysis against the requirements (baseline `55fbabe`)

| Requirement | Baseline | Gap |
|---|---|---|
| Incremental fetch from last stored bar, overlap re-check | yes (`_last_bar`, `_window`) | keep |
| Append-only bars, explicit corrections | yes (0010 triggers, `market_bar_corrections`) | keep |
| Per-run write budget with finalisation reserve | yes (PR #25) | keep; 5,000 rows unchanged |
| Per-series failure isolation | yes | keep |
| Overlap protection | GitHub `concurrency` group only | **no database lease**: a local run, a second workflow or a re-run could write at the same time |
| Abandoned runs | stay `running` forever (production run 11) | **no recovery** |
| Continuation after a budget stop | waits for the next 6-hourly cron | **missing** |
| Backoff after failures | none | **missing** |
| Trigger origin / per-run usage | not recorded | **missing** |
| Backfill priority | symbol by symbol (OGDC all timeframes, then HBL…) | **1-minute history of later symbols expires while earlier symbols' daily history is fetched** |
| External dispatch | not supported | Stage 4 |
| Session-aware scheduling, completeness grading, cheap coverage, ops view | not present | Stage 5 |

**Schema:** no change is needed. `collector_runs.quota_usage_json` (JSON, existing column) carries the
trigger origin, pass, reason, budget-stop flag and usage; `collector_runs.status` and `sources` health
columns carry the rest. Gap and completeness detection can be computed from `market_bars` with the
existing primary-key index.

## 2. Target architecture: responsibilities

```
trigger (GitHub cron fallback | external workflow_dispatch | manual)
  -> scheduled-jobs.yml (concurrency group: one job at a time)
     -> collectors.market_ohlcv --due
        -> market_orchestrator.orchestrate        coordination only
             recover_abandoned   running > lease  -> failed ("abandoned")
             decide              ACTIVE? daily cap? continuation? interval x backoff?
             collect_market      lease claim (atomic INSERT .. WHERE NOT EXISTS running)
                                 series in priority order, incremental, budget reserve
                                 finalise: status + quota_usage_json + source health
             loop                fresh connection per pass (same-size budget), stop on
                                 complete / failed / no progress / busy / max passes / cap
```

* **Run states:** `succeeded` (all series done), `partial` with `budget_stopped=true` (healthy, more
  work remains: continues), `partial` with series errors (isolated failures: waits for the interval),
  `failed` (all series failed, or abandoned).
* **Duplicate triggers:** the lease admits one writer; the due check turns later triggers into no-ops;
  bar writes are idempotent (existing unchanged bars are never rewritten).
* **Limits (env, clamped):** `PSXNI_MARKET_MAX_PASSES` 3 (1–6) per invocation,
  `PSXNI_MARKET_MAX_RUNS_PER_DAY` 12 (1–48), `PSXNI_MARKET_LEASE_MINUTES` 30 (25–240; must exceed the
  20-minute job timeout). Backoff: interval × 2^failures, at most ×16.
* **Worst-case writes (estimate):** 12 runs/day × ≤5,000 billed rows = 60,000/day, about 1.8M/month,
  inside the 10M quota. Steady state after backfill is far lower (about 5,600/trading day, estimated in
  the 2026-11-08 audit). Each run's budget stays 5,000.
* **Priority:** `PSXNI_MARKET_TIMEFRAME_PRIORITY`, default `1m,1h,4h,1d`: every symbol's 1-minute
  history before any deeper timeframe. Symbols come from `PSXNI_MARKET_SYMBOLS`. Existing bars are
  kept and never re-fetched beyond the 3-bar overlap.

## 3. Roadmap

| Stage | Scope | Status |
|---|---|---|
| 2 | Lease, abandoned-run recovery, due decision, backoff, bounded continuation, trigger tracking | TESTED (offline) |
| 3 | Configurable timeframe-first priority | TESTED (offline) |
| 4 | Workflow `trigger` input, external dispatch design (fine-grained token, `actions:write` on this repo only), missed-run detection | NOT STARTED; token/routine need owner approval |
| 5 | Session calendar (PSX hours, holidays), completeness grading (COMPLETE / INCOMPLETE / ANOMALY / MISSING / PROVIDER_UNAVAILABLE), skip-unfinished-bar fetches, indexed coverage query + app cache, operations tab | NOT STARTED |

## 4. Lease, fencing and recovery rules

* **Claim** (one transaction): release *orchestrated* runs whose lease expired, then insert the new run
  only if no run of this job is `running` inside the lease window. `changes()` decides ownership.
* **Fencing:** every bar and correction insert is `INSERT … SELECT … WHERE EXISTS (run still running)`,
  followed in the same transaction by a status read. A run that lost its lease writes nothing more,
  raises `LeaseLost`, and does not finalise, so the takeover's record stands.
* **Finalisation** is `UPDATE … WHERE run_id = ? AND status = 'running'`.
* **Legacy runs** (no `context` in `quota_usage_json`, i.e. written before this code) are never changed
  automatically. They are reported as `legacy_stale_runs_needing_owner_cleanup`, they do not block the
  lease (it only considers runs inside the window), and they don't count toward today's cap or toward
  backoff (`sources.consecutive_failures` is not touched).
* **Daily cap:** counted from `collector_runs.started_at_utc` for the current UTC day, so it survives
  restarts and cannot be reset by a new dispatch.

## 5. Production run 11: owner-approved cleanup procedure (NOT executed)

Run 11 (`market_ohlcv`, started 2026-11-08 12:40 UTC) is still `running` because it predates PR #25.
Deploying the orchestration code does **not** change it: it has no run context, so automatic recovery
skips it. It is reported as `legacy_stale_runs_needing_owner_cleanup`, and it neither blocks the lease nor
counts toward the daily cap or backoff. Correcting it is a separate production write that needs explicit
owner approval.

1. **Backup first (required).** Take a fresh `/dump` backup and record its SHA-256 and the point-in-time
   restore marker, as for `psxni-prod-backup-20261108T105245Z.sql`. Without it, stop.
2. **Read-only precondition.** Expect exactly one row, with `status = 'running'` and
   `finished_at_utc IS NULL`. Record `started_at_utc`, the counts and the bar count:
   ```sql
   SELECT run_id, job, source_id, status, started_at_utc, finished_at_utc, items_fetched,
          items_accepted, items_rejected, http_requests, errors, quota_usage_json
   FROM collector_runs WHERE run_id = 11;
   SELECT COUNT(*) AS bars FROM market_bars WHERE collection_run_id = 11;   -- expect 1692
   ```
3. **One-row update, guarded by its current state, in one transaction:**
   ```sql
   UPDATE collector_runs
   SET status = 'failed',
       errors = substr(COALESCE(errors || char(10), '') ||
                'owner-approved correction: abandoned before PR #25; true end time unknown', 1, 2000)
   WHERE run_id = 11 AND job = 'market_ohlcv' AND status = 'running' AND finished_at_utc IS NULL
     AND quota_usage_json IS NULL;
   SELECT changes() AS n;   -- must be 1; if 0, nothing matched: stop and investigate
   ```
   `finished_at_utc` stays NULL because the true end time is unknown. `started_at_utc`, the counts and
   `quota_usage_json` are not touched. Market bars cannot be touched: they are append-only, guarded by
   triggers.
4. **Verify (read-only):** run 11 has `status = 'failed'`, `finished_at_utc` NULL, and the same start time
   and counts as recorded in step 2; 1,692 bars are still linked to run 11; no other `collector_runs` row
   changed (compare `COUNT(*)` and `MAX(run_id)` before and after).

## 6. Disposable-Turso lease verification: setup checklist (NOT executed)

SQLite results do not prove Turso behaviour. Until this checklist has been run, single-writer behaviour
on Turso is **unverified**. The only safeguards are the fail-closed ownership read-back and the GitHub
concurrency group. Owner approval is needed for steps 1–3.

1. Create a **new, empty** Turso database used only for this test (e.g. `psxni-lease-test-<date>`), never
   production (`psx-news-intelligence-imranrazabozdar…`).
2. Create a database-scoped token for it, with an expiry of 1 day.
3. Apply migrations to it: `PSXNI_TURSO_DATABASE_URL=<test url> PSXNI_TURSO_AUTH_TOKEN=<test token>
   python -m database.migrate`, in a shell that has no production values set.
4. Run, in that shell:
   ```
   export PSXNI_TEST_TURSO_DATABASE_URL=<test url> PSXNI_TEST_TURSO_AUTH_TOKEN=<test token>
   export PSXNI_TEST_TURSO_ALLOW_COMMITS=yes-commit-test-rows
   unset PSXNI_TURSO_DATABASE_URL PSXNI_TURSO_AUTH_TOKEN
   pytest tests/test_turso_market_lease.py -v
   ```
   The gate (`tests/turso_guard.integration_config_status`) refuses the production host or token before
   connecting.
5. Expected: 3 passed.

   | Test | Verifies |
   |---|---|
   | `test_simultaneous_claims_on_turso_admit_exactly_one` | Two connections claim at once; one owner, one busy, one row, owner finalised |
   | `test_live_lease_blocks_and_expired_orchestrated_lease_is_taken_over` | Live lease blocks; expired lease is taken over and marked abandoned; no `running` row left |
   | `test_fenced_write_after_takeover_writes_nothing` | A fenced bar insert for a run that is no longer `running` writes 0 rows, inside a rolled-back batch |

   Each test removes its synthetic source and run rows. No market bars are committed.
6. Record the date, result and libsql server version here, then delete the test database and revoke the
   token.

## 6a. Known limitations
* The lease, fencing and `changes()` behaviour are verified on local SQLite (including two simultaneous
  writers on one file). **Turso verification is prepared but not run:** `tests/test_turso_market_lease.py`
  needs a dedicated test database with migrations applied, `PSXNI_TEST_TURSO_DATABASE_URL`,
  `PSXNI_TEST_TURSO_AUTH_TOKEN` and `PSXNI_TEST_TURSO_ALLOW_COMMITS=yes-commit-test-rows`. None are
  configured, and creating them requires owner approval.
* The cap counts by UTC day (PKT 05:00 to 05:00).
* Gaps inside already-collected history are not re-requested yet (Stage 5 gap detection). History the
  provider no longer serves comes back as `no_data` and is not treated as a failure.
* An in-progress intraday bar fetched during the session can later be recorded as a correction; Stage 5
  avoids requesting unfinished bars.
