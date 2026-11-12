# Archive database: migration safety design

Scope: the financial archive Turso database only. The operational database has its own runner, ledger and token
and is never opened by any archive tool.

## Separation
- Configuration: archive-only variables `PSXNI_ARCHIVE_TURSO_URL` and `PSXNI_ARCHIVE_TURSO_AUTH_TOKEN`. The archive
  never reads the operational token and never falls back to it.
- Connection: `connect_archive()` refuses a missing URL or token, the operational URL (compared by identity), and
  any database that holds operational tables. `connect_main()` refuses the archive the same way.
- Routing: repository functions declare the handle role they need and raise `ArchiveRoutingError` otherwise.
- No cross-database write transaction exists anywhere in the code.

## Migration history
- The archive has its own ledger (`schema_migrations`) and its own numbering. It cannot share versions with the
  operational sequence.
- Each applied migration is recorded with its name and SHA-256 checksum of the file bytes.
- The runner refuses: a checksum mismatch, a name mismatch (version reuse or rename), a version missing from the
  repository, a ledger gap, an out-of-order pending migration.
- Applied migration files are immutable. A change means a new migration. Checksums are never edited to pass.

## Structure is derived, not declared
- `reference_fingerprint(k)` applies the first k migration files to an in-memory database and records every table,
  column, index and trigger. No hand-maintained list can drift from the SQL.
- The target is inventoried with SELECT and PRAGMA only and compared with the reference for its ledger state.
- Any extra object (table, index, trigger, view) refuses the database. A missing or changed object is drift.

## Dry run
- `plan()` performs reads only. Its statements are recorded and proven to contain no write or DDL
  (`tests/test_archive_safety.py`). The schema inventory and ledger are unchanged before and after.
- The shared runner's dry run no longer creates the ledger. It previously did, which is fixed and tested.

## Apply gate
Real DDL runs only when all of these hold, in this order:
1. The target declares purpose `archive`.
2. The connection carries the archive role.
3. `PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL` equals `yes-execute-archive-migration-ddl` exactly.
4. Preflight passes: no operational objects, no unknown objects.
5. Pre-state drift is zero for the recorded ledger state.
Then migrations run in order, each in one batch with its ledger row.

After the run, the structure must equal the full reference. If it does not, the run stops with a `SchemaDrift`
report. Nothing is rolled back or re-run automatically.

The approval value is never printed or logged. A refusal names the variable, not its value.

## Interruption and recovery
- Turso/libSQL atomicity for a multi-statement DDL batch is NOT verified by any test in this repository. It must be
  verified against the disposable archive-test database before production DDL. Until then, the design assumes an
  interruption may leave partial objects.
- An interrupted run is detected on the next probe: objects exist without matching ledger rows, or a ledger row
  exists with objects missing. The gate refuses to apply on pre-state drift.
- Recovery procedure (manual, with owner approval):
  1. Run the probe and record its output. Do not re-run the migration command.
  2. Identify which objects of which migration exist (the probe lists them).
  3. Decide between: finish the migration by hand under a new approval, or remove the partial objects under a
     separate approval. Neither is performed automatically.
  4. Re-probe until `fully_migrated` is true, then record the ledger.
- Backup: the archive is empty until data is loaded. Before any data load, a Turso point-in-time restore or
  export must be confirmed on the owner's account plan. This is NOT verified here.

## Storage and privacy rules enforced in the schema
- No BLOB columns. PDFs stay in the local vault; the archive stores only SHA-256 hashes and file names. File names
  and vault references cannot contain path separators (CHECK constraints).
- Append-only triggers on every table holding evidence or history.
- Missing values are `not_reported` (NULL), never zero (CHECK constraint).
- Duplicate prevention: documents by file hash; line items, notes, reconciliation results by natural key.
- Reviews are separate rows. Original extracted values are never changed.

## Verification status
| Control | Evidence | Status |
|---|---|---|
| Separate configuration and refusals | `tests/test_archive_turso_integration.py` (offline), `tests/test_dual_database.py` | Passing offline |
| Dry run immutability | `tests/test_archive_safety.py` | Passing offline, recorded SQL |
| Ledger name, checksum, gap, order checks | `tests/test_archive_safety.py` | Passing offline |
| Unknown and drifted objects refused | `tests/test_archive_safety.py` | Passing offline |
| Apply approval exact match | `tests/test_archive_safety.py` | Passing offline |
| Turso DDL execution, triggers, CHECKs, JSON validity | Disposable archive-test database | NOT RUN: not configured |
| Turso DDL atomicity under interruption | Disposable archive-test database | NOT RUN |
| Foreign key enforcement on Turso | Disposable archive-test database | NOT VERIFIED; relationships are documented in the schema and enforced by the repository |
