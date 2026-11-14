# Turso database policy

Status: policy as enforced by the repository on `feature/financial-pdf-reconciliation`. It names variables and
rules only. No secret value appears in this repository, and none may be added.

## 1. Databases and roles

| Role | Holds | Environment variables (names only) | Enforced by |
|---|---|---|---|
| Main (operational, news) | operational tables (`database/migrations`) | `PSXNI_TURSO_DATABASE_URL`, `PSXNI_TURSO_AUTH_TOKEN` | `database/connection.py` (`connect_main`, `assert_role`) |
| Archive (financial history) | archive tables (`database/archive_migrations`) | `PSXNI_ARCHIVE_TURSO_URL`, `PSXNI_ARCHIVE_TURSO_AUTH_TOKEN` | `connect_archive`; refuses the main URL under any spelling |
| Portfolio (designed, M8) | portfolio tables (`database/portfolio_migrations`) | `PSXNI_PORTFOLIO_DATABASE_URL`, `PSXNI_PORTFOLIO_AUTH_TOKEN` | no connector yet |

- Each role uses its own URL and token. A missing archive token is an error; the main token is never reused.
- Each database has its own migration ledger (`schema_migrations`). The runners never share a ledger.
- `assert_role` refuses a handle whose tables belong to another role. The role sets are derived from the migration
  directories (`tables_created_by`), so they cannot drift from the schema (`tests/test_role_guard_completeness.py`).
- Document files never enter a database. Raw PDFs stay in `PSXNI_DOCUMENT_VAULT`, which must be an absolute
  directory outside the repository. Only SHA-256 names and metadata are stored.

## 2. Migrations

- Migrations are numbered, applied in order, and immutable once applied. The runner records a SHA-256 checksum
  and refuses to continue if an applied file has changed. Corrections are new migrations.
- Migrations are additive. The runner refuses `DROP`, `DELETE FROM`, and table rename or drop statements.
- Immutable history: archive migrations 0001 to 0008 and news migrations 0001 to 0016 are not edited.
- Live application requires owner approval and a disposable rehearsal first. A rehearsal target must match the
  allow-list `psxni-migration-rehearsal-*` (the A2 remediation tool, `scripts/remediate_migration_collision_a2.py`).
  A production target is always refused.
- Rehearsals on a disposable Turso database are gated by `PSXNI_TURSO_DISPOSABLE_*` and the suite is skipped
  when they are not configured. The A2 guard rehearsal and the archive disposable integration are NOT RUN.

## 3. What this repository and this session may do

- Local SQLite only: migrations, tests and rehearsals run on in-memory or throwaway files.
- No write to any remote or live Turso database from development sessions, and no production DDL.
- Tests never use production credentials. Real-Turso tests are gated by `PSXNI_TEST_TURSO_*` and
  `PSXNI_ARCHIVE_TEST_TURSO_*` and skip otherwise.
- Merges go through the feature branch and owner approval. Nothing merges to `main` without it.

## 4. Reference data and the seed

- `database/seed/companies.json` is reference data. Its validation requires 30 to 60 listed companies, so the
  seed is not extended with the full watchlist. The coverage watchlist (`config/coverage_watchlist.json`) is the
  defined scope for extraction and analysis, and is not loaded into the database.
- The seed loader hashes the seed files. Changing a seed file (for example the `in_scope` flags added on
  2026-11-11) changes the hash, so the next reference-data load treats the data as changed and writes again.
  Run such a load only with owner approval.

## 5. Secrets

- Secret variables use the `PSXNI_` prefix and are set in the environment or CI secrets. They are never committed,
  printed, or logged. `.env` files are git-ignored.
- The independence guard (`scripts/check_independence.py`) refuses secret names without the prefix in workflows.

## 6. Current state (not inspected by this session)

- The live state of the main, archive and portfolio databases is UNKNOWN from this repository.
- The archive migrations 0006 to 0008 are tested only on in-memory SQLite. They are not applied anywhere.
- Owner decisions open: F5 (placement of financial results), merge to `main`, and any live application.
