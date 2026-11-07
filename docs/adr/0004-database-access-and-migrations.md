# ADR-0004: Database access, migrations and data integrity

* **Status:** Accepted (Phase 1)
* **Date:** 2026-11-07

## Decision
1. **A dedicated Turso database:** `psx-news-intelligence` (owner's new Turso account). Configuration
   comes only from `PSXNI_TURSO_DATABASE_URL` and `PSXNI_TURSO_AUTH_TOKEN`. Unprefixed variables are
   ignored, and the code never falls back to another database.
2. **No driver dependency.** `database/connection.py` calls Turso's documented HTTP API
   (`POST /v2/pipeline`) with the standard library. Local development and tests use `sqlite3` with
   the same SQL. This adds no third-party packages and keeps the dependency guard simple.
3. **Atomic writes.** Multi-statement writes run as a Turso `batch` (BEGIN, conditional steps,
   COMMIT, and ROLLBACK if any step fails). Network errors and 502/503/504 responses are retried
   with backoff. Writes are idempotent (unique keys and `ON CONFLICT DO NOTHING`), so a retry
   can't create duplicates.
4. **Migrations** (`database/migrate.py`) are numbered SQL files with SHA-256 checksums. They are
   safe to re-run, and editing an already-applied migration is refused. Destructive statements are
   refused (spec section 11.1: no destructive migration without a backup and approval).
5. **Integrity in the database itself:** foreign keys, CHECK constraints for enumerations and
   ranges, unique deduplication keys, and triggers that make history tables append-only.
6. **Integration tests** run against the real Turso database only when its URL is configured.
   Their writes always roll back. Without credentials they are skipped and reported as skipped,
   never mocked.

## Consequences
* There's no ORM. SQL is explicit and reviewed in migrations.
* Schema changes are always a new migration. Applied migrations are never edited.
