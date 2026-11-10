# Extractor-version schema update (DRAFT, not applied, not in the migrations directory)

Status: design only. Not executed on any database. Requires the owner's decision (section 5) before it becomes a
migration. Stored here, outside `database/archive_migrations/`, so the migration runner and the approval package
are unaffected.

## 1. The problem
`archive_line_items` is unique on (report_sha256, statement, line_no, column_period_end, consolidation). Re-running
extraction with a DIFFERENT extractor (a new pdfplumber rule, a fixed table parser) would either collide with the
first run (refused, the new result is lost) or, if the key were widened silently, store two incompatible versions
with no way to tell them apart. Neither is acceptable.

`archive_document_registry` identifies a document by its bytes, which is correct. But a document is not
re-registered when its extraction changes, so the registry has no place to record which extractor produced which
evidence.

## 2. Design
- Every extraction run gets an identity: `extractor_version` (a string such as `pdfplumber-0.11.10/rules-2026.11.1`)
  and a `run_id`. Both are recorded once per run, append-only.
- Line items, notes and reconciliation results carry `extractor_version`. The natural key becomes
  (report_sha256, extractor_version, statement, line_no, column_period_end, consolidation).
- Re-running the SAME extractor version on the same bytes is idempotent: the rows already exist, nothing is added.
- A DIFFERENT extractor version adds a second, separate set of rows. Nothing is overwritten. Reconciliation and
  review refer to one run at a time, so the two sets never silently mix.
- The processing event log records `extractor_version` on every status change.
- Review rows (`archive_line_reviews`) reference a `line_id`, which is unique per run, so reviews stay bound to
  the run they reviewed.

## 3. Exact schema (proposed)
```sql
CREATE TABLE archive_extraction_runs (
    run_id            INTEGER PRIMARY KEY,
    report_sha256     TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    extractor_version TEXT NOT NULL CHECK (length(extractor_version) BETWEEN 1 AND 120),
    started_at_utc    TEXT NOT NULL,
    UNIQUE (report_sha256, extractor_version)
);
-- archive_line_items: add run_id INTEGER NOT NULL REFERENCES archive_extraction_runs(run_id);
-- replace UNIQUE(report_sha256, statement, line_no, column_period_end, consolidation)
--         with UNIQUE(run_id, statement, line_no, column_period_end, consolidation).
-- archive_notes and archive_reconciliation: the same run_id column and key.
-- archive_processing_events: add run_id (nullable for document-level events).
```

## 4. Migration constraints that shape the approach
- SQLite cannot alter a UNIQUE constraint in place. Changing the key requires a table rebuild.
- The migration runner refuses `DROP TABLE` and `ALTER ... DROP`. A rebuild therefore cannot be a migration
  applied to a database that already holds rows.
- While the archive is EMPTY (the current state, and the state the approval package describes), the cleanest path
  is to revise migrations 0003 and 0004 BEFORE the first application. Their checksums then change, so the approval
  package must be regenerated. Nothing has been applied, so no ledger is affected.
- After the first application, the same change becomes a new migration that creates a new table, copies rows, and
  is applied with a reviewed rebuild procedure, which cannot be done with the current runner's destructive-statement
  refusal in place. That path would need its own approval.

## 5. Decision needed
1. Revise 0003 and 0004 now, while the archive is empty (recommended), then regenerate the approval package and
   re-run the disposable suite against the revised files. OR
2. Keep 0003 and 0004 and accept that a later extractor change requires a reviewed rebuild procedure.

## 6. Verification plan once approved
- Live disposable suite: same extractor twice is idempotent; a second extractor version adds rows and leaves the
  first set unchanged; reviews stay bound to their run; foreign keys enforced on `run_id`.
- Offline: the reprocessing pipeline keyed by (sha, extractor_version) produces no duplicate rows across runs.
