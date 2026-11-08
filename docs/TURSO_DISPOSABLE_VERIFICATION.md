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
4. Run: `pytest tests/test_turso_disposable.py -rs -p no:cacheprovider`.

   The gate (`tests/turso_guard.py`, `disposable_config_status`, unit-tested in CI) **skips** when neither
   variable is set. It **fails**, never falling back to production, when:
   - only one variable is set;
   - the URL is not `libsql://` or `https://`;
   - the URL contains the production marker, or has the same host as `PSXNI_TURSO_DATABASE_URL` under
     either scheme;
   - the token equals `PSXNI_TURSO_AUTH_TOKEN`.

   The module also refuses a non-empty database. Production variables are never used to connect.
5. Also run the SQLite-level suites, to compare behaviour.
6. Record the results in this document (date, Turso version, pass or fail per test). Then destroy
   the disposable database and revoke its token.

## What the module checks
| Test | Verifies over HTTP |
|---|---|
| `test_all_migrations_apply_and_foreign_keys_enforced` | 0001–0009 apply; `PRAGMA foreign_keys` on |
| `test_composite_fk_and_cascade_over_http` | composite FK refusal; the refutation cascade withdraws the assessment and writes revision 2 |
| `test_policy_approval_race_over_http` | two concurrent approvals of overlapping policies: exactly one succeeds; the overlap view is empty |
| `test_0009_guards_installed_over_http` | every 0009 guard trigger and the review-once index are installed on the server |
| `test_review_single_use_over_http` | a consumed review cannot authorise a later transition |
| `test_every_linked_exposure_freshness_with_server_clock` | a record that expired yesterday by the **server clock** blocks the upgrade; one valid through today qualifies |
| `test_linked_exposure_immutability_over_http` | UPDATE, DELETE and REPLACE of a linked exposure record refused; the record is unchanged |
| `test_permanent_retraction_and_read_time_revalidation_over_http` | retraction makes the assessment read `needs_revalidation`; REPLACE on either identity and DELETE refused |
| `test_exposure_chain_replace_guards_over_http` | REPLACE of a candidate, of an evidence link (by rowid) and of a candidate revision refused; rows unchanged |

The 0009 tests reuse the SQL-level fixtures of `tests/test_impact_assessments.py` through the `Database`
interface. Each uses its own synthetic company. They have been dry-run on a local SQLite file only to
check the test logic: 9 of 9 pass, and 4 fail when the 0009 guards are dropped. **That is not Turso
verification.**

**Not covered over HTTP:**
- Expiry after the fact, where a record expires after an assessment has qualified: no clock can be
  advanced on the server. The server-clock test above covers the same rule from the other side.
- Audit-failure rollback, which needs a per-batch TEMP trigger.
- Synthetic-isolation refusals.

**Cleanup:** all written data is SYNTHETIC and append-only by design, so it cannot be deleted. Destroy the
disposable database afterwards and revoke its token.

**libSQL clock limitation:**
- **Which tests:** four tests advance time with `tests/db_clock.py`, which overrides SQL `date()` and
  `strftime()` on the connection:
  - `test_expiry_decision_uses_the_database_clock`;
  - `test_expiry_is_irreversible_and_replacement_needs_new_evidence_and_review`;
  - `test_read_time_invalidation_when_a_record_lapses`;
  - `test_single_record_lapse_invalidates_confirmed`.
- **Why they can't run on embedded libSQL:** its Python connection cannot register SQL functions.
- **Why they weren't made portable:** that would need a test-controlled time source inside the
  production SQL, which is not acceptable.
- **Coverage:** they pass on SQLite 3.53.1 and 3.47.0. On Turso the same rules are checked against the
  real server clock, as above.

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
