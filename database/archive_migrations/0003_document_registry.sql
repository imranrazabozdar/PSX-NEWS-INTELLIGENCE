-- Archive database, migration 0003: document registry and processing history.
-- One row per original document (identified by the SHA-256 of its bytes). The PDF itself stays in the local
-- vault; this row keeps only its hash, file name and source metadata. Append-only.
-- Re-processing the same bytes returns the existing row (no duplicate). A new version of a document for the same
-- company, period and consolidation basis is a new row with document_version + 1, never an overwrite.

CREATE TABLE archive_document_registry (
    report_sha256     TEXT PRIMARY KEY CHECK (length(report_sha256) = 64),
    psx_symbol        TEXT NOT NULL CHECK (length(psx_symbol) BETWEEN 1 AND 12),
    company_id        TEXT NOT NULL,                             -- logical reference to companies (operational DB)
    doc_type          TEXT NOT NULL CHECK (doc_type IN ('annual','half_yearly','quarterly','nine_month')),
    financial_year    INTEGER NOT NULL CHECK (financial_year BETWEEN 1990 AND 2100),
    period_end        TEXT NOT NULL CHECK (period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    consolidation     TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated','mixed','unknown')),
    audit_status      TEXT NOT NULL CHECK (audit_status IN ('audited','reviewed','unaudited','unknown')),
    publication_date  TEXT CHECK (publication_date IS NULL OR publication_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    original_filename TEXT NOT NULL CHECK (original_filename NOT LIKE '%/%' AND original_filename NOT LIKE '%\%'),
    vault_ref         TEXT NOT NULL CHECK (vault_ref NOT LIKE '%/%' AND vault_ref NOT LIKE '%\%'),
    source_id         TEXT NOT NULL,
    source_url        TEXT,
    retrieved_at_utc  TEXT NOT NULL,
    document_version  INTEGER NOT NULL DEFAULT 1 CHECK (document_version >= 1),
    registered_at_utc TEXT NOT NULL,
    UNIQUE (company_id, doc_type, period_end, consolidation, document_version)
);
CREATE INDEX ix_archive_registry_symbol ON archive_document_registry(psx_symbol, period_end);

CREATE TABLE archive_processing_events (
    event_id          INTEGER PRIMARY KEY,
    report_sha256     TEXT NOT NULL REFERENCES archive_document_registry(report_sha256),
    status            TEXT NOT NULL CHECK (status IN ('registered','extracting','extracted','reconciled',
                                                      'needs_review','failed')),
    detail            TEXT NOT NULL,
    recorded_at_utc   TEXT NOT NULL
);
CREATE INDEX ix_archive_processing_doc ON archive_processing_events(report_sha256, event_id);

CREATE TRIGGER trg_archive_registry_no_update BEFORE UPDATE ON archive_document_registry
BEGIN SELECT RAISE(ABORT, 'the document registry is immutable'); END;
CREATE TRIGGER trg_archive_registry_no_delete BEFORE DELETE ON archive_document_registry
BEGIN SELECT RAISE(ABORT, 'the document registry is append-only'); END;
CREATE TRIGGER trg_archive_events_no_update BEFORE UPDATE ON archive_processing_events
BEGIN SELECT RAISE(ABORT, 'processing events are immutable'); END;
CREATE TRIGGER trg_archive_events_no_delete BEFORE DELETE ON archive_processing_events
BEGIN SELECT RAISE(ABORT, 'processing events are append-only'); END;
