# Security and incident register

Last verified: 2026-11-10. Names only. No value is recorded anywhere in this package.

## 1. Credential status
| Credential (name) | Used by | Environment | Production or disposable | Status | Evidence |
|---|---|---|---|---|---|
| Old shared production write token (name not recorded here) | Historical: technical and early news sessions | Claude "Default" environment network secret | production | **Invalidated.** A read with it returned HTTP 401 on 2026-11-10 ("role was invalidated after token was issued") | [PROD-RO] |
| Saved network-secret entries for the production host and the old rehearsal hosts in the Default environment | Claude sessions | Claude environment | production and disposable | **Deletion UNKNOWN.** The owner was asked to delete them. An invalid token is harmless, but the entries must go | [REPORTED] |
| Read-only production token, 1 day (created 2026-11-09) | Pre-flight and backup | Claude environment | production, read-only | Expired by its own lifetime [UNKNOWN exact expiry] | [REPORTED] |
| Write token, 1 hour and 2 hour (created 2026-11-09) | A2 execution | Claude environment | production, write | Expired by lifetime. A2 is done. | [REPORTED] |
| App runtime token (`PSXNI_TURSO_AUTH_TOKEN`) | News app and CI, in the news repository's GitHub secrets | GitHub Actions secrets (news) | production, read-write | Created by the owner on 2026-11-10 [REPORTED]. Stored in GitHub secrets [REPORTED]. Not verified from this package | — |
| `PSXNI_TURSO_DATABASE_URL` | News app and CI | GitHub secrets (news) | production address (not secret, but not for display) | Set to the owned host [REPORTED] | — |
| Technical `LIBSQL_URL`, `LIBSQL_AUTH_TOKEN` | Technical CI and runtime | GitHub secrets (technical) | historically the news production database | **Must be repointed** to a separate database. Current value [UNKNOWN] | [REPORTED] |
| Disposable rehearsal database token (`a2-rehearsal-1109`, 2 h) | A2 Turso rehearsal | Claude environment | disposable | Destruction of the database: [UNKNOWN] | [REPORTED] |
| LLM provider keys (`PSXNI_GROQ_API_KEY`, `PSXNI_GEMINI_API_KEY`, `PSXNI_OPENROUTER_API_KEY`) | Technical project: live calls | Technical project secrets and the shared Claude environment | free-tier accounts | Present in the shared environment [REPORTED]. Rotation status [UNKNOWN] | [REPORTED] |
| `PSXNI_ANTHROPIC_API_KEY` | Not connected | — | — | Not created [SRC] | — |

Owner actions on credentials are listed in `OWNER_ACTIONS_REQUIRED.md`.

## 2. Incidents
Each entry: root cause, impact, correction, status, remaining risk, prevention control.

