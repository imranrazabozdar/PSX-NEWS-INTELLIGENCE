-- 0012: fundamentals dimension assessments and valuations (master plan M3 / M5). Additive only.
-- Rows are versioned by engine_version and never updated: a new run writes new rows.

CREATE TABLE dimension_assessments (
    assessment_id    INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    dimension        TEXT NOT NULL CHECK (dimension IN ('A','B','C','D','E','F','G','H','I','J','K','L')),
    as_of_date       TEXT NOT NULL,
    period_end       TEXT,
    scope            TEXT,
    data_state       TEXT NOT NULL CHECK (data_state IN ('ok','partial','insufficient_data','not_applicable')),
    band             TEXT,                 -- NULL until the owner sets thresholds (U9)
    components_json  TEXT NOT NULL CHECK (json_valid(components_json)),
    evidence_json    TEXT NOT NULL CHECK (json_valid(evidence_json)),
    engine_version   TEXT NOT NULL,
    created_at_utc   TEXT NOT NULL,
    UNIQUE (company_id, dimension, as_of_date, engine_version)
);
CREATE INDEX ix_dim_assess ON dimension_assessments(dimension, as_of_date);
CREATE TRIGGER trg_dim_assess_no_update BEFORE UPDATE ON dimension_assessments
BEGIN SELECT RAISE(ABORT, 'dimension_assessments are immutable'); END;

CREATE TABLE valuations (
    valuation_id     INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    as_of_date       TEXT NOT NULL,
    method           TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('ok','not_applicable','insufficient_data','needs_assumptions')),
    inputs_json      TEXT NOT NULL CHECK (json_valid(inputs_json)),
    assumptions_json TEXT NOT NULL CHECK (json_valid(assumptions_json)),
    conservative     REAL,
    base             REAL,
    optimistic       REAL,
    sensitivity_json TEXT CHECK (sensitivity_json IS NULL OR json_valid(sensitivity_json)),
    missing_json     TEXT NOT NULL CHECK (json_valid(missing_json)),
    engine_version   TEXT NOT NULL,
    created_at_utc   TEXT NOT NULL,
    CHECK (state = 'ok' OR (conservative IS NULL AND base IS NULL AND optimistic IS NULL)),
    UNIQUE (company_id, as_of_date, method, engine_version)
);
CREATE INDEX ix_valuations ON valuations(company_id, as_of_date);
CREATE TRIGGER trg_valuations_no_update BEFORE UPDATE ON valuations
BEGIN SELECT RAISE(ABORT, 'valuations are immutable'); END;
