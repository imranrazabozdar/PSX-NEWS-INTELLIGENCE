-- 0008: Phase 4 company exposure mapping (additive only).
-- Company relationships with provenance and effective dates, exposure candidates (one per
-- event, company, category and mechanism), append-only candidate revisions and append-only
-- human review decisions. Existing tables are reused: company_exposures and company_segments
-- hold company-specific evidence; event_companies receives only reviewed, evidence-backed links.

CREATE TABLE company_relationships (
    relationship_id    INTEGER PRIMARY KEY,
    parent_company_id  TEXT NOT NULL REFERENCES companies(company_id),
    child_company_id   TEXT REFERENCES companies(company_id),   -- NULL when the child is not in the master
    child_name         TEXT NOT NULL,                           -- as stated in the evidence
    relationship_type  TEXT NOT NULL CHECK (relationship_type IN ('subsidiary','associate','joint_venture',
                                                                  'holding_company','common_control')),
    ownership_pct      REAL CHECK (ownership_pct IS NULL OR ownership_pct BETWEEN 0 AND 100),
    valid_from         TEXT,
    valid_to           TEXT,
    evidence_status    TEXT NOT NULL CHECK (evidence_status IN ('confirmed','strongly_supported','potential',
                                                                'unverified','rejected')),
    source_item_id     INTEGER REFERENCES source_items(source_item_id),
    evidence_excerpt   TEXT CHECK (evidence_excerpt IS NULL OR length(evidence_excerpt) BETWEEN 1 AND 1000),
    is_synthetic       INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    recorded_by        TEXT NOT NULL,
    recorded_at_utc    TEXT NOT NULL,
    CHECK (child_company_id IS NULL OR child_company_id <> parent_company_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    -- a relationship can only be confirmed or strongly supported with cited evidence
    CHECK (evidence_status NOT IN ('confirmed','strongly_supported')
           OR (source_item_id IS NOT NULL AND evidence_excerpt IS NOT NULL)),
    UNIQUE (parent_company_id, child_name, relationship_type, valid_from)
);
CREATE INDEX ix_company_relationships_child ON company_relationships(child_company_id);

CREATE TABLE exposure_candidates (
    candidate_id       INTEGER PRIMARY KEY,
    event_id           INTEGER NOT NULL REFERENCES events(event_id),
    company_id         TEXT NOT NULL REFERENCES companies(company_id),
    psx_symbol         TEXT,
    exposure_category  TEXT NOT NULL CHECK (exposure_category IN ('operational','financial','regulatory',
                                                                  'macroeconomic','geopolitical','sector')),
    exposure_subtype   TEXT NOT NULL,
    exposure_level     TEXT NOT NULL CHECK (exposure_level IN ('direct','indirect')),
    impact_direction   TEXT NOT NULL CHECK (impact_direction IN ('positive','negative','mixed','neutral','unknown')),
    segment_id         INTEGER REFERENCES company_segments(segment_id),
    mechanism          TEXT NOT NULL,
    explanation        TEXT NOT NULL,
    claim_evidence_ids_json   TEXT NOT NULL CHECK (json_valid(claim_evidence_ids_json)),
    exposure_evidence_ids_json TEXT NOT NULL CHECK (json_valid(exposure_evidence_ids_json)),
    source_item_ids_json      TEXT NOT NULL CHECK (json_valid(source_item_ids_json)),
    missing_evidence_json     TEXT NOT NULL CHECK (json_valid(missing_evidence_json)),
    confidence         REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_status    TEXT NOT NULL CHECK (evidence_status IN ('confirmed','strongly_supported','potential',
                                                                'unverified','rejected')),
    review_status      TEXT NOT NULL CHECK (review_status IN ('pending','needs_review','accepted','rejected')),
    review_reasons_json TEXT NOT NULL CHECK (json_valid(review_reasons_json)),
    origin             TEXT NOT NULL CHECK (origin IN ('rule','llm_suggestion')),
    rule_id            TEXT,
    ruleset_version    TEXT NOT NULL,
    model              TEXT,
    prompt_version     TEXT,
    schema_version     TEXT NOT NULL,
    is_synthetic       INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    current_revision   INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    created_at_utc     TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL,
    -- confirmed/strongly supported require company-specific exposure evidence
    CHECK (evidence_status NOT IN ('confirmed','strongly_supported') OR exposure_evidence_ids_json <> '[]'),
    -- confirmed additionally requires human acceptance
    CHECK (evidence_status <> 'confirmed' OR review_status = 'accepted'),
    CHECK (evidence_status <> 'rejected' OR review_status IN ('rejected','needs_review','pending')),
    UNIQUE (event_id, company_id, exposure_category, exposure_subtype, mechanism, ruleset_version)
);
CREATE INDEX ix_exposure_candidates_event ON exposure_candidates(event_id);
CREATE INDEX ix_exposure_candidates_company ON exposure_candidates(company_id);
CREATE INDEX ix_exposure_candidates_review ON exposure_candidates(review_status);

CREATE TABLE exposure_candidate_revisions (
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    revision_no        INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc    TEXT NOT NULL,
    evidence_status    TEXT NOT NULL,
    review_status      TEXT NOT NULL,
    snapshot_json      TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason      TEXT NOT NULL,
    changed_by         TEXT NOT NULL,
    PRIMARY KEY (candidate_id, revision_no)
);
CREATE TRIGGER trg_exposure_revisions_no_update BEFORE UPDATE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;
CREATE TRIGGER trg_exposure_revisions_no_delete BEFORE DELETE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;

-- Candidates change only by moving to a recorded revision; identity columns never change.
CREATE TRIGGER trg_exposure_candidates_require_revision BEFORE UPDATE ON exposure_candidates
WHEN NEW.current_revision <> OLD.current_revision + 1
  OR NOT EXISTS (SELECT 1 FROM exposure_candidate_revisions r
                 WHERE r.candidate_id = NEW.candidate_id AND r.revision_no = NEW.current_revision)
  OR NEW.event_id <> OLD.event_id OR NEW.company_id <> OLD.company_id
  OR NEW.exposure_category <> OLD.exposure_category OR NEW.mechanism <> OLD.mechanism
  OR NEW.origin <> OLD.origin OR NEW.ruleset_version <> OLD.ruleset_version
  OR NEW.is_synthetic <> OLD.is_synthetic
BEGIN SELECT RAISE(ABORT, 'update exposure candidates only through a new recorded revision'); END;
CREATE TRIGGER trg_exposure_candidates_no_delete BEFORE DELETE ON exposure_candidates
BEGIN SELECT RAISE(ABORT, 'exposure candidates cannot be deleted; record a rejection instead'); END;

CREATE TABLE exposure_reviews (
    review_id          INTEGER PRIMARY KEY,
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    decision           TEXT NOT NULL CHECK (decision IN ('accept','reject','needs_more_evidence')),
    reviewer           TEXT NOT NULL,
    notes              TEXT NOT NULL,
    decided_at_utc     TEXT NOT NULL
);
CREATE INDEX ix_exposure_reviews_candidate ON exposure_reviews(candidate_id);
CREATE TRIGGER trg_exposure_reviews_no_update BEFORE UPDATE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;
CREATE TRIGGER trg_exposure_reviews_no_delete BEFORE DELETE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;
