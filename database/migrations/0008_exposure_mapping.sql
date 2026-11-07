-- 0008: Phase 4 company exposure mapping (additive only).
--
-- Integrity design (owner database-integrity review, 2026-11-07):
-- * Evidence is linked through a normalised table with real foreign keys, never JSON id lists.
--   Triggers check that each link belongs to the candidate's own event or company and that
--   synthetic evidence is only attached to synthetic candidates.
-- * Revision 1 of every candidate is written by an AFTER INSERT trigger in the same statement,
--   so a candidate cannot exist without it. Every later change writes the next revision through
--   an AFTER UPDATE trigger. Revisions cannot be inserted by hand, updated or deleted.
-- * Candidates are inserted as 'unverified' or 'rejected' only. Higher statuses are reached by an
--   update that triggers re-check against the linked evidence and approved sources.
-- * 'confirmed' requires a real, immutable acceptance record in exposure_reviews.
-- * company_relationships is append-only; corrections are new rows that supersede old ones.

-- Synthetic marker for sources (additive). Synthetic evidence can only support synthetic mappings.
ALTER TABLE sources ADD COLUMN is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1));

-- ---------------------------------------------------------------- company relationships
CREATE TABLE company_relationships (
    relationship_id    INTEGER PRIMARY KEY,
    supersedes_relationship_id INTEGER UNIQUE REFERENCES company_relationships(relationship_id),
    parent_company_id  TEXT NOT NULL REFERENCES companies(company_id),
    child_company_id   TEXT REFERENCES companies(company_id),   -- NULL when the child is not in the master
    child_name         TEXT NOT NULL CHECK (length(trim(child_name)) > 0),
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
    change_reason      TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    recorded_by        TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
    recorded_at_utc    TEXT NOT NULL,
    CHECK (child_company_id IS NULL OR child_company_id <> parent_company_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (evidence_status NOT IN ('confirmed','strongly_supported','potential')
           OR (source_item_id IS NOT NULL AND evidence_excerpt IS NOT NULL))
);
CREATE INDEX ix_company_relationships_parent ON company_relationships(parent_company_id);
CREATE INDEX ix_company_relationships_child ON company_relationships(child_company_id);

CREATE TRIGGER trg_relationships_no_update BEFORE UPDATE ON company_relationships
BEGIN SELECT RAISE(ABORT, 'company_relationships are append-only; insert a superseding row'); END;
CREATE TRIGGER trg_relationships_no_delete BEFORE DELETE ON company_relationships
BEGIN SELECT RAISE(ABORT, 'company_relationships are append-only; insert a superseding row'); END;

CREATE TRIGGER trg_relationships_validate BEFORE INSERT ON company_relationships
BEGIN
    -- a correction must describe the same parent and child as the row it supersedes
    SELECT RAISE(ABORT, 'superseding row must keep the same parent and child')
    WHERE NEW.supersedes_relationship_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_relationships o WHERE o.relationship_id = NEW.supersedes_relationship_id
          AND o.parent_company_id = NEW.parent_company_id AND o.child_name = NEW.child_name
          AND o.child_company_id IS NEW.child_company_id);
    -- a new (non-correction) row may not duplicate a current relationship
    SELECT RAISE(ABORT, 'relationship already recorded; supersede it instead')
    WHERE NEW.supersedes_relationship_id IS NULL AND EXISTS (
        SELECT 1 FROM company_relationships o
        WHERE o.parent_company_id = NEW.parent_company_id AND o.child_name = NEW.child_name
          AND o.relationship_type = NEW.relationship_type
          AND NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = o.relationship_id));
    -- direct reversal cycle (A parent of B and B parent of A); deeper cycles are refused in application code
    SELECT RAISE(ABORT, 'relationship would create a cycle')
    WHERE NEW.child_company_id IS NOT NULL AND NEW.evidence_status <> 'rejected' AND EXISTS (
        SELECT 1 FROM company_relationships o
        WHERE o.parent_company_id = NEW.child_company_id AND o.child_company_id = NEW.parent_company_id
          AND o.evidence_status <> 'rejected'
          AND NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = o.relationship_id));
    -- stronger statuses need evidence from an approved source; synthetic evidence only on synthetic rows
    SELECT RAISE(ABORT, 'relationship evidence must come from an approved (ACTIVE) source')
    WHERE NEW.evidence_status IN ('confirmed','strongly_supported') AND NOT EXISTS (
        SELECT 1 FROM source_items i JOIN sources s USING(source_id)
        WHERE i.source_item_id = NEW.source_item_id AND s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved');
    SELECT RAISE(ABORT, 'synthetic evidence can only support a synthetic relationship')
    WHERE NEW.is_synthetic = 0 AND EXISTS (
        SELECT 1 FROM source_items i JOIN sources s USING(source_id)
        WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1);
END;

CREATE VIEW current_company_relationships AS
SELECT r.* FROM company_relationships r
WHERE NOT EXISTS (SELECT 1 FROM company_relationships s WHERE s.supersedes_relationship_id = r.relationship_id);

-- ---------------------------------------------------------------- exposure candidates
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
    mechanism          TEXT NOT NULL CHECK (length(trim(mechanism)) > 0),
    explanation        TEXT NOT NULL,
    missing_evidence_json TEXT NOT NULL CHECK (json_valid(missing_evidence_json)),
    confidence         REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence_status    TEXT NOT NULL CHECK (evidence_status IN ('confirmed','strongly_supported','potential',
                                                                'unverified','rejected')),
    review_status      TEXT NOT NULL CHECK (review_status IN ('pending','needs_review','accepted','rejected')),
    review_reasons_json TEXT NOT NULL CHECK (json_valid(review_reasons_json)),
    last_review_id     INTEGER REFERENCES exposure_reviews(review_id),
    origin             TEXT NOT NULL CHECK (origin IN ('rule','llm_suggestion')),
    rule_id            TEXT,
    ruleset_version    TEXT NOT NULL,
    model              TEXT,
    prompt_version     TEXT,
    schema_version     TEXT NOT NULL,
    is_synthetic       INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    current_revision   INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    change_reason      TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    changed_by         TEXT NOT NULL CHECK (length(trim(changed_by)) > 0),
    created_at_utc     TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL,
    CHECK ((evidence_status = 'confirmed') = (review_status = 'accepted')),
    CHECK (evidence_status <> 'rejected' OR review_status IN ('rejected','needs_review','pending')),
    CHECK (origin <> 'llm_suggestion' OR evidence_status NOT IN ('strongly_supported','confirmed')),
    UNIQUE (event_id, company_id, exposure_category, exposure_subtype, mechanism, ruleset_version)
);
CREATE INDEX ix_exposure_candidates_event ON exposure_candidates(event_id);
CREATE INDEX ix_exposure_candidates_company ON exposure_candidates(company_id);
CREATE INDEX ix_exposure_candidates_review ON exposure_candidates(review_status);

