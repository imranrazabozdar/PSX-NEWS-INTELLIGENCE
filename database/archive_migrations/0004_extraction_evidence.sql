-- Archive database, migration 0004: extracted line items, notes, reconciliation results and reviews.
-- Parent is archive_document_registry (0003), NOT archive_reports, because archive_reports only holds reconciled
-- summaries and extraction records must exist before they are reconciled.
-- All tables are append-only. Original extracted values are never changed; reviews are separate rows.
-- Foreign keys are declared for documentation and are enforced by the repository; enforcement depends on the
-- connection's PRAGMA foreign_keys and is verified in the disposable integration test, not assumed.

CREATE TABLE archive_line_items (
    line_id          INTEGER PRIMARY KEY,
    report_sha256    TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    statement        TEXT NOT NULL CHECK (statement IN ('IS','BS','CF','EQ','OCI','NOTE')),
    line_no          INTEGER NOT NULL CHECK (line_no >= 1),       -- order within the statement: labels repeat
    raw_label        TEXT NOT NULL,
    canonical_code   TEXT,                                       -- NULL until mapped
    column_period_end TEXT NOT NULL CHECK (column_period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    is_comparative   INTEGER NOT NULL DEFAULT 0 CHECK (is_comparative IN (0,1)),
    value            REAL,                                       -- NULL means not reported: never zero
    value_state      TEXT NOT NULL CHECK (value_state IN ('reported','not_reported','unreadable')),
    currency         TEXT NOT NULL,
    unit_scale       INTEGER NOT NULL CHECK (unit_scale IN (1,1000,1000000,1000000000)),
    consolidation    TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    page             INTEGER CHECK (page IS NULL OR page >= 1),
    note_ref         TEXT,                                       -- e.g. '12' or '12(a)' as printed
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('manual','pdf_text','pdf_table','ocr','structured_json')),
    confidence       REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK ((value IS NULL) = (value_state <> 'reported')),
    UNIQUE (report_sha256, statement, line_no, column_period_end, consolidation)
);
CREATE INDEX ix_archive_lines_code ON archive_line_items(report_sha256, canonical_code);

CREATE TABLE archive_notes (
    note_id          INTEGER PRIMARY KEY,
    report_sha256    TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    note_no          TEXT NOT NULL,
    note_title       TEXT NOT NULL,
    page             INTEGER CHECK (page IS NULL OR page >= 1),
    body_json        TEXT NOT NULL CHECK (json_valid(body_json) AND length(body_json) <= 65536),
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('manual','pdf_text','pdf_table','ocr','structured_json')),
    UNIQUE (report_sha256, note_no)
);

CREATE TABLE archive_reconciliation (
    check_id         INTEGER PRIMARY KEY,
    report_sha256    TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    check_name       TEXT NOT NULL,                              -- e.g. balance_sheet, cash_flow, profit
    column_period_end TEXT NOT NULL,
    consolidation    TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    reported         REAL,
    expected         REAL,
    difference       REAL,
    tolerance        REAL NOT NULL CHECK (tolerance >= 0),
    result           TEXT NOT NULL CHECK (result IN ('pass','fail','not_checkable')),
    recorded_at_utc  TEXT NOT NULL,
    UNIQUE (report_sha256, check_name, column_period_end, consolidation)
);

CREATE TABLE archive_line_reviews (
    review_id        INTEGER PRIMARY KEY,
    line_id          INTEGER NOT NULL REFERENCES archive_line_items(line_id),
    decision         TEXT NOT NULL CHECK (decision IN ('accepted','rejected','corrected')),
    corrected_value  REAL,                                       -- the reviewed value; the original stays in line_items
    reviewer         TEXT NOT NULL,
    note             TEXT NOT NULL,
    reviewed_at_utc  TEXT NOT NULL,
    CHECK ((decision = 'corrected') = (corrected_value IS NOT NULL))
);

CREATE TRIGGER trg_archive_lines_no_update BEFORE UPDATE ON archive_line_items
BEGIN SELECT RAISE(ABORT, 'archive line items are immutable; record a review instead'); END;
CREATE TRIGGER trg_archive_lines_no_delete BEFORE DELETE ON archive_line_items
BEGIN SELECT RAISE(ABORT, 'archive line items are append-only'); END;
CREATE TRIGGER trg_archive_notes_no_update BEFORE UPDATE ON archive_notes
BEGIN SELECT RAISE(ABORT, 'archive notes are immutable'); END;
CREATE TRIGGER trg_archive_notes_no_delete BEFORE DELETE ON archive_notes
BEGIN SELECT RAISE(ABORT, 'archive notes are append-only'); END;
CREATE TRIGGER trg_archive_recon_no_update BEFORE UPDATE ON archive_reconciliation
BEGIN SELECT RAISE(ABORT, 'reconciliation results are immutable; recompute into a new document version'); END;
CREATE TRIGGER trg_archive_recon_no_delete BEFORE DELETE ON archive_reconciliation
BEGIN SELECT RAISE(ABORT, 'reconciliation results are append-only'); END;
CREATE TRIGGER trg_archive_reviews_no_update BEFORE UPDATE ON archive_line_reviews
BEGIN SELECT RAISE(ABORT, 'reviews are immutable'); END;
CREATE TRIGGER trg_archive_reviews_no_delete BEFORE DELETE ON archive_line_reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