### INC-1. One Turso database used by two projects
- **Root cause:** the technical engine's runtime was pointed at the news production database through its secrets. No check refused it.
- **Impact:** technical writes into news production (see INC-3); the version-11 collision (INC-2); shared credentials in two environments.
- **Correction:** guards on both sides (news PR #58 branch, technical PR #67 branch). Owner to create a separate database and repoint secrets.
- **Status:** guards open as PRs; separation NOT done.
- **Remaining risk:** until secrets are repointed, the technical workflow still points at the news database. Historical shared rows remain.
- **Control:** purpose-bound connections; refusal at construction and at import; tests on both sides.

### INC-2. Migration version-11 collision
- **Root cause:** the technical migration `0011_extraction_reviews` was applied to the news production database, which already had its own version 11 sequence from the news repository's migration `0011_financial_documents`.
- **Impact:** the news migration runner refused to run; the ledger for version 11 held a foreign name and checksum.
- **Correction:** A2 remediation (PR #52, merged): guarded transaction, verified production execution, backups taken (SHA-256 in the migration runbook). Migrations 0011–0014 applied after.
- **Status:** resolved in production [REPORTED + PROD-RO ledger 2026-11-10].
- **Remaining risk:** the foreign `extraction_reviews` rows (0 at the time of A2) are gone with the table. Any technical review decisions made after A2 would have been lost; none are known.
- **Control:** the A2 guard; the migration runbook; the purpose-bound connections.

### INC-3. Technical writes into the news production database
- **Root cause:** INC-1.
- **Impact, as reported** (not rechecked): 120 OHLCV bars in `market_bars` (run 38); 21 Investify rows in `source_items` (run 39); 21 name backfills (run 40); 16 stub companies and 32 aliases (run 41); 15 `llm_calls` and 15 extraction candidates; review and cluster tables 0 rows [REPORTED: PRs #60–#66].
- **Correction:** quarantine of legacy extraction records at read time (news PR #59, branch). Other tables not yet quarantined.
- **Status:** OPEN for `market_bars`, company stubs and aliases, and Investify rows.
- **Remaining risk:** the news code reads `market_bars` and the company master. These rows could affect outputs. The owner must decide between keeping, quarantining or removing them, under a backup, rehearsal and approval.
- **Control:** queued in tasks; no automatic deletion.

### INC-4. Live model output written to the shared database
- **Root cause:** INC-1 and the technical extraction runs.
- **Impact:** 15 extraction candidates, none reviewed, some with grounded quotes, some without (reported 2026-11-09).
- **Correction:** quarantine on read (news PR #59). Candidates must not be promoted automatically.
- **Status:** OPEN for review and disposition.
- **Control:** append-only triggers keep the rows intact; review requires a human.

### INC-5. Technical features described as news features
- **Root cause:** reporting and planning across two repositories.
- **Impact:** audits reported completed work that was in the other repository.
- **Correction:** `docs/ARCHITECTURE_CORRECTION_2026-11-10.md` (news PR #63) and this handover.
- **Status:** corrected in documentation.

### INC-6. Repeated plans and audits instead of implementation
- **Impact:** wasted cycles; some audits missed existing work.
- **Control:** inspect the repository and PR before any plan; cite evidence.

### INC-7. Migration guard proven only on SQLite
- **Root cause:** a TEMP-table guard was assumed to work on Turso.
- **Correction:** the guard was changed to a permanent table and proven on a disposable Turso database [REPORTED].
- **Status:** resolved for A2.

### INC-8. Post-COMMIT read-budget failure risk
- **Root cause:** verification reads could exceed the per-run budget after COMMIT.
- **Correction:** pre-flight estimate with headroom, reuse of pre-flight counts, `--verify-only` in a fresh process, and never reporting a committed run as verified.
- **Status:** resolved in the script; the production run used 34,701 reads against a 50,000 budget [REPORTED].

### INC-9. Restricted sources
- **Root cause:** a read-only pilot against a restricted listing; one debug call sent a short paraphrase of restricted text to a model provider (reported in technical PR #63 [REPORTED]).
- **Impact:** one small text disclosed to a free-tier provider, not stored by this project.
- **Correction:** eligibility gate; restricted items excluded; disclosure recorded.
- **Status:** controlled. Remaining risk: any future debug call must not carry restricted text.

### INC-10. Synthetic evaluation presented as accuracy
- **Root cause:** an author-written sample.
- **Correction:** labels and this register.
- **Status:** controlled by wording. Any accuracy claim needs independent labelled data.

### INC-11. A failing secret-scan blocking PR checks
- **Root cause:** `.gitleaksignore` on a branch that other PRs did not include, and full-history scanning.
- **Correction:** planned: merge #57, then update branches from `main`. No history rewrite.
- **Status:** OPEN (PRs #58–#63).

### INC-12. Force-push attempt blocked
- **Root cause:** an attempt to force-push a rebased branch.
- **Impact:** none; the permission system refused it. A new branch was used instead.
- **Control:** never force-push a shared branch. Use new branch names.

## 3. Controls summary
| Control | Where | Status |
|---|---|---|
| Purpose-bound database connections | news `database/connection.py` | branch, PR #58 |
| Refusal of the news database in the technical engine | technical `fundamental_engine/core/db_guard.py`, `backend/turso_db.py` | branch, PR #67 |
| Quarantine of legacy extraction rows | news `engines/quarantine.py` | branch, PR #59 |
| Append-only extraction and review tables | migrations 0007, 0008 | on main [SRC] |
| A2 guard and verification | `scripts/remediate_migration_collision_a2.py` | merged, PR #52 |
| Independence scanner | `scripts/check_independence.py` | on main, runs in CI |
| Secret scanning with canary | CI `secret-scan` job | on main; failing on open PRs (INC-11) |
| Eligibility gate for model input | `engines/extraction.py`, `engines/llm_live.py` | on main / branch |
| Kill switch for model calls | `engines/llm.py`, `PSXNI_KILL_SWITCH` | on main |