CREATE TABLE exposure_candidate_evidence (
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    role               TEXT NOT NULL CHECK (role IN ('claim','company_specific')),
    event_evidence_id  INTEGER REFERENCES event_evidence(evidence_id),
    company_exposure_id INTEGER REFERENCES company_exposures(exposure_id),
    relationship_id    INTEGER REFERENCES company_relationships(relationship_id),
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    added_at_utc       TEXT NOT NULL,
    CHECK ((event_evidence_id IS NOT NULL) + (company_exposure_id IS NOT NULL) + (relationship_id IS NOT NULL) = 1),
    CHECK (role = 'company_specific' OR event_evidence_id IS NOT NULL)
);
CREATE UNIQUE INDEX ux_candidate_evidence ON exposure_candidate_evidence(
    candidate_id, role, COALESCE(event_evidence_id, 0), COALESCE(company_exposure_id, 0), COALESCE(relationship_id, 0));
CREATE INDEX ix_candidate_evidence_candidate ON exposure_candidate_evidence(candidate_id);

CREATE TRIGGER trg_candidate_evidence_no_update BEFORE UPDATE ON exposure_candidate_evidence
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_evidence is append-only'); END;
CREATE TRIGGER trg_candidate_evidence_no_delete BEFORE DELETE ON exposure_candidate_evidence
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_evidence is append-only'); END;

