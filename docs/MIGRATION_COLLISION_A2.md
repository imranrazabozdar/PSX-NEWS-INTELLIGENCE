# Migration collision (version 11): remediation A2, rehearsal harness and review

Status (2026-11-09): code and SQLite tests TESTED. **Turso rehearsal: NOT RUN.** **Production: NOT EXECUTED.**
Migrations 0011-0014 are not applied by anything in this change.

## The problem
Production `schema_migrations` holds version 11 = `extraction_reviews` (checksum
`a9b55ef930503e72fa6cf8ff86f9611683f76c4c60767cdd6ccbb582ebc04c39`), a migration that is not in this repository.
This repository's own `0011` is `financial_documents`. `database.migrate.migrate()` therefore raises
`MigrationError: migration 11 (extraction_reviews) was changed after it was applied...` (even with `dry_run=True`)
and `engines.integrity.check` reports problems. The foreign table held 0 rows at the last read-only pre-flight
(2026-11-09T15:36:39Z; counts digest `6ddfff7658f573b868f174ebe29acc5006ddfef9de74ab270a61dc006c3d928d`).
Never fix this by editing the stored name or checksum of row 11: the runner would then record `0011_financial_documents`
as applied without creating its tables.

## What this change adds (nothing else)
| File | Role |
|---|---|
| `scripts/remediate_migration_collision_a2.py` | Option A2: retire the foreign version 11. Dry run by default |
| `tests/test_turso_disposable_a2_rehearsal.py` | Harness: SQLite leg (always) + Turso leg (gated, disposable database only) |
| `docs/MIGRATION_COLLISION_A2.md` | This document |

## The transaction (A2), Option B guard
One transaction: a guard (permanent `_a2_guard` table, created and dropped inside the transaction, whose CHECK fails unless `extraction_reviews` has 0 rows, version 11 has exactly the
expected name and checksum, and 11 is the highest version), then `DROP VIEW v_review_queue`, `DROP TRIGGER`
x2, `DROP INDEX`, `DROP TABLE extraction_reviews`, `DELETE FROM schema_migrations` (name and checksum matched), `DROP TABLE` guard.
The foreign migration's SQL is embedded verbatim in the test and its SHA-256 is asserted, so the checksum cannot drift.

## Review of the guard under Turso's HTTP batch interface
`TursoHTTPDatabase.batch(transactional=True)` sends ONE Hrana `batch` on one stream: `PRAGMA foreign_keys = ON`, `BEGIN`,
each statement conditional on the previous step succeeding, `COMMIT` conditional on the last step, and a `ROLLBACK`
conditional on the `COMMIT` step not succeeding. Consequences for the guard:
* **Expected (from the driver code):** if the guard INSERT violates its CHECK, every later step is skipped, `ROLLBACK` runs, and
  `batch` raises `DatabaseError`. A missing `extraction_reviews` table (a re-run) also errors and aborts.
* **Already proven on Turso by this repository's own rehearsals:** DDL inside this batch pattern is transactional
  (a failing migration leaves no table and no `schema_migrations` row).
* **Why Option B:** the earlier TEMP-table guard could not be assumed to work on Turso's stream. The permanent guard table uses only
  ordinary DDL. It is still **NOT proven on Turso until the Turso leg of the harness has run**; SQLite passing does not establish it.
* **Rule:** if Turso rejects it, stop and report. Another guard is accepted only with proven database-enforced rollback;
  an application-only guard is never substituted.

### Alternatives (fallbacks only if Option B fails on Turso; NOT implemented)
| | Guard | Notes |
|---|---|---|
| C | `SELECT json(CASE WHEN <conditions> THEN '1' ELSE 'guard failed' END)` as the first step | No objects at all; the error skips the later steps; depends on libSQL's JSON functions |
| E | No in-transaction guard: rely on the read-only pre-flight run immediately before, the writer freeze and the backup | Weakest; only if A-C are all rejected |

## Safety properties of the harness
* It never provisions or deletes a database and makes no Platform API call. Creating and deleting the disposable database is a
  separate owner step (runbook section 7). Inside the database it was given, it only creates its own tables and refuses to run unless the
  database is empty.
