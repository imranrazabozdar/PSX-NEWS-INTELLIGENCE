# Archive database: read-only probe and dry run, 2026-11-10

Status: **probe and dry run executed. No DDL executed.** Final DDL waits for the owner's approval.

## Method
- Command: `python -m scripts.archive_probe` (read-only: SELECT and PRAGMA only; no DDL, no writes).
- Target: the owner-provided archive database (host recorded in the owner's secrets, not in this repository).
- Credential: saved through the session's secure credential form and injected by the network proxy. No value
  appears in this repository or in any transcript.
- Operational database: not opened.
- Run twice. The probe state was identical before and after the dry run.

## Probe result
- Tables: none. Ledger (`schema_migrations`): absent. Triggers: none. Operational tables: none.
- The database is empty. It has no unknown tables, so preflight passes.

## Dry run (`migrate(dry_run=True)` through the gate)
| Migration | Statements | SHA-256 of the committed SQL file (= migration checksum) |
|---|---|---|
| `0001_financial_archive` | 8 | `010562a357a7e3b800dbdc46d3e778265e82d033edf69582ba96df485f6f5e52` |
| `0002_disclosures` | 4 | `1aba03e1818524a37c94855a4dbf4df46264ebac0c5fadc61745520d88481601` |

Both migrations are pending. Checksums were computed independently with `sha256sum` and match.

## Expected state after the approved DDL run
- Tables: `archive_reports`, `archive_financial_tuples`, `archive_disclosures`, `schema_migrations`.
- Triggers: six (`trg_archive_*_no_delete` and `_no_update` for each of the three tables).
- Ledger: two rows.

## Defect found and fixed before this run
The shared migration runner issued `CREATE TABLE IF NOT EXISTS schema_migrations` even on a dry run, so a dry run
could write. The runner now reads the ledger without creating it when `dry_run=True`. Regression coverage is in
`tests/test_archive_turso_integration.py::test_dry_run_changes_nothing_and_reports_checksums`.

## Requested for the final DDL approval
Approval string: `yes-execute-archive-migration-ddl`, set as `PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL` for the single apply command.
