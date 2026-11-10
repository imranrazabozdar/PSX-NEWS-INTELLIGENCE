-- Archive database, migration 0001: multi-year financial statement history.
-- Lives ONLY in the archive database (PSXNI_ARCHIVE_TURSO_URL). Its own ledger (schema_migrations) and its own
-- numbering: it never shares a sequence with database/migrations, which is how the 0011 collision happened.
-- Stores lightweight metadata and normalised tuples only. No binary content, no file paths.
-- company_id is a LOGICAL reference to the operational database's companies table. There is no cross-database
-- foreign key, so the archive never depends on operational tables existing.

CREATE TABLE archive_reports (
    report_sha256    TEXT PRIMARY KEY CHECK (length(report_sha256) = 64),  -- SHA-256 of the original PDF
    vault_ref        TEXT NOT NULL,        -- file name in the local vault (e.g. <sha>.pdf); never a path, never bytes
    company_id       TEXT NOT NULL,        -- logical reference to the operational companies table
    doc_type         TEXT NOT NULL CHECK (doc_type IN ('annual','half_yearly','quarterly','nine_month')),
    period_end       TEXT NOT NULL CHECK (period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    scope            TEXT NOT NULL CHECK (scope IN ('consolidated','unconsolidated')),
    currency         TEXT NOT NULL,
    unit_scale       INTEGER NOT NULL CHECK (unit_scale IN (1,1000,1000000,1000000000)),
    audit_status     TEXT NOT NULL,
    reconciliation   TEXT NOT NULL CHECK (reconciliation IN ('reconciled')),  -- only reconciled reports are archived
    archived_at_utc  TEXT NOT NULL
);
CREATE INDEX ix_archive_reports_company ON archive_reports(company_id, period_end);

-- The normalised multi-period tuple: (company_id, period_end_date, metric_name, value, unit), plus what is
-- needed to tell apart a restatement or a duplicate. Append-only.
CREATE TABLE archive_financial_tuples (
    tuple_id         INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL,
    period_end_date  TEXT NOT NULL CHECK (period_end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    period_type      TEXT NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','H1','H2','9M','FY','TTM')),
    scope            TEXT NOT NULL CHECK (scope IN ('consolidated','unconsolidated')),
    metric_name      TEXT NOT NULL,
    value            REAL NOT NULL,        -- already scaled to the stated unit; never NULL (not reported = no row)
    unit             TEXT NOT NULL,        -- currency, '%', 'shares', or '<currency>/share'
    currency         TEXT,
    basis            TEXT NOT NULL CHECK (basis IN ('reported','restated')),
    report_sha256    TEXT NOT NULL REFERENCES archive_reports(report_sha256),
    archived_at_utc  TEXT NOT NULL,
    UNIQUE (company_id, period_end_date, period_type, scope, metric_name, basis, report_sha256)
);
CREATE INDEX ix_archive_tuples_series ON archive_financial_tuples(company_id, scope, metric_name, period_end_date);

CREATE TRIGGER trg_archive_tuples_no_delete BEFORE DELETE ON archive_financial_tuples
BEGIN SELECT RAISE(ABORT, 'archive_financial_tuples is append-only'); END;
CREATE TRIGGER trg_archive_tuples_no_update BEFORE UPDATE ON archive_financial_tuples
BEGIN SELECT RAISE(ABORT, 'archive tuples are immutable; record a restatement instead'); END;
CREATE TRIGGER trg_archive_reports_no_delete BEFORE DELETE ON archive_reports
BEGIN SELECT RAISE(ABORT, 'archive_reports is append-only'); END;
CREATE TRIGGER trg_archive_reports_no_update BEFORE UPDATE ON archive_reports
BEGIN SELECT RAISE(ABORT, 'archive reports are immutable'); END;