CREATE TRIGGER trg_candidate_evidence_validate BEFORE INSERT ON exposure_candidate_evidence
BEGIN
    SELECT RAISE(ABORT, 'event evidence must belong to the candidate''s event and source item')
    WHERE NEW.event_evidence_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM event_evidence e JOIN exposure_candidates c ON c.event_id = e.event_id
        WHERE e.evidence_id = NEW.event_evidence_id AND c.candidate_id = NEW.candidate_id
          AND e.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'company exposure evidence must belong to the candidate''s company and source item')
    WHERE NEW.company_exposure_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_exposures x JOIN exposure_candidates c ON c.company_id = x.company_id
        WHERE x.exposure_id = NEW.company_exposure_id AND c.candidate_id = NEW.candidate_id
          AND x.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'relationship evidence must name the candidate''s company as parent')
    WHERE NEW.relationship_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM company_relationships r JOIN exposure_candidates c ON c.company_id = r.parent_company_id
        WHERE r.relationship_id = NEW.relationship_id AND c.candidate_id = NEW.candidate_id
          AND r.source_item_id IS NEW.source_item_id);
    SELECT RAISE(ABORT, 'synthetic evidence can only support a synthetic candidate')
    WHERE EXISTS (SELECT 1 FROM source_items i JOIN sources s USING(source_id)
                  JOIN exposure_candidates c ON c.candidate_id = NEW.candidate_id
                  WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1 AND c.is_synthetic = 0);
    SELECT RAISE(ABORT, 'evidence cannot be added to a confirmed or rejected candidate')
    WHERE EXISTS (SELECT 1 FROM exposure_candidates c WHERE c.candidate_id = NEW.candidate_id
                  AND c.evidence_status IN ('confirmed','rejected'));
END;

CREATE TABLE exposure_candidate_revisions (
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    revision_no        INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc    TEXT NOT NULL,
    evidence_status    TEXT NOT NULL,
    review_status      TEXT NOT NULL,
    last_review_id     INTEGER REFERENCES exposure_reviews(review_id),
    snapshot_json      TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason      TEXT NOT NULL,
    changed_by         TEXT NOT NULL,
    PRIMARY KEY (candidate_id, revision_no)
);
CREATE TRIGGER trg_exposure_revisions_only_current BEFORE INSERT ON exposure_candidate_revisions
WHEN NOT EXISTS (SELECT 1 FROM exposure_candidates c
                 WHERE c.candidate_id = NEW.candidate_id AND c.current_revision = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'revisions are written by triggers for the current revision only'); END;
CREATE TRIGGER trg_exposure_revisions_no_update BEFORE UPDATE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;
CREATE TRIGGER trg_exposure_revisions_no_delete BEFORE DELETE ON exposure_candidate_revisions
BEGIN SELECT RAISE(ABORT, 'exposure_candidate_revisions are append-only'); END;

CREATE TRIGGER trg_exposure_candidates_insert BEFORE INSERT ON exposure_candidates
BEGIN
    SELECT RAISE(ABORT, 'candidates start at revision 1')
    WHERE NEW.current_revision <> 1;
    SELECT RAISE(ABORT, 'candidates are created unverified or rejected; stronger statuses need linked evidence')
    WHERE NEW.evidence_status NOT IN ('unverified','rejected');
    SELECT RAISE(ABORT, 'a new candidate cannot carry a review decision')
    WHERE NEW.last_review_id IS NOT NULL OR NEW.review_status IN ('accepted');
END;

