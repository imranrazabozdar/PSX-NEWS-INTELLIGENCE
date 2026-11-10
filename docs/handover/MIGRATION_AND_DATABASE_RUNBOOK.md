# Migration and database runbook

Last verified: 2026-11-10.

## 1. Migration history (news repository) [SRC `database/migrations/`]
| Version | File | Purpose |
|---|---|---|
| 0001 | `0001_reference_and_sources.sql` | Companies, identifiers, aliases, sources |
| 0002 | `0002_events_and_evidence.sql` | Events, revisions, evidence |
| 0003 | `0003_metrics_research_and_outcomes.sql` | Metrics and research |
| 0004 | `0004_media_operations_watchlist.sql` | Media, operations, watchlist |
| 0005 | `0005_dataset_loads.sql` | Dataset loads and quotas |
| 0006 | `0006_collection_engine.sql` | Collection engine |
| 0007 | `0007_intelligence_engine.sql` | `llm_calls`, `event_extractions` (append-only), clusters |
| 0008 | `0008_exposure_mapping.sql` | Exposure candidates, relationships, reviews |
| 0009 | `0009_impact_assessments.sql` | Impact assessments |
| 0010 | `0010_market_ohlcv.sql` | Market bars |
| 0011 | `0011_financial_documents.sql` | Financial documents, reports, line items |
| 0012 | `0012_assessments_and_valuations.sql` | Dimension assessments, valuations |
| 0013 | `0013_macro_series.sql` | Macro series and vintages |
| 0014 | `0014_validation_and_reports.sql` | Validation runs, report snapshots |

Rules [SRC `database/migrate.py`]: contiguous versions from 1; SHA-256 of each file recorded in `schema_migrations`; destructive statements refused in migration files; an applied version whose checksum changes stops the runner.

## 2. The version-11 collision (historical facts)
- Production ledger version 11, before remediation: `extraction_reviews`, checksum `a9b55ef930503e72fa6cf8ff86f9611683f76c4c60767cdd6ccbb582ebc04c39` [PROD-RO 2026-11-09, REPORTED in PR #52].
- It was written by the technical repository's migration (technical `fundamental_engine/migrations/0011_extraction_reviews.sql`, PR #65 [GIT]).
- The news repository's version 11 is `0011_financial_documents.sql`. These are different migrations. Never treat them as equivalent.
- Objects created by the foreign migration: `extraction_reviews`, `ix_extraction_reviews_extraction`, `trg_extraction_reviews_no_update`, `trg_extraction_reviews_no_delete`, `v_review_queue` [REPORTED, PR #52].
- The news runner refused to run while the foreign version existed.

## 3. A2 remediation (PR #52, merged) [GIT, SRC]
- Script: `scripts/remediate_migration_collision_a2.py`. Dry run by default. `--execute` requires `--confirm retire-migration-11`, a 64-hex `--backup-sha256`, `--approval-id`, and `--target`.
- One transaction. Guard: a permanent `_a2_guard` table with a CHECK that fails unless: `extraction_reviews` has 0 rows; version 11 has exact name and checksum; `MAX(version)` is 11. A failed check rolls back the whole transaction.
- Post-COMMIT verification reports `remediated_check_failed` and never "verified", with `--verify-only` as the fresh-process recovery.
- Tests: `tests/test_turso_disposable_a2_rehearsal.py`. SQLite leg always runs. Turso leg runs only against a fresh disposable database. Result reported on 2026-11-09: 26 passed on Turso (Option B guard) [REPORTED].
- Production execution: performed on 2026-11-09 under explicit owner approval, verified [REPORTED plus PROD-RO ledger check 2026-11-10].
- Backups (SHA-256): before A2 `2085ec5101dde7dafb4f33718b7f0a9ebb710e3c571cd223fac1146c53cd823e`; after A2 `34b539f6a208449185fbf6614eb89a024b4fb0c6bea183edfab92283bc0ba40e` [REPORTED]. Their storage location is the owner's [UNKNOWN to this package].

## 4. Migrations 0011–0014 (news)
Applied to production on 2026-11-09 under owner instruction [REPORTED]. Read-only check 2026-11-10: versions 1–14 present; 11 is `financial_documents` [PROD-RO]. Row counts of tables created by 0011–0014 were not checked [REPORTED]. No module using them is activated [REPORTED].

## 5. Procedure for any future migration (required)
1. Write the migration in the news repository only, with the next free version.
2. Never edit an applied migration. Never renumber. Never edit a checksum in `schema_migrations`.
3. Run `python -m database.migrate --dry-run` against a disposable database. Then run the migration tests (`tests/test_turso_disposable_*`).
4. Take a backup with a verified SHA-256 (`docs/OPERATIONS_RUNBOOK.md` section 1).
5. Pre-flight: read-only ledger, object list and row counts, with a fresh read-only token.
6. Obtain explicit owner approval with an approval ID. Only then run against production.
7. Post-flight: ledger, `integrity.check`, foreign-key check and count digest. Record the result in the docs.

## 6. Turso specifics [REPORTED, verified by the A2 Turso rehearsal]
- A failing statement inside one HTTP batch rolls back the batch.
- A TEMP table was not used; the permanent guard table was used because its behaviour on Turso was proven.
- Per-run read budget defaults: 50,000 rows read, 5,000 written, 2,000 requests (`PSXNI_DB_MAX_*`). Budget exhaustion after COMMIT must never be reported as success.

## 7. Never do
- Apply a migration from the technical repository to the news database.
- Use the old production credential, which was invalidated [PROD-RO 2026-11-10].
- Delete or modify production candidate, OHLCV or source rows without a backup, rehearsal, pre-flight, post-flight and approval.
- Re-run `--execute` after a COMMIT. Use `--verify-only`.
