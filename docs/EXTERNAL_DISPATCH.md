# External dispatch for scheduled collection (Stage 4)

Status: repository side IMPLEMENTED and TESTED offline. The token, the repository secret and the external
scheduler are NOT created. Each needs separate owner approval.

## Why
GitHub's cron starts this workflow late or not at all (measured 2026-11-08: 69 minutes late, about 5¾ h
late, one slot skipped). An independent scheduler that calls `workflow_dispatch` starts runs when they are
needed. GitHub cron stays as the fallback, so a failure of either trigger alone stops nothing.

## How a dispatch is handled
1. The external scheduler sends `POST /repos/imranrazabozdar/PSX-NEWS-INTELLIGENCE/actions/workflows/
   scheduled-jobs.yml/dispatches` with `{"ref": "main", "inputs": {"trigger": "external", "dry_run": "false"}}`.
   `dry_run` defaults to `true` for dispatches, so a scheduler that omits it collects nothing.
2. The workflow sets `PSXNI_TRIGGER` to `schedule` for cron runs and to the `trigger` input otherwise, and
   passes it to `collectors.market_ohlcv --due --trigger`.
3. The orchestrator records a heartbeat (`collector_checkpoints.cursor` of `scs_chart`: last time and
   GitHub run id per origin), even when nothing is due, and records origin, run id, pass and reason in
   each run's `collector_runs.quota_usage_json`.
4. Duplicate triggers are safe at three levels:
   * the workflow `concurrency: scheduled-collection` group runs one job at a time (GitHub keeps at most
     one queued run and cancels older pending ones);
   * the database lease admits one market writer, with fencing after a takeover;
   * the due check (interval, backoff, continuation, daily cap of 12 runs) makes extra triggers no-ops.
     The news step has its own per-source due check.

## Token (to be created by the owner, NOT created)
* A **fine-grained personal access token**, resource owner `imranrazabozdar`, **repository access: only
  `PSX-NEWS-INTELLIGENCE`**.
* **Repository permissions: Actions = Read and write** (this is what `workflow_dispatch` requires;
  Metadata = Read is added automatically). No contents, secrets, administration or other permissions.
* An expiry of 90 days or less, with a calendar reminder to rotate it.
* Stored **only** in the external scheduler's secret store, as `PSXNI_DISPATCH_TOKEN`. It is never committed,
  never stored as a repository secret (the workflow does not need it), and never printed.
* Recommended cadence: hourly at a jittered minute (e.g. `41 * * * *`). Hourly is enough for continuation
  (3 passes per invocation) and the 60-minute market interval, and stays well inside the daily cap.

## Scheduler options
| Option | Fits | Limitations |
|---|---|---|
| Claude Code scheduled task calling the dispatch API | independent of GitHub's scheduler; owner already uses this pattern elsewhere | depends on that service; the token lives in its environment's secret store |
| Any external cron (e.g. a small always-on host) running one `curl` | simplest | needs a host; the owner manages its availability |
| A second GitHub workflow cron | **not** independent: same unreliable scheduler | not recommended |

## Limitations and failure handling
* A dispatch API call can fail (HTTP 5xx, network). The scheduler should retry once after about a minute.
  It must not loop: the next hourly call is the retry, and the cron fallback covers outages.
* HTTP 401/403 means the token expired or lost access. That needs owner action. Collection continues on
  GitHub cron.
* A successful dispatch only starts the workflow. The kill switch (`PSXNI_KILL_SWITCH`), missing Turso
  secrets and source ACTIVE status still apply.
* GitHub may delay dispatched runs under load. Usually they start within a minute.

## Monitoring
* `last_triggers()` (heartbeat) shows the last schedule / external / manual invocation.
* `python -m collectors.schedule_health runs.json` classifies each cron slot as on_time, late (more than
  30 min), missed or pending, from `gh run list --workflow scheduled-jobs.yml --event schedule --json
  createdAt`. It exits 1 if a slot was missed.
* No successful external invocation for over 3 hours means the external trigger is down. Collection still
  runs on GitHub cron, and the owner checks the token and scheduler.
* Stage 5 adds these to the Streamlit operations view.
