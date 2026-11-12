-- Archive database, migration 0007: the full status vocabulary, stored per statement and per fact. Additive only.
-- Migrations 0001-0006 are NOT modified. archive_reconciliation_v2 keeps its four legacy codes (its CHECK cannot be
-- changed without a rebuild); the statement table below carries the full vocabulary and is the stored status.

CREATE TABLE archive_status_codes (
    code     TEXT PRIMARY KEY CHECK (code IN ('reconciled','reconciled_with_rounding','unreconciled',
                                              'insufficient_data','not_verifiable_from_disclosure',
                                              'unmapped','requires_review')),
    meaning  TEXT NOT NULL
);

INSERT INTO archive_status_codes(code, meaning) VALUES
    ('reconciled', 'the identity holds exactly, from the disclosure'),
    ('reconciled_with_rounding', 'the identity holds within the printed rounding allowance'),
    ('unreconciled', 'the identity fails: the discrepancy is stored and disclosed'),
    ('insufficient_data', 'an input needed for the identity is not printed or not extracted'),
    ('not_verifiable_from_disclosure', 'the disclosure does not let the figure or classification be proven'),
    ('unmapped', 'a printed line has no canonical mapping'),
    ('requires_review', 'extracted, but a person must confirm it (layout or scope ambiguity)');

CREATE TABLE archive_statement_status (
    status_id         INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES archive_extraction_runs(run_id),
    report_sha256     TEXT NOT NULL REFERENCES archive_document_registry(report_sha256)
                      CHECK (length(report_sha256) = 64),
    statement_type    TEXT NOT NULL CHECK (statement_type IN ('IS','BS','CF','EQ','OCI')),
    consolidation     TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    column_period_end TEXT NOT NULL CHECK (column_period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status            TEXT NOT NULL REFERENCES archive_status_codes(code),
    reason            TEXT NOT NULL,
    evidence_page     INTEGER CHECK (evidence_page IS NULL OR evidence_page >= 1),
    recorded_at_utc   TEXT NOT NULL,
    UNIQUE (run_id, statement_type, consolidation, column_period_end)
);

CREATE TABLE archive_fact_status (
    fact_status_id    INTEGER PRIMARY KEY,
    line_id           INTEGER NOT NULL UNIQUE REFERENCES archive_line_items_v2(line_id),
    report_sha256     TEXT NOT NULL CHECK (length(report_sha256) = 64),
    status            TEXT NOT NULL REFERENCES archive_status_codes(code),
    reason            TEXT NOT NULL,
    recorded_at_utc   TEXT NOT NULL
);

CREATE TRIGGER trg_statement_status_sha BEFORE INSERT ON archive_statement_status
WHEN NEW.report_sha256 IS NOT (SELECT r.report_sha256 FROM archive_extraction_runs r WHERE r.run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'a statement status must carry the SHA-256 of its run document'); END;
CREATE TRIGGER trg_statement_status_no_update BEFORE UPDATE ON archive_statement_status
BEGIN SELECT RAISE(ABORT, 'statement statuses are immutable'); END;
CREATE TRIGGER trg_statement_status_no_delete BEFORE DELETE ON archive_statement_status
BEGIN SELECT RAISE(ABORT, 'statement statuses are append-only'); END;

CREATE TRIGGER trg_fact_status_sha BEFORE INSERT ON archive_fact_status
WHEN NEW.report_sha256 IS NOT (SELECT COALESCE(l.report_sha256, l.document_id)
                               FROM archive_line_items_v2 l WHERE l.line_id = NEW.line_id)
BEGIN SELECT RAISE(ABORT, 'a fact status must carry the SHA-256 of its fact'); END;
CREATE TRIGGER trg_fact_status_no_update BEFORE UPDATE ON archive_fact_status
BEGIN SELECT RAISE(ABORT, 'fact statuses are immutable'); END;
CREATE TRIGGER trg_fact_status_no_delete BEFORE DELETE ON archive_fact_status
BEGIN SELECT RAISE(ABORT, 'fact statuses are append-only'); END;
