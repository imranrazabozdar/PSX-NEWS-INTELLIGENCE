# Intelligence pipeline: production activation runbook (PREPARED, NOT EXECUTED)

Activation needs explicit owner approval. Nothing in this repository calls the pipeline against production
yet. Migrations 0007–0009 are already in production, so **no migration is needed**.

## What runs
`engines/intel_pipeline.run_all(db)` runs these stages, in order, as one lease-protected job (`collector_runs.job
= 'intelligence'`):
1. headline builder;
2. event intel;
3. exposure and T1–T9 impact;
4. revalidation.

Every stage is idempotent and writes one transaction per item or assessment. A second runner exits
(`Busy`). A run left `running` for more than 60 minutes is finalised as `failed` (abandoned) by the next
claim.

## Proposed activation steps (each needs approval)
1. **Fresh production backup** (`/dump`), recorded with SHA-256, as for run 11.
2. **Dry inspection, read-only:** `readiness()` on production. Expect the headline backlog to equal the
   stored news items (276 at the last audit) and 0 events.
3. **Add a production entry point:** a small change that lets `intel_pipeline.main` use `connect()` with the
   production budget (5,000 rows per run). Today it accepts only `--local-db`.
4. **Workflow:** a separate job or workflow (recommended: its own, with its own concurrency group), run after
   collection. It is never part of the market collector's lease.
5. **First run:** with an explicit limit (e.g. 50 items). Then review `readiness()` and the run record.
6. **Backlog:** process the remaining stored items over later runs, within the per-run budget.

## Monitoring and alerts
* `readiness()["overall"]`:
  * `fail` means the last run failed, or more than one runner is running. Investigate before the next run.
  * `warn` means backlogs, stale assessments or pending reviews. Expected while work is queued.
* `collector_runs` (job `intelligence`): `status`, `errors` and `quota_usage_json.summary` per run.
* The dashboard's Readiness and Review tabs.

## Recovery
* **Crash or timeout:** re-run. Completed items are skipped, and the abandoned lease is finalised
  automatically after 60 minutes.
* **A bad ruleset:** stop runs (kill switch / workflow disabled). Outputs are append-only and versioned
  (`headline-event/1`, `event-intel/1`, `transmission/1`). A corrected ruleset is a new version, so the
  history stays intact.
* **Turso budget reached:** the run stops cleanly (`stopped_at_budget`), and the next run continues.