* Targeting production is blocked twice: the existing `tests/turso_guard.py` deny-list (host, marker, token) and a positive
  allow-list in this change: the host must start with `psxni-migration-rehearsal-`. The script applies the same checks to `--target disposable`.
* The script is a dry run unless `--execute --confirm retire-migration-11 --backup-sha256 <64 hex> --approval-id <ref>` are all given.
* Read budget: two full count passes only (pre-flight, whose result is reused for the expected digest, and post-flight) plus a
  2,000-row reserve for the ledger, runner dry-run and integrity check: about 32,000 reads at 14,959 rows (previously ~45,000).
  Execution is refused unless the estimate with 25% headroom fits the per-run budget (default 50,000) AND enough budget remains
  after the pre-flight reads for the post-flight. If verification still cannot finish after the COMMIT, the status is
  `remediated_check_failed` (never "verified") and the message says the change COMMITTED; run `--verify-only --expect-post-digest <hex>`
  in a fresh process (fresh budget). Do not re-run `--execute`.

## Rehearsal result (2026-11-09)
Fresh disposable Turso database (empty, 2-hour token, exact-host override): `pytest tests/test_turso_disposable_a2_rehearsal.py` gave
26 passed. The Turso leg (tests 01-09) covered: collision reproduced (runner and integrity check fail), pre-flight, incomplete
execute refused, guard aborts with a decision row / wrong checksum / higher version and everything rolls back, A2 executes and
verifies, a re-run is refused, and migrations 0011-0014 then apply. Tests 10-16 use private in-memory databases (not Turso).
The database was reached through the proxy-injected credential; production was never touched. The database and its token are deleted by the owner afterwards.

## Production execution record (2026-11-09)
Executed by the owner-authorized session (approval reference OWNER-APPROVED-2026-11-09-chat) after the owner invalidated every token and issued
new ones. Backup: SHA-256 `2085ec5101dde7dafb4f33718b7f0a9ebb710e3c571cd223fac1146c53cd823e` (56+1 tables, 14,959 rows; restore-tested into SQLite).
Pre-flight digest `6ddfff76…928d` matched the earlier snapshot. Result `remediated_verified`: ledger 1..10, the five foreign objects and the guard
table gone, counts digest `af4c6881…12bf4` as expected (only `schema_migrations` 11 -> 10), `integrity.check` ok, runner dry run lists
0011-0014 as pending, and a separate `--verify-only` run in a fresh process also verified. 34,701 rows read, 4 written. Migrations 0011-0014
were NOT applied by this change.

## Tests
* `pytest tests/test_turso_disposable_a2_rehearsal.py`: SQLite leg only without disposable variables (17 passed, 9 skipped).
* Turso leg (not yet run): create a FRESH database named `psxni-migration-rehearsal-<date>...` in the production region with a
  database-scoped token expiring in about 2 hours, keep the token in a private scratch file, then
  `PSXNI_TURSO_DISPOSABLE_DATABASE_URL=... PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN=... pytest tests/test_turso_disposable_a2_rehearsal.py -rs`.
  Expect 26 passed. Do not reuse the database of the other gate-3 modules. Afterwards delete the database, confirm its host returns 404,
  shred the token file, and record the evidence (names, times, results, no secrets) in `docs/OPERATIONS_RUNBOOK.md` section 7.
* If the Turso leg fails on the guard (tests 04-07): stop, record the exact error, and take the alternatives above to the owner.

## Production sequence (each step needs its own owner approval; none is part of this change)
1. Credential rotation complete and read-only pre-flight repeated (the figures above are from 2026-11-09T15:36Z). 2. Freeze writers.
3. Backup and recorded SHA-256. 4. Turso rehearsal passes. 5. Dry run: `python -m scripts.remediate_migration_collision_a2 --target production`.
6. Execute with the flags above plus `--expect-pre-digest` and `--expect-post-digest af4c68810c50c21f66cf511f71bdc9bdd6422355c7f3134b0389da2821412bf4`
(it refuses if production moved since the snapshot). 7. Activating 0011-0014 is a separate approval (runbook section 1).
