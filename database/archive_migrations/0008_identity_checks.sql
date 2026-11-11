-- Archive database, migration 0008: reconciliation identities stored with their result and delta. Additive only.
-- Migrations 0001-0007 are NOT modified. Every identity result carries the source SHA-256 (insert trigger) and is
-- append-only. An exception is stored as UNRECONCILED with its delta; it is never dropped or forced to pass.

CREATE TABLE archive_identity_checks (
    identity_id       INTEGER PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES archive_extraction_runs(run_id),
    report_sha256     TEXT NOT NULL REFERENCES archive_document_registry(report_sha256)
                      CHECK (length(report_sha256) = 64),
    identity          TEXT NOT NULL CHECK (identity IN (
                          'assets_equal_liabilities_plus_equity',
                          'pbt_less_tax_equals_pat',
                          'pat_plus_oci_equals_total_comprehensive_income',
                          'opening_cash_plus_movement_equals_closing_cash',
                          'equity_closing_equals_balance_sheet_equity',
                          'oci_components_equal_printed_total')),
    consolidation     TEXT NOT NULL CHECK (consolidation IN ('consolidated','unconsolidated')),
    column_period_end TEXT NOT NULL CHECK (column_period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    left_value        REAL,
    right_value       REAL,
    delta             REAL,
    tolerance         REAL NOT NULL CHECK (tolerance >= 0),
    status            TEXT NOT NULL REFERENCES archive_status_codes(code),
    reason            TEXT NOT NULL,
    recorded_at_utc   TEXT NOT NULL,
    UNIQUE (run_id, identity, consolidation, column_period_end),
    CHECK ((left_value IS NULL OR right_value IS NULL) = (delta IS NULL)),
    CHECK (status <> 'reconciled' OR (delta IS NOT NULL AND abs(delta) <= tolerance))
);

CREATE TRIGGER trg_identity_sha BEFORE INSERT ON archive_identity_checks
WHEN NEW.report_sha256 IS NOT (SELECT r.report_sha256 FROM archive_extraction_runs r WHERE r.run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'an identity result must carry the SHA-256 of its run document'); END;
CREATE TRIGGER trg_identity_no_update BEFORE UPDATE ON archive_identity_checks
BEGIN SELECT RAISE(ABORT, 'identity results are immutable'); END;
CREATE TRIGGER trg_identity_no_delete BEFORE DELETE ON archive_identity_checks
BEGIN SELECT RAISE(ABORT, 'identity results are append-only'); END;
