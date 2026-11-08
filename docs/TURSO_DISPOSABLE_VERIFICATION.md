# Disposable-Turso verification (gate 3) — procedure

**Status: NOT EXECUTED.** No disposable Turso database or credential exists in this project's
environment. The only Turso credential configured is production's, and it must never be used for
this. The production gate stays **closed**.

## Purpose
Verify migrations 0006–0009 on a real Turso server, through the HTTP (Hrana) interface the
application uses, before any production migration is proposed. Specifically:
- composite foreign keys;
- trigger cascades: event refutation withdrawing assessments, revision writes;
- audit-write rollback;
- concurrent expiry-policy approvals;
- transaction behaviour of batches;
- overlap detection;
- synthetic-data isolation.

## Procedure (owner-run)
1. Create a **new, empty** Turso database used only for this test, for example
   `psxni-disposable-verify-<date>`. Never reuse or copy production.
2. Create a database-scoped token for it.
3. Provide the URL and token to the test run as **separate** variables:
   - `PSXNI_TURSO_DISPOSABLE_DATABASE_URL`
   - `PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN`

   Use the session's network-secret mechanism for the token, never chat or the repository. Do **not**
   set `PSXNI_TURSO_DATABASE_URL` for this run.
4. Run: `pytest tests/test_turso_disposable.py -rs`.

   The module refuses to run if:
   - the URL looks like production or equals `PSXNI_TURSO_DATABASE_URL`;
   - the target database is not empty.
5. Also run the SQLite-level suites, to compare behaviour.
6. Record the results in this document (date, Turso version, pass or fail per test). Then destroy
   the disposable database and revoke its token.

## What the module checks
| Test | Verifies |
|---|---|
| `test_all_migrations_apply_and_foreign_keys_enforced` | 0001–0009 apply over HTTP; `PRAGMA foreign_keys` on |
| `test_composite_fk_and_cascade_over_http` | composite FK refusal; refutation cascade withdraws the assessment and writes revision 2 |
| `test_policy_approval_race_over_http` | two concurrent HTTP approvals of overlapping policies: exactly one succeeds; the overlap view is empty |

**To add during the gate-3 run:**
- audit-failure rollback over HTTP (needs a per-batch TEMP trigger; confirm Hrana keeps TEMP objects
  within one batch);
- synthetic-isolation refusals.

## Production integration test: explicit DDL opt-in
`tests/test_turso_integration.py` can verify pending migrations inside a batch that is always rolled
back. Since the PR #21 remediation, it does so **only** when
`PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL=yes-execute-migration-ddl` is also set. A configured
`PSXNI_TURSO_DATABASE_URL` alone skips that step.
- **Risk:** even rolled back, migration DDL executes against whatever database the URL names.
- **Rule:** CI never sets the opt-in, and it must never be set for production.

## Already verified locally (not Turso)
- SQLite 3.53.1 (stdlib): full suite, including the two-connection approval race.
- SQLite 3.47.0 (`sqlean.py`, Turso's reported version): impact, exposure and database suites.
- libSQL embedded engine 3.45.1: migrations 0001–0009 apply (229 statements after remediation); a REPLACE
  overwrite attempt is refused.
- SQLite 3.47.0: the remediation regression suite passes as well.

## Remains unverified
- Hrana transaction and lock semantics for concurrent batches.
- TEMP-object scope per batch.
- Cascade and composite-FK enforcement on the server.
- Server-side limits.