CREATE TRIGGER trg_exposure_candidates_rev1 AFTER INSERT ON exposure_candidates
BEGIN
    INSERT INTO exposure_candidate_revisions(candidate_id, revision_no, recorded_at_utc, evidence_status,
        review_status, last_review_id, snapshot_json, change_reason, changed_by)
    VALUES (NEW.candidate_id, 1, NEW.created_at_utc, NEW.evidence_status, NEW.review_status, NULL,
        json_object('impact_direction', NEW.impact_direction, 'exposure_level', NEW.exposure_level,
                    'evidence_status', NEW.evidence_status, 'review_status', NEW.review_status,
                    'confidence', NEW.confidence, 'explanation', NEW.explanation,
                    'missing_evidence', json(NEW.missing_evidence_json),
                    'review_reasons', json(NEW.review_reasons_json), 'segment_id', NEW.segment_id),
        NEW.change_reason, NEW.changed_by);
END;

CREATE TRIGGER trg_exposure_candidates_update BEFORE UPDATE ON exposure_candidates
BEGIN
    SELECT RAISE(ABORT, 'each update must move to the next revision')
    WHERE NEW.current_revision <> OLD.current_revision + 1;
    SELECT RAISE(ABORT, 'candidate identity cannot change')
    WHERE NEW.event_id <> OLD.event_id OR NEW.company_id <> OLD.company_id
       OR NEW.exposure_category <> OLD.exposure_category OR NEW.exposure_subtype <> OLD.exposure_subtype
       OR NEW.mechanism <> OLD.mechanism OR NEW.origin <> OLD.origin
       OR NEW.ruleset_version <> OLD.ruleset_version OR NEW.is_synthetic <> OLD.is_synthetic
       OR NEW.created_at_utc <> OLD.created_at_utc;
    SELECT RAISE(ABORT, 'a confirmed or rejected decision can only change through a new review')
    WHERE OLD.review_status IN ('accepted','rejected') AND NEW.last_review_id IS OLD.last_review_id;
    -- potential and above: company-specific evidence must be linked, and all of it from approved sources
    SELECT RAISE(ABORT, 'potential or stronger status requires linked company-specific evidence')
    WHERE NEW.evidence_status IN ('potential','strongly_supported','confirmed') AND NOT EXISTS (
        SELECT 1 FROM exposure_candidate_evidence l WHERE l.candidate_id = NEW.candidate_id
          AND l.role = 'company_specific');
    SELECT RAISE(ABORT, 'potential or stronger status requires every company-specific source to be approved')
    WHERE NEW.evidence_status IN ('potential','strongly_supported','confirmed') AND EXISTS (
        SELECT 1 FROM exposure_candidate_evidence l JOIN source_items i USING(source_item_id)
        JOIN sources s USING(source_id)
        WHERE l.candidate_id = NEW.candidate_id AND l.role = 'company_specific'
          AND NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'));
    -- strongly supported: the event itself must be corroborated or primary-confirmed
    SELECT RAISE(ABORT, 'strongly supported requires a corroborated or primary-confirmed event')
    WHERE NEW.evidence_status IN ('strongly_supported','confirmed') AND NOT EXISTS (
        SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
          AND e.verification_state IN ('corroborated','primary_confirmed'));
    -- confirmed: only from strongly supported, through a real acceptance review
    SELECT RAISE(ABORT, 'confirmed requires a prior strongly supported status')
    WHERE NEW.evidence_status = 'confirmed' AND OLD.evidence_status <> 'strongly_supported';
    SELECT RAISE(ABORT, 'accepted status requires a matching acceptance review')
    WHERE NEW.review_status = 'accepted' AND NOT EXISTS (
        SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id
          AND r.candidate_id = NEW.candidate_id AND r.decision = 'accept');
    SELECT RAISE(ABORT, 'rejected review status requires a matching rejection review')
    WHERE NEW.review_status = 'rejected' AND OLD.review_status <> 'rejected' AND NEW.origin = 'rule'
      AND NOT EXISTS (SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id
                      AND r.candidate_id = NEW.candidate_id AND r.decision = 'reject');
    SELECT RAISE(ABORT, 'last_review_id must refer to a review of this candidate')
    WHERE NEW.last_review_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM exposure_reviews r WHERE r.review_id = NEW.last_review_id AND r.candidate_id = NEW.candidate_id);
