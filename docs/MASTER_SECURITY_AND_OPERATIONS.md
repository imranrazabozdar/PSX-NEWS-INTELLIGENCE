# Master security and operations

Status: DESIGN (main `012a6bf`). These controls keep their current form; none is weakened by this programme.

## 1. Independence (ADR-0001, permanent)
* **No technical-project content of any kind:** no imports, dependencies, shared database, shared credentials,
  cross-repository workflows or copied indicators.
* **`scripts/check_independence.py`** must pass before every commit, and its allowlist is not loosened to fit new
  modules (new modules go under `engines/` or `collectors/`).
* **No integration or data exchange of any kind** with the technical project (files, tables, exports,
  submodules, workflows or runtime calls). This is permanent unless the owner changes the project boundary in a
  future, separately documented decision; it is not an open decision.

## 2. Secrets
* **Naming and storage:** `PSXNI_` prefix only, stored in GitHub secrets or the environment, never in the
  repository, logs or test fixtures.
* **Separate tokens** for the research database, the portfolio database (`PSXNI_PORTFOLIO_*`, M8) and any future
  source key (e.g. `PSXNI_EIA_API_KEY`, U2).
* **CI:** CI holds no production secrets. Tests run on in-memory SQLite and recorded fixtures.
* **Logs:** URL and credential redaction stays in place; tests assert that tokens never appear in output.

## 3. Access and approvals
| Action | Requires |
|---|---|
| Merge a PR | Owner's explicit approval |
| Production write, migration, activation, new scheduled job | **Separate** owner approval, per action; a merge is not approval |
| New source automation | Register row upgraded to V (terms reviewed) and owner approval |
| New dependency | PyPI only; justified in the PR; owner approval |
| Paid service or AI provider | Not authorised (U11) |
| Order execution / trading | Never built |

## 4. Production change procedure (every migration or activation)
1. **Backup:** export with a SHA-256 recorded.
2. **Rehearsal:** on a disposable Turso database, then delete it and rotate its token.
3. **Migration:** additive only; append-only triggers verified.
4. **Limited first run:** small `--limit`, within the per-run budget (5,000 rows written, 50k read, 2,000
   requests).
5. **Evidence:** run id, row counts and quota usage recorded in the module's document.
6. **Widen** only after the evidence is reviewed. Rollback is to restore from the backup, or disable the job; the
   rollback path is tested in the rehearsal.

## 5. Operations
* **Single-writer lease and fencing:** applies to all collectors and engines (existing `collection_ops`).
* **Budgets:** per-run budgets, plus monthly monitoring against the Starter quotas (500M reads, 10M writes, 5 GB).
  Writes are checked after each milestone backfill.
* **Monitoring:** schedule health, gap recovery and readiness views remain the operational surface; new jobs
  register there.
* **Calendar maintenance:** moon-dependent holidays are entered manually from PSX notices
  (`PSX_CALENDAR_MAINTENANCE.md`).
* **Incidents:** a source outage means `source_unavailable`, never zero. Repeated failures back off; nothing is
  backfilled with invented values.

## 6. Outstanding Stage 1/2 operational items (M0)
| Item | State |
|---|---|
| Scheduled run of the current code | Production evidence pending |
| Continuation after a budget stop | Pending |
| Backfill completion (5 symbols) | Pending |
| External dispatcher | Blocked on the owner's token and scheduler |
| Moon-dependent holidays and Ramadan hours | Manual entry pending |
| Intelligence pipeline activation | Awaiting a separate owner approval |
| Saved test-host credential from the lock verification | Owner to remove manually |

## Update (OGDC pilot finalisation): document vault and local tools

- The vault holds original PDFs outside the repository, private (0700). Intake refuses symbolic links and group- or world-accessible vault folders.
- OCR, where evaluated, runs locally through fixed command lines. No cloud OCR, no third-party AI, no document upload.
- Tesseract was installed only in the development container for evaluation. It is not part of any production environment; installing it there would need its own approval.
- No production database was touched in this batch; all tests use in-memory or local databases.
