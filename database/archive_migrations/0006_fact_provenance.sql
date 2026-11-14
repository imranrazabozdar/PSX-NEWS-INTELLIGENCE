-- Archive database, migration 0006: an explicit source SHA-256 on every stored fact and reconciliation result.
-- Additive only. Migrations 0001-0005 are NOT modified.
--
-- Before this migration, a versioned fact carried its source hash as document_id (a foreign key to the document
-- registry) and a reconciliation result reached it only through its run. Both now carry report_sha256 explicitly.
-- Rows stored before this migration keep report_sha256 NULL; their hash is still document_id (see the view).
-- Insert triggers refuse a fact or result whose hash does not match its document or run.

ALTER TABLE archive_line_items_v2
    ADD COLUMN report_sha256 TEXT CHECK (report_sha256 IS NULL OR length(report_sha256) = 64)
    REFERENCES archive_document_registry(report_sha256);

ALTER TABLE archive_reconciliation_v2
    ADD COLUMN report_sha256 TEXT CHECK (report_sha256 IS NULL OR length(report_sha256) = 64)
    REFERENCES archive_document_registry(report_sha256);

CREATE TRIGGER trg_lines_v2_sha_required BEFORE INSERT ON archive_line_items_v2
WHEN NEW.report_sha256 IS NULL OR NEW.report_sha256 <> NEW.document_id
BEGIN SELECT RAISE(ABORT, 'a versioned line item must carry the SHA-256 of its document'); END;

CREATE TRIGGER trg_recon_v2_sha_required BEFORE INSERT ON archive_reconciliation_v2
WHEN NEW.report_sha256 IS NULL
     OR NEW.report_sha256 IS NOT (SELECT r.report_sha256 FROM archive_extraction_runs r WHERE r.run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'a reconciliation result must carry the SHA-256 of its run document'); END;

CREATE VIEW v_fact_provenance AS
SELECT l.line_id,
       COALESCE(l.report_sha256, l.document_id) AS report_sha256,
       l.run_id,
       l.extractor_version,
       l.statement_type,
       l.canonical_code,
       l.column_period_end,
       l.consolidation,
       l.pdf_page_number,
       l.line_item_name
FROM archive_line_items_v2 l;