END;

CREATE TRIGGER trg_exposure_candidates_revision AFTER UPDATE ON exposure_candidates
BEGIN
    INSERT INTO exposure_candidate_revisions(candidate_id, revision_no, recorded_at_utc, evidence_status,
        review_status, last_review_id, snapshot_json, change_reason, changed_by)
    VALUES (NEW.candidate_id, NEW.current_revision, NEW.updated_at_utc, NEW.evidence_status, NEW.review_status,
        NEW.last_review_id,
        json_object('impact_direction', NEW.impact_direction, 'exposure_level', NEW.exposure_level,
                    'evidence_status', NEW.evidence_status, 'review_status', NEW.review_status,
                    'confidence', NEW.confidence, 'explanation', NEW.explanation,
                    'missing_evidence', json(NEW.missing_evidence_json),
                    'review_reasons', json(NEW.review_reasons_json), 'segment_id', NEW.segment_id),
        NEW.change_reason, NEW.changed_by);
END;

CREATE TRIGGER trg_exposure_candidates_no_delete BEFORE DELETE ON exposure_candidates
BEGIN SELECT RAISE(ABORT, 'exposure candidates cannot be deleted; record a rejection instead'); END;

-- ---------------------------------------------------------------- human reviews
CREATE TABLE exposure_reviews (
    review_id          INTEGER PRIMARY KEY,
    candidate_id       INTEGER NOT NULL REFERENCES exposure_candidates(candidate_id),
    decision           TEXT NOT NULL CHECK (decision IN ('accept','reject','needs_more_evidence')),
    reviewer           TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    decided_at_utc     TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    evidence_status_at_decision TEXT NOT NULL
);
CREATE INDEX ix_exposure_reviews_candidate ON exposure_reviews(candidate_id);
CREATE TRIGGER trg_exposure_reviews_validate BEFORE INSERT ON exposure_reviews
BEGIN
    SELECT RAISE(ABORT, 'review must record the candidate''s current evidence status')
    WHERE NOT EXISTS (SELECT 1 FROM exposure_candidates c WHERE c.candidate_id = NEW.candidate_id
                      AND c.evidence_status = NEW.evidence_status_at_decision);
    SELECT RAISE(ABORT, 'only a strongly supported candidate can be accepted')
    WHERE NEW.decision = 'accept' AND NEW.evidence_status_at_decision <> 'strongly_supported';
END;
CREATE TRIGGER trg_exposure_reviews_no_update BEFORE UPDATE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;
CREATE TRIGGER trg_exposure_reviews_no_delete BEFORE DELETE ON exposure_reviews
BEGIN SELECT RAISE(ABORT, 'exposure_reviews are append-only'); END;

-- Reviewed links in the existing event_companies table must come from a confirmed candidate.
CREATE TRIGGER trg_event_companies_accepted_requires_confirmed BEFORE INSERT ON event_companies
WHEN NEW.reviewer_status = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM exposure_candidates c WHERE c.event_id = NEW.event_id AND c.company_id = NEW.company_id
      AND c.evidence_status = 'confirmed')
BEGIN SELECT RAISE(ABORT, 'accepted event-company links require a confirmed exposure candidate'); END;
CREATE TRIGGER trg_event_companies_accept_update BEFORE UPDATE OF reviewer_status ON event_companies
WHEN NEW.reviewer_status = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM exposure_candidates c WHERE c.event_id = NEW.event_id AND c.company_id = NEW.company_id
      AND c.evidence_status = 'confirmed')
BEGIN SELECT RAISE(ABORT, 'accepted event-company links require a confirmed exposure candidate'); END;
