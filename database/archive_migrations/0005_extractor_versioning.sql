-- Archive database, migration 0005: extractor versioning and reprocessing.
-- Migrations 0001-0004 are NOT modified. SQLite cannot remove a table-level UNIQUE constraint without rebuilding
-- the table, and the runner refuses DROP, so the versioned records live in NEW tables. The 0004 tables stay in
-- place (empty while the archive is empty) and new code must not write to them.
--
-- One extraction run = one (document, extractor_version). Re-running the same extractor on the same bytes reuses
-- the run, so the composite keys reject nothing new: idempotent. A different extractor version creates a new run,
-- and its rows never collide with, or overwrite, another run's rows.
-- Append-only throughout. Numbers are stored as extracted; missing values are NULL, never zero.

CREATE TABLE archive_extraction_runs (
    run_id            INTEGER PRIMARY KEY,
    report_sha256     TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    extractor_version TEXT NOT NULL CHECK (length(extractor_version) BETWEEN 1 AND 120),
    started_at_utc    TEXT NOT NULL,
    UNIQUE (report_sha256, extractor_version),
    UNIQUE (run_id, extractor_version)
);

CREATE TABLE archive_line_items_v2 (
    line_id           INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL,
    extractor_version TEXT NOT NULL,
    document_id       TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    symbol            TEXT NOT NULL CHECK (length(symbol) BETWEEN 1 AND 12),
    period_end        TEXT NOT NULL CHECK (period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    statement_type    TEXT NOT NULL CHECK (statement_type IN ('IS','BS','CF','EQ','OCI','NOTE')),
    line_no           INTEGER NOT NULL CHECK (line_no >= 1),
    line_item_name    TEXT NOT NULL,
    canonical_code    TEXT,
    column_period_end TEXT NOT NULL CHECK (column_period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    is_comparative    INTEGER NOT NULL DEFAULT 0 CHECK (is_comparative IN (0,1)),
    reported_amount   REAL,
    value_state       TEXT NOT NULL CHECK (value_state IN ('reported','not_reported','unreadable')),
    restated_flag     INTEGER NOT NULL DEFAULT 0 CHECK (restated_flag IN (0,1)),
    currency          TEXT NOT NULL,
    unit_scale        INTEGER NOT NULL CHECK (unit_scale IN (1,1000,1000000,1000000000)),
    consolidation     TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    pdf_page_number   INTEGER CHECK (pdf_page_number IS NULL OR pdf_page_number >= 1),
    note_ref          TEXT,
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('manual','pdf_text','pdf_table','ocr','structured_json')),
    confidence        REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    processed_at_utc  TEXT NOT NULL,
    CHECK ((reported_amount IS NULL) = (value_state <> 'reported')),
    FOREIGN KEY (run_id, extractor_version) REFERENCES archive_extraction_runs(run_id, extractor_version),
    UNIQUE (run_id, statement_type, line_no, column_period_end, consolidation)
);
CREATE INDEX ix_archive_lines_v2_doc ON archive_line_items_v2(document_id, statement_type);

CREATE TABLE archive_reconciliation_v2 (
    recon_id          INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES archive_extraction_runs(run_id),
    check_name        TEXT NOT NULL,
    column_period_end TEXT NOT NULL CHECK (column_period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    consolidation     TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    reported          REAL,
    expected          REAL,
    discrepancy       REAL,
    tolerance         REAL NOT NULL CHECK (tolerance >= 0),
    status            TEXT NOT NULL CHECK (status IN ('RECONCILED','RECONCILED_WITH_ROUNDING','UNRECONCILED','INSUFFICIENT_DATA')),
    recorded_at_utc   TEXT NOT NULL,
    UNIQUE (run_id, check_name, column_period_end, consolidation)
);

CREATE TABLE archive_document_files (
    report_sha256     TEXT PRIMARY KEY REFERENCES archive_document_registry(report_sha256),
    file_size_bytes   INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    stored_at_utc     TEXT NOT NULL
);

ALTER TABLE archive_processing_events ADD COLUMN run_id INTEGER REFERENCES archive_extraction_runs(run_id);

CREATE TRIGGER trg_runs_no_update BEFORE UPDATE ON archive_extraction_runs
BEGIN SELECT RAISE(ABORT, 'extraction runs are immutable'); END;
CREATE TRIGGER trg_runs_no_delete BEFORE DELETE ON archive_extraction_runs
BEGIN SELECT RAISE(ABORT, 'extraction runs are append-only'); END;
CREATE TRIGGER trg_lines_v2_no_update BEFORE UPDATE ON archive_line_items_v2
BEGIN SELECT RAISE(ABORT, 'versioned line items are immutable'); END;
CREATE TRIGGER trg_lines_v2_no_delete BEFORE DELETE ON archive_line_items_v2
BEGIN SELECT RAISE(ABORT, 'versioned line items are append-only'); END;
CREATE TRIGGER trg_recon_v2_no_update BEFORE UPDATE ON archive_reconciliation_v2
BEGIN SELECT RAISE(ABORT, 'versioned reconciliation results are immutable'); END;
CREATE TRIGGER trg_recon_v2_no_delete BEFORE DELETE ON archive_reconciliation_v2
BEGIN SELECT RAISE(ABORT, 'versioned reconciliation results are append-only'); END;
CREATE TRIGGER trg_files_no_update BEFORE UPDATE ON archive_document_files
BEGIN SELECT RAISE(ABORT, 'file records are immutable'); END;
CREATE TRIGGER trg_files_no_delete BEFORE DELETE ON archive_document_files
BEGIN SELECT RAISE(ABORT, 'file records are append-only'); END;
