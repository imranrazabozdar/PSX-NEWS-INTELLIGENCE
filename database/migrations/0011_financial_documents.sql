-- 0011: financial documents (master plan M2; MASTER_DATABASE_DESIGN.md section 2). Additive only.
-- A report is one financial document for one period and scope. Line items keep the raw label, page and
-- extraction method; canonical values are promoted to financial_metrics only after mapping and
-- reconciliation. Line items, corporate actions and approved mappings are append-only.
-- One document holding consolidated and unconsolidated statements is recorded as one source item per
-- scope (same document SHA-256, linked as duplicate content), because financial_metrics (0003) is unique on
-- source_item_id without scope.

CREATE TABLE financial_reports (
    report_id        INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    source_item_id   INTEGER NOT NULL REFERENCES source_items(source_item_id),
    doc_type         TEXT NOT NULL CHECK (doc_type IN ('annual','half_yearly','quarterly','nine_month')),
    period_end       TEXT NOT NULL CHECK (period_end GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    period_months    INTEGER NOT NULL CHECK (period_months IN (3,6,9,12)),
    scope            TEXT NOT NULL CHECK (scope IN ('consolidated','unconsolidated')),
    currency         TEXT NOT NULL,
    unit_scale       INTEGER NOT NULL CHECK (unit_scale IN (1,1000,1000000,1000000000)),
    audit_status     TEXT NOT NULL CHECK (audit_status IN ('audited','reviewed','unaudited','unknown')),
    auditor_opinion  TEXT CHECK (auditor_opinion IS NULL OR auditor_opinion IN
                       ('unmodified','unmodified_with_emphasis','qualified','adverse','disclaimer')),
    filed_at_utc     TEXT,
    restates_report_id INTEGER REFERENCES financial_reports(report_id),
    framework        TEXT NOT NULL CHECK (framework IN ('bank','insurer','corporate')),
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('manual','text','pdf_text','ocr')),
    extraction_status TEXT NOT NULL DEFAULT 'extracted'
                       CHECK (extraction_status IN ('extracted','reconciled','needs_review','failed')),
    created_at_utc   TEXT NOT NULL,
    UNIQUE (company_id, doc_type, period_end, scope, source_item_id)
);
CREATE INDEX ix_fin_reports_company ON financial_reports(company_id, period_end);

CREATE TABLE financial_line_items (
    line_id          INTEGER PRIMARY KEY,
    report_id        INTEGER NOT NULL REFERENCES financial_reports(report_id),
    statement        TEXT NOT NULL CHECK (statement IN ('IS','BS','CF','EQ','note')),
    line_no          INTEGER NOT NULL CHECK (line_no >= 1),   -- order within the statement: labels repeat
    raw_label        TEXT NOT NULL,
    canonical_code   TEXT,
    column_period_end TEXT NOT NULL,
    is_comparative   INTEGER NOT NULL DEFAULT 0 CHECK (is_comparative IN (0,1)),
    value            REAL,                 -- NULL means not reported / blank: never zero
    value_state      TEXT NOT NULL CHECK (value_state IN ('reported','not_reported','unreadable')),
    page             INTEGER,
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('manual','text','pdf_text','ocr')),
    confidence       REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    review_status    TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','accepted','rejected')),
    CHECK ((value IS NULL) = (value_state <> 'reported')),
    UNIQUE (report_id, statement, line_no, column_period_end)
);
CREATE INDEX ix_fin_lines_report ON financial_line_items(report_id, statement);
CREATE INDEX ix_fin_lines_code ON financial_line_items(canonical_code);
CREATE TRIGGER trg_fin_lines_no_delete BEFORE DELETE ON financial_line_items
BEGIN SELECT RAISE(ABORT, 'financial_line_items is append-only'); END;
CREATE TRIGGER trg_fin_lines_values_fixed BEFORE UPDATE OF value, value_state, raw_label, column_period_end
    ON financial_line_items
BEGIN SELECT RAISE(ABORT, 'extracted values are immutable; record a restatement instead'); END;

CREATE TABLE account_mappings (
    mapping_id       INTEGER PRIMARY KEY,
    framework        TEXT NOT NULL CHECK (framework IN ('bank','insurer','corporate')),
    raw_label_normalised TEXT NOT NULL,
    statement        TEXT NOT NULL CHECK (statement IN ('IS','BS','CF','EQ','note')),
    canonical_code   TEXT NOT NULL,
    version          INTEGER NOT NULL CHECK (version >= 1),
    approved_by      TEXT NOT NULL,
    approved_at_utc  TEXT NOT NULL,
    UNIQUE (framework, statement, raw_label_normalised, version)
);
CREATE TRIGGER trg_account_mappings_no_update BEFORE UPDATE ON account_mappings
BEGIN SELECT RAISE(ABORT, 'account_mappings are versioned: add a new version'); END;

CREATE TABLE corporate_actions (
    action_id        INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    action_type      TEXT NOT NULL CHECK (action_type IN ('cash_dividend','bonus','split','rights','consolidation')),
    ex_date          TEXT NOT NULL CHECK (ex_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    record_date      TEXT,
    -- bonus / rights: NEW shares per existing share (0.25 = 1 for 4);
    -- split / consolidation: shares held AFTER per share held before (2 = 2-for-1 split, 0.1 = 1-for-10)
    ratio            REAL CHECK (ratio IS NULL OR ratio > 0),
    amount_per_share REAL CHECK (amount_per_share IS NULL OR amount_per_share >= 0),
    subscription_price REAL CHECK (subscription_price IS NULL OR subscription_price > 0),
    currency         TEXT,
    source_item_id   INTEGER NOT NULL REFERENCES source_items(source_item_id),
    status           TEXT NOT NULL DEFAULT 'announced' CHECK (status IN ('announced','confirmed','cancelled')),
    recorded_at_utc  TEXT NOT NULL,
    CHECK (action_type <> 'cash_dividend' OR amount_per_share IS NOT NULL),
    CHECK (action_type NOT IN ('bonus','split','rights','consolidation') OR ratio IS NOT NULL),
    CHECK (action_type <> 'rights' OR subscription_price IS NOT NULL),
    UNIQUE (company_id, action_type, ex_date, source_item_id)
);
CREATE INDEX ix_corp_actions ON corporate_actions(company_id, ex_date);
CREATE TRIGGER trg_corp_actions_no_delete BEFORE DELETE ON corporate_actions
BEGIN SELECT RAISE(ABORT, 'corporate_actions is append-only; cancel by status'); END;

ALTER TABLE financial_metrics ADD COLUMN report_id INTEGER REFERENCES financial_reports(report_id);
ALTER TABLE financial_metrics ADD COLUMN scope TEXT CHECK (scope IS NULL OR scope IN ('consolidated','unconsolidated'));
