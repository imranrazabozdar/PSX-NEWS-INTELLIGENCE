-- Archive database, migration 0002: parsed material disclosures (structured JSON, never binary).
-- Append-only. The raw PDF stays in the local vault; this table keeps only its SHA-256 as a reference.
-- payload_json is bounded and must be valid JSON, so a malformed or oversized payload cannot be stored.

CREATE TABLE archive_disclosures (
    disclosure_sha256 TEXT PRIMARY KEY CHECK (length(disclosure_sha256) = 64),
    company_id        TEXT NOT NULL,        -- logical reference to the operational companies table
    kind              TEXT NOT NULL CHECK (kind IN ('financial_statement','material_disclosure')),
    published_at_utc  TEXT NOT NULL,
    title             TEXT NOT NULL,
    payload_json      TEXT NOT NULL CHECK (json_valid(payload_json) AND length(payload_json) <= 65536),
    pdf_sha256        TEXT CHECK (pdf_sha256 IS NULL OR length(pdf_sha256) = 64),
    archived_at_utc   TEXT NOT NULL
);
CREATE INDEX ix_archive_disclosures_company ON archive_disclosures(company_id, published_at_utc);
CREATE TRIGGER trg_archive_disclosures_no_delete BEFORE DELETE ON archive_disclosures
BEGIN SELECT RAISE(ABORT, 'archive_disclosures is append-only'); END;
CREATE TRIGGER trg_archive_disclosures_no_update BEFORE UPDATE ON archive_disclosures
BEGIN SELECT RAISE(ABORT, 'archive disclosures are immutable'); END;
