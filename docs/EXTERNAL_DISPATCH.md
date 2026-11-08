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
* **An accepted dispatch (HTTP 204) is not a successful collection.** It only queues the workflow, and
  the heartbeat records only that collection was invoked. Collection success is judged only from
  `collector_runs` (status `succeeded`, or `partial` with `budget_stopped`) and the source health columns.
  A workflow run that ends green because nothing was due writes no run row.
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

## Operational setup guide (owner steps; nothing here has been done)

1. **Create the token:** GitHub → Settings → Developer settings → Fine-grained tokens → Generate.
   * Resource owner: `imranrazabozdar`.
   * Repository access: *Only select repositories* → `PSX-NEWS-INTELLIGENCE`.
   * Permissions: Repository → **Actions: Read and write**. Leave everything else as *No access*
     (Metadata: Read is mandatory and automatic).
   * Expiration: 90 days or less.
2. **Store it** only in the external scheduler's secret store, as `PSXNI_DISPATCH_TOKEN`. Don't add it to
   this repository's secrets, and don't paste it into chat or logs.
3. **Configure the scheduler** to run hourly at a jittered minute (e.g. `41 * * * *` UTC):
   ```
   curl -fsS -X POST \
     -H "Authorization: Bearer $PSXNI_DISPATCH_TOKEN" -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/imranrazabozdar/PSX-NEWS-INTELLIGENCE/actions/workflows/scheduled-jobs.yml/dispatches \
     -d '{"ref":"main","inputs":{"trigger":"external","dry_run":"false"}}'
   ```
   `dry_run` must be `"false"` explicitly; the default is a dry run. Expect HTTP 204.
4. **First check (owner-approved):** let one dispatch run, then confirm in the *Collection operations*
   tab that the `external` trigger shows status `ok`, and that a run row records `trigger: external` with
   the GitHub run id.
5. **Failure detection:**

   | Symptom | Cause | Action |
   |---|---|---|
   | Non-204 from the dispatch call | API failure | Scheduler retries once after 60 s, then alerts |
   | 401 or 403 | Token expired or revoked | Owner rotates the token |
   | `external` trigger overdue (more than 3 h) | External scheduler is down | Collection continues on cron |
   | `schedule` trigger overdue (more than 6 h 30 min) | GitHub cron missed or late | `python -m collectors.schedule_health` lists the missed slots |

6. **Missed-run recovery:** none is needed by hand. The next trigger from either path runs whatever is
   due. Bars resume from the last stored bar, budget-stopped runs continue, and recoverable gaps are
   re-requested within provider retention.
7. **Cron fallback:** keep `17 */6 * * *` in place. Remove it only after the external trigger has been
   reliable for a period the owner chooses.
8. **Rotation:** before the token expires, create its replacement, update the scheduler secret, then
   revoke the old token.
