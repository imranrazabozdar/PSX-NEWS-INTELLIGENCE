-- 0009: Phase 5 impact-assessment schema (additive only). Implements docs/MIGRATION_0009_DESIGN.md.
-- Company-level assessments only; sector results are computed views. No expiry policy is shipped.
-- Nothing here estimates numeric impact, prices or market reactions (market_check is 'not_evaluable').

-- ---------------------------------------------------------------- expiry policies (immutable; shipped empty)
CREATE TABLE impact_expiry_policy_versions (
    policy_version     TEXT PRIMARY KEY CHECK (length(trim(policy_version)) > 0),
    rules_json         TEXT NOT NULL CHECK (json_valid(rules_json)),
    rationale          TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    drafted_by         TEXT NOT NULL CHECK (length(trim(drafted_by)) >= 2),
    drafted_at_utc     TEXT NOT NULL,
    supersedes_version TEXT REFERENCES impact_expiry_policy_versions(policy_version)
);
CREATE TRIGGER trg_policy_versions_no_update BEFORE UPDATE ON impact_expiry_policy_versions
BEGIN SELECT RAISE(ABORT, 'policy versions are immutable; draft a new version'); END;
CREATE TRIGGER trg_policy_versions_no_delete BEFORE DELETE ON impact_expiry_policy_versions
BEGIN SELECT RAISE(ABORT, 'policy versions are immutable'); END;

CREATE TABLE impact_expiry_policy_events (
    policy_event_id    INTEGER PRIMARY KEY,
    policy_version     TEXT NOT NULL REFERENCES impact_expiry_policy_versions(policy_version),
    event_type         TEXT NOT NULL CHECK (event_type IN ('approved','retired')),
    actor              TEXT NOT NULL CHECK (length(trim(actor)) >= 2),
    effective_from_utc TEXT,
    effective_to_utc   TEXT,
    recorded_at_utc    TEXT NOT NULL,
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    CHECK (event_type <> 'approved' OR (effective_from_utc IS NOT NULL AND effective_to_utc IS NULL)),
    CHECK (event_type <> 'retired' OR (effective_to_utc IS NOT NULL AND effective_from_utc IS NULL)),
    UNIQUE (policy_version, event_type)
);
CREATE TRIGGER trg_policy_events_no_update BEFORE UPDATE ON impact_expiry_policy_events
BEGIN SELECT RAISE(ABORT, 'policy lifecycle events are immutable'); END;
CREATE TRIGGER trg_policy_events_no_delete BEFORE DELETE ON impact_expiry_policy_events
BEGIN SELECT RAISE(ABORT, 'policy lifecycle events are immutable'); END;

-- Overlap check and approval write happen in the same statement (and transaction), under the write lock.
-- A new approval is open-ended, so it is refused unless every other approved version is already retired
-- with an end no later than the new start.
CREATE TRIGGER trg_policy_events_validate BEFORE INSERT ON impact_expiry_policy_events
BEGIN
    SELECT RAISE(ABORT, 'a version can only be retired after it is approved')
    WHERE NEW.event_type = 'retired' AND NOT EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.policy_version = NEW.policy_version AND a.event_type = 'approved');
    SELECT RAISE(ABORT, 'retirement cannot precede the effective start')
    WHERE NEW.event_type = 'retired' AND EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.policy_version = NEW.policy_version AND a.event_type = 'approved'
          AND NEW.effective_to_utc < a.effective_from_utc);
    SELECT RAISE(ABORT, 'overlapping expiry-policy approval')
    WHERE NEW.event_type = 'approved' AND EXISTS (
        SELECT 1 FROM impact_expiry_policy_events a
        WHERE a.event_type = 'approved' AND a.policy_version <> NEW.policy_version
          AND NOT EXISTS (SELECT 1 FROM impact_expiry_policy_events r
                          WHERE r.policy_version = a.policy_version AND r.event_type = 'retired'
                            AND r.effective_to_utc <= NEW.effective_from_utc));
END;

CREATE VIEW impact_expiry_policies_current AS
SELECT v.policy_version,
       a.effective_from_utc, r.effective_to_utc, a.actor AS approved_by,
       CASE WHEN a.policy_event_id IS NULL THEN 'draft'
            WHEN r.policy_event_id IS NULL THEN 'approved' ELSE 'retired' END AS status
FROM impact_expiry_policy_versions v
LEFT JOIN impact_expiry_policy_events a ON a.policy_version = v.policy_version AND a.event_type = 'approved'
LEFT JOIN impact_expiry_policy_events r ON r.policy_version = v.policy_version AND r.event_type = 'retired';

-- Detection backstop (integrity tests, health report): must always be empty.
CREATE VIEW impact_expiry_policy_overlaps AS
SELECT x.policy_version AS version_a, y.policy_version AS version_b
FROM impact_expiry_policies_current x JOIN impact_expiry_policies_current y
  ON x.policy_version < y.policy_version
WHERE x.status <> 'draft' AND y.status <> 'draft'
  AND x.effective_from_utc < COALESCE(y.effective_to_utc, '9999-12-31T23:59:59Z')
  AND y.effective_from_utc < COALESCE(x.effective_to_utc, '9999-12-31T23:59:59Z');

-- ---------------------------------------------------------------- assessments (company level only)
CREATE TABLE impact_assessments (
    assessment_id        INTEGER PRIMARY KEY,
    event_id             INTEGER NOT NULL REFERENCES events(event_id),
    event_revision_no    INTEGER NOT NULL,
    company_id           TEXT NOT NULL REFERENCES companies(company_id),
    mechanism_id         TEXT NOT NULL CHECK (mechanism_id GLOB 'T[1-9]' AND length(mechanism_id) = 2),
    transmission_version TEXT NOT NULL CHECK (length(trim(transmission_version)) > 0),
    ruleset_version      TEXT NOT NULL,
    calculation_version  TEXT,
    scenario_kind        TEXT NOT NULL CHECK (scenario_kind IN ('current','hypothetical','historical_test')),
    assessment_status    TEXT NOT NULL CHECK (assessment_status IN ('scenario_only','provisional','needs_review',
                             'needs_revalidation','confirmed_conclusion','withdrawn_evidence_invalid',
                             'rejected_by_review')),
    status_reason        TEXT NOT NULL,
    direction            TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude_level      TEXT NOT NULL CHECK (magnitude_level IN ('low','medium','high','not_assessable')),
    magnitude_basis      TEXT NOT NULL CHECK (magnitude_basis IN ('qualitative','deterministic_model',
                                                                  'financially_quantified')),
    horizon              TEXT NOT NULL CHECK (horizon IN ('short','medium','long','unknown')),
    evidence_confidence  TEXT NOT NULL CHECK (evidence_confidence IN ('low','medium','high')),
    exposure_confidence  TEXT NOT NULL CHECK (exposure_confidence IN ('low','medium','high')),
    direction_confidence TEXT NOT NULL CHECK (direction_confidence IN ('low','medium','high')),
    magnitude_confidence TEXT NOT NULL CHECK (magnitude_confidence IN ('low','medium','high')),
    scenario_uncertainty TEXT NOT NULL CHECK (scenario_uncertainty IN ('narrow','wide','undetermined')),
    confidence_reasons_json TEXT NOT NULL CHECK (json_valid(confidence_reasons_json)),
    affected_lines_json  TEXT NOT NULL CHECK (json_valid(affected_lines_json)),
    counter_evidence_json TEXT NOT NULL CHECK (json_valid(counter_evidence_json)),
    missing_inputs_json  TEXT NOT NULL CHECK (json_valid(missing_inputs_json)),
    quantification_json  TEXT CHECK (quantification_json IS NULL OR json_valid(quantification_json)),
    market_check         TEXT NOT NULL DEFAULT 'not_evaluable' CHECK (market_check = 'not_evaluable'),
    analysis_id          INTEGER REFERENCES analyses(analysis_id),
    expiry_policy_version TEXT REFERENCES impact_expiry_policy_versions(policy_version),
    freshness_basis      TEXT NOT NULL CHECK (freshness_basis IN ('explicit_source_expiry','policy_expiry',
                                                                  'not_established')),
    is_synthetic         INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0,1)),
    current_revision     INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    last_review_id       INTEGER REFERENCES impact_reviews(review_id),
    change_reason        TEXT NOT NULL CHECK (length(trim(change_reason)) > 0),
    changed_by           TEXT NOT NULL CHECK (length(trim(changed_by)) >= 2),
    actor_type           TEXT NOT NULL CHECK (actor_type IN ('human','system')),
    created_at_utc       TEXT NOT NULL,
    updated_at_utc       TEXT NOT NULL,
    FOREIGN KEY (event_id, event_revision_no) REFERENCES event_revisions(event_id, revision_no),
    -- financially quantified results need a quantification record; others must not carry one
    CHECK ((magnitude_basis = 'financially_quantified') = (quantification_json IS NOT NULL)),
    CHECK ((freshness_basis = 'policy_expiry') = (expiry_policy_version IS NOT NULL)),
    -- status <-> reason <-> actor (system withdrawal and human rejection can never be confused)
    CHECK (
        (assessment_status = 'scenario_only' AND status_reason IN ('created_scenario','revalidated'))
     OR (assessment_status = 'provisional' AND status_reason IN ('created_eligible','revalidated','reinstated'))
     OR (assessment_status = 'needs_review' AND status_reason IN ('created_needs_review','event_disputed',
                                    'reviewer_needs_more_evidence','freshness_not_established'))
     OR (assessment_status = 'needs_revalidation' AND status_reason IN ('evidence_revoked','evidence_superseded',
                                    'evidence_expired','evidence_retracted','source_restricted','exposure_rejected',
                                    'reviewer_requested_revalidation'))
     OR (assessment_status = 'confirmed_conclusion' AND status_reason = 'reviewer_accepted')
     OR (assessment_status = 'withdrawn_evidence_invalid' AND status_reason IN ('event_refuted','evidence_revoked',
                                    'evidence_superseded','evidence_expired','evidence_retracted',
                                    'source_restricted','exposure_rejected'))
     OR (assessment_status = 'rejected_by_review' AND status_reason = 'reviewer_rejected')),
    CHECK (status_reason NOT IN ('reviewer_accepted','reviewer_rejected','reviewer_needs_more_evidence',
                                 'reviewer_requested_revalidation','reinstated') OR actor_type = 'human'),
    CHECK (assessment_status <> 'withdrawn_evidence_invalid' OR actor_type = 'system'),
    CHECK (assessment_status <> 'rejected_by_review' OR actor_type = 'human'),
    UNIQUE (event_id, company_id, mechanism_id, scenario_kind, transmission_version)
);
CREATE INDEX ix_impact_company ON impact_assessments(company_id);
CREATE INDEX ix_impact_status ON impact_assessments(assessment_status);

CREATE TABLE impact_reviews (
    review_id          INTEGER PRIMARY KEY,
    assessment_id      INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    decision           TEXT NOT NULL CHECK (decision IN ('accept','reject','request_revalidation',
                                                         'needs_more_evidence')),
    reviewer           TEXT NOT NULL CHECK (length(trim(reviewer)) >= 2),
    notes              TEXT NOT NULL CHECK (length(trim(notes)) > 0),
    decided_at_utc     TEXT NOT NULL CHECK (decided_at_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    status_at_decision TEXT NOT NULL
);
CREATE INDEX ix_impact_reviews_assessment ON impact_reviews(assessment_id);
CREATE TRIGGER trg_impact_reviews_no_update BEFORE UPDATE ON impact_reviews
BEGIN SELECT RAISE(ABORT, 'impact_reviews are append-only'); END;
CREATE TRIGGER trg_impact_reviews_no_delete BEFORE DELETE ON impact_reviews
BEGIN SELECT RAISE(ABORT, 'impact_reviews are append-only'); END;

CREATE TABLE impact_assessment_inputs (
    input_id                   INTEGER PRIMARY KEY,
    assessment_id              INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    input_kind                 TEXT NOT NULL CHECK (input_kind IN ('exposure_candidate','event_evidence',
                                                                   'financial_metric','commodity_price')),
    exposure_candidate_id      INTEGER REFERENCES exposure_candidates(candidate_id),
    exposure_candidate_revision INTEGER,
    event_evidence_id          INTEGER REFERENCES event_evidence(evidence_id),
    financial_metric_id        INTEGER REFERENCES financial_metrics(metric_id),
    commodity_price_id         INTEGER REFERENCES commodity_prices(price_id),
    source_item_id             INTEGER NOT NULL REFERENCES source_items(source_item_id),
    step_no                    INTEGER CHECK (step_no IS NULL OR step_no >= 1),
    added_at_utc               TEXT NOT NULL,
    FOREIGN KEY (exposure_candidate_id, exposure_candidate_revision)
        REFERENCES exposure_candidate_revisions(candidate_id, revision_no),
    CHECK ((exposure_candidate_id IS NOT NULL) + (event_evidence_id IS NOT NULL)
           + (financial_metric_id IS NOT NULL) + (commodity_price_id IS NOT NULL) = 1),
    CHECK ((input_kind = 'exposure_candidate') = (exposure_candidate_id IS NOT NULL)),
    CHECK ((exposure_candidate_id IS NULL) = (exposure_candidate_revision IS NULL)),
    CHECK ((input_kind = 'event_evidence') = (event_evidence_id IS NOT NULL)),
    CHECK ((input_kind = 'financial_metric') = (financial_metric_id IS NOT NULL)),
    CHECK ((input_kind = 'commodity_price') = (commodity_price_id IS NOT NULL))
);
CREATE INDEX ix_impact_inputs_assessment ON impact_assessment_inputs(assessment_id);
CREATE INDEX ix_impact_inputs_candidate ON impact_assessment_inputs(exposure_candidate_id);
CREATE TRIGGER trg_impact_inputs_no_update BEFORE UPDATE ON impact_assessment_inputs
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs are append-only'); END;
CREATE TRIGGER trg_impact_inputs_no_delete BEFORE DELETE ON impact_assessment_inputs
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs are append-only'); END;

CREATE TRIGGER trg_impact_inputs_validate BEFORE INSERT ON impact_assessment_inputs
BEGIN
    SELECT RAISE(ABORT, 'exposure candidate must belong to the assessment''s event and company')
    WHERE NEW.exposure_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM exposure_candidates x JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE x.candidate_id = NEW.exposure_candidate_id AND x.event_id = a.event_id
          AND x.company_id = a.company_id);
    SELECT RAISE(ABORT, 'event evidence must belong to the assessment''s event and source item')
    WHERE NEW.event_evidence_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM event_evidence e JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE e.evidence_id = NEW.event_evidence_id AND e.event_id = a.event_id
          AND e.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'financial metric must belong to the assessment''s company and source item')
    WHERE NEW.financial_metric_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM financial_metrics m JOIN impact_assessments a ON a.assessment_id = NEW.assessment_id
        WHERE m.metric_id = NEW.financial_metric_id AND m.company_id = a.company_id
          AND m.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'commodity price must match its source item')
    WHERE NEW.commodity_price_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM commodity_prices c WHERE c.price_id = NEW.commodity_price_id
          AND c.source_item_id = NEW.source_item_id);
    SELECT RAISE(ABORT, 'synthetic input can only support a synthetic assessment')
    WHERE EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.is_synthetic = 0)
      AND (EXISTS (SELECT 1 FROM source_items i JOIN sources s USING(source_id)
                   WHERE i.source_item_id = NEW.source_item_id AND s.is_synthetic = 1)
        OR EXISTS (SELECT 1 FROM exposure_candidates x WHERE x.candidate_id = NEW.exposure_candidate_id
                   AND x.is_synthetic = 1));
    SELECT RAISE(ABORT, 'an exposure input attached to a provisional assessment must be strongly supported or confirmed')
    WHERE NEW.exposure_candidate_id IS NOT NULL
      AND EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.assessment_status = 'provisional')
      AND NOT EXISTS (SELECT 1 FROM exposure_candidates_current c WHERE c.candidate_id = NEW.exposure_candidate_id
                      AND c.effective_status IN ('strongly_supported','confirmed'));
    SELECT RAISE(ABORT, 'inputs cannot be added to a terminal assessment')
    WHERE EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                  AND a.assessment_status IN ('confirmed_conclusion','withdrawn_evidence_invalid',
                                              'rejected_by_review'));
END;

-- An input is invalid when its source is no longer approved, its record was retracted, or its exposure
-- candidate is no longer valid / eligible / up to date (a newer revision changed status or direction).
CREATE VIEW impact_invalid_inputs AS
SELECT i.input_id, i.assessment_id, i.input_kind,
       CASE
         WHEN NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
                   AND s.access_status = 'verified_permitted' AND s.enabled = 1) THEN 'source_restricted'
         WHEN i.event_evidence_id IS NOT NULL AND EXISTS (SELECT 1 FROM evidence_retractions x
              WHERE x.record_table = 'event_evidence' AND x.record_id = i.event_evidence_id) THEN 'evidence_retracted'
         WHEN i.exposure_candidate_id IS NOT NULL AND (cv.evidence_currently_valid = 0
              OR cv.effective_status IN ('rejected','needs_revalidation')) THEN 'evidence_revoked'
         WHEN i.exposure_candidate_id IS NOT NULL AND EXISTS (
              SELECT 1 FROM exposure_candidate_revisions nr JOIN exposure_candidate_revisions lr
                ON lr.candidate_id = nr.candidate_id AND lr.revision_no = i.exposure_candidate_revision
              WHERE nr.candidate_id = i.exposure_candidate_id AND nr.revision_no > i.exposure_candidate_revision
                AND (nr.evidence_status <> lr.evidence_status
                     OR json_extract(nr.snapshot_json, '$.impact_direction')
                        IS NOT json_extract(lr.snapshot_json, '$.impact_direction'))) THEN 'evidence_superseded'
       END AS invalid_reason
FROM impact_assessment_inputs i
JOIN source_items si ON si.source_item_id = i.source_item_id
JOIN sources s ON s.source_id = si.source_id
LEFT JOIN exposure_candidates_current cv ON cv.candidate_id = i.exposure_candidate_id
WHERE NOT (s.lifecycle_status = 'ACTIVE' AND s.terms_status = 'approved'
           AND s.access_status = 'verified_permitted' AND s.enabled = 1)
   OR (i.event_evidence_id IS NOT NULL AND EXISTS (SELECT 1 FROM evidence_retractions x
       WHERE x.record_table = 'event_evidence' AND x.record_id = i.event_evidence_id))
   OR (i.exposure_candidate_id IS NOT NULL AND (cv.evidence_currently_valid = 0
       OR cv.effective_status IN ('rejected','needs_revalidation')))
   OR (i.exposure_candidate_id IS NOT NULL AND EXISTS (
       SELECT 1 FROM exposure_candidate_revisions nr JOIN exposure_candidate_revisions lr
         ON lr.candidate_id = nr.candidate_id AND lr.revision_no = i.exposure_candidate_revision
       WHERE nr.candidate_id = i.exposure_candidate_id AND nr.revision_no > i.exposure_candidate_revision
         AND (nr.evidence_status <> lr.evidence_status
              OR json_extract(nr.snapshot_json, '$.impact_direction')
                 IS NOT json_extract(lr.snapshot_json, '$.impact_direction'))));

-- Explicit source expiry is verified from the database for EVERY linked company-specific exposure record
-- (approved contract section 3: each exposure input has a freshness horizon; one expired input invalidates).
-- A record is fresh only if valid_to is a real calendar date (YYYY-MM-DD, or YYYY-MM-DDTHH:MM:SSZ), and that
-- date has not passed by the database clock. One fresh record never compensates for a stale one.
CREATE VIEW impact_linked_exposure_freshness AS
SELECT i.assessment_id, x.exposure_id, x.valid_to,
       CASE
         WHEN x.valid_to IS NULL THEN 'missing'
         WHEN NOT ((length(x.valid_to) = 10 AND x.valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                    AND date(x.valid_to) IS x.valid_to)
                OR (length(x.valid_to) = 20
                    AND x.valid_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
                    AND strftime('%Y-%m-%dT%H:%M:%SZ', x.valid_to) IS x.valid_to)) THEN 'invalid'
         WHEN substr(x.valid_to, 1, 10) < date('now') THEN 'expired'
         ELSE 'fresh'
       END AS freshness
FROM impact_assessment_inputs i
JOIN exposure_candidate_evidence l ON l.candidate_id = i.exposure_candidate_id AND l.role = 'company_specific'
JOIN company_exposures x ON x.exposure_id = l.company_exposure_id;

-- An assessment has verified explicit freshness only when it has at least one linked exposure record and
-- every linked exposure record is fresh.
CREATE VIEW impact_explicit_freshness AS
SELECT f.assessment_id
FROM impact_linked_exposure_freshness f
GROUP BY f.assessment_id
HAVING SUM(f.freshness <> 'fresh') = 0;

CREATE TABLE impact_assessment_revisions (
    assessment_id      INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no        INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc    TEXT NOT NULL,
    previous_status    TEXT,
    new_status         TEXT NOT NULL,
    status_reason      TEXT NOT NULL,
    actor_type         TEXT NOT NULL,
    actor              TEXT NOT NULL,
    review_id          INTEGER REFERENCES impact_reviews(review_id),
    snapshot_json      TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    input_snapshot_json TEXT NOT NULL CHECK (json_valid(input_snapshot_json)),
    PRIMARY KEY (assessment_id, revision_no)
);
CREATE TRIGGER trg_impact_revisions_only_current BEFORE INSERT ON impact_assessment_revisions
WHEN NOT EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                 AND a.current_revision = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'revisions are written by triggers for the current revision only'); END;
CREATE TRIGGER trg_impact_revisions_no_update BEFORE UPDATE ON impact_assessment_revisions
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions are append-only'); END;
CREATE TRIGGER trg_impact_revisions_no_delete BEFORE DELETE ON impact_assessment_revisions
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions are append-only'); END;

CREATE TABLE impact_transmission_steps (
    assessment_id  INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no    INTEGER NOT NULL,
    step_no        INTEGER NOT NULL CHECK (step_no >= 1),
    from_variable  TEXT NOT NULL CHECK (length(trim(from_variable)) > 0),
    to_variable    TEXT NOT NULL CHECK (length(trim(to_variable)) > 0),
    sign           INTEGER CHECK (sign IS NULL OR sign IN (-1, 0, 1)),
    lag_horizon    TEXT NOT NULL CHECK (lag_horizon IN ('short','medium','long','unknown')),
    explanation    TEXT NOT NULL CHECK (length(trim(explanation)) > 0),
    PRIMARY KEY (assessment_id, revision_no, step_no),
    FOREIGN KEY (assessment_id, revision_no) REFERENCES impact_assessment_revisions(assessment_id, revision_no)
);
CREATE TRIGGER trg_impact_steps_no_update BEFORE UPDATE ON impact_transmission_steps
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps are append-only'); END;
CREATE TRIGGER trg_impact_steps_no_delete BEFORE DELETE ON impact_transmission_steps
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps are append-only'); END;

CREATE TABLE impact_scenarios (
    assessment_id    INTEGER NOT NULL REFERENCES impact_assessments(assessment_id),
    revision_no      INTEGER NOT NULL,
    scenario_case    TEXT NOT NULL CHECK (scenario_case IN ('base','optimistic','adverse')),
    direction        TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude_level  TEXT NOT NULL CHECK (magnitude_level IN ('low','medium','high','not_assessable')),
    assumptions_json TEXT NOT NULL CHECK (json_valid(assumptions_json)),
    PRIMARY KEY (assessment_id, revision_no, scenario_case),
    FOREIGN KEY (assessment_id, revision_no) REFERENCES impact_assessment_revisions(assessment_id, revision_no)
);
CREATE TRIGGER trg_impact_scenarios_no_update BEFORE UPDATE ON impact_scenarios
BEGIN SELECT RAISE(ABORT, 'impact_scenarios are append-only'); END;
CREATE TRIGGER trg_impact_scenarios_no_delete BEFORE DELETE ON impact_scenarios
BEGIN SELECT RAISE(ABORT, 'impact_scenarios are append-only'); END;

-- Reviews must state the true current status; acceptance confirms a provisional assessment or approves a
-- reinstatement (from a withdrawn, rejected or needs_revalidation state).
CREATE TRIGGER trg_impact_reviews_validate BEFORE INSERT ON impact_reviews
BEGIN
    SELECT RAISE(ABORT, 'review must record the assessment''s current status')
    WHERE NOT EXISTS (SELECT 1 FROM impact_assessments a WHERE a.assessment_id = NEW.assessment_id
                      AND a.assessment_status = NEW.status_at_decision);
    SELECT RAISE(ABORT, 'accept is only allowed for provisional assessments or reinstatement')
    WHERE NEW.decision = 'accept' AND NEW.status_at_decision NOT IN
          ('provisional','withdrawn_evidence_invalid','rejected_by_review','needs_revalidation');
    SELECT RAISE(ABORT, 'cannot accept a provisional assessment with invalid inputs')
    WHERE NEW.decision = 'accept' AND NEW.status_at_decision = 'provisional'
      AND EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = NEW.assessment_id);
END;

-- ---------------------------------------------------------------- assessment insert / update guards
CREATE TRIGGER trg_impact_assessments_insert BEFORE INSERT ON impact_assessments
BEGIN
    SELECT RAISE(ABORT, 'assessments start at revision 1') WHERE NEW.current_revision <> 1;
    SELECT RAISE(ABORT, 'assessments are created as scenario_only or needs_review; upgrade after linking inputs')
    WHERE NEW.assessment_status NOT IN ('scenario_only','needs_review');
    SELECT RAISE(ABORT, 'a new assessment cannot carry a review') WHERE NEW.last_review_id IS NOT NULL;
    SELECT RAISE(ABORT, 'a refuted event cannot have a current assessment')
    WHERE NEW.scenario_kind = 'current' AND EXISTS (
        SELECT 1 FROM events e WHERE e.event_id = NEW.event_id AND e.verification_state = 'refuted');
    SELECT RAISE(ABORT, 'fictional (cmp-syn-*) companies require a synthetic assessment')
    WHERE NEW.is_synthetic = 0 AND NEW.company_id GLOB 'cmp-syn-*';
    SELECT RAISE(ABORT, 'expiry policy must be approved and in effect, with no overlapping approvals')
    WHERE NEW.expiry_policy_version IS NOT NULL AND (
        NOT EXISTS (SELECT 1 FROM impact_expiry_policies_current p
                    WHERE p.policy_version = NEW.expiry_policy_version AND p.status <> 'draft'
                      AND p.effective_from_utc <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                      AND (p.effective_to_utc IS NULL
                           OR strftime('%Y-%m-%dT%H:%M:%SZ', 'now') < p.effective_to_utc))
        OR EXISTS (SELECT 1 FROM impact_expiry_policy_overlaps));
END;

CREATE TRIGGER trg_impact_assessments_rev1 AFTER INSERT ON impact_assessments
BEGIN
    INSERT INTO impact_assessment_revisions VALUES (
        NEW.assessment_id, 1, NEW.created_at_utc, NULL, NEW.assessment_status, NEW.status_reason,
        NEW.actor_type, NEW.changed_by, NULL,
        json_object('assessment_status', NEW.assessment_status, 'status_reason', NEW.status_reason,
                    'direction', NEW.direction, 'magnitude_level', NEW.magnitude_level,
                    'magnitude_basis', NEW.magnitude_basis, 'horizon', NEW.horizon,
                    'evidence_confidence', NEW.evidence_confidence, 'exposure_confidence', NEW.exposure_confidence,
                    'direction_confidence', NEW.direction_confidence,
                    'magnitude_confidence', NEW.magnitude_confidence,
                    'scenario_uncertainty', NEW.scenario_uncertainty, 'event_revision_no', NEW.event_revision_no,
                    'expiry_policy_version', NEW.expiry_policy_version, 'freshness_basis', NEW.freshness_basis,
                    'is_synthetic', NEW.is_synthetic),
        '[]');
END;

CREATE TRIGGER trg_impact_assessments_update BEFORE UPDATE ON impact_assessments
BEGIN
    SELECT RAISE(ABORT, 'each update must move to the next revision')
    WHERE NEW.current_revision <> OLD.current_revision + 1;
    SELECT RAISE(ABORT, 'assessment identity cannot change')
    WHERE NEW.event_id <> OLD.event_id OR NEW.company_id <> OLD.company_id
       OR NEW.mechanism_id <> OLD.mechanism_id OR NEW.scenario_kind <> OLD.scenario_kind
       OR NEW.transmission_version <> OLD.transmission_version OR NEW.is_synthetic <> OLD.is_synthetic
       OR NEW.created_at_utc <> OLD.created_at_utc;
    SELECT RAISE(ABORT, 'expiry_policy_version and freshness_basis are fixed at creation')
    WHERE NEW.expiry_policy_version IS NOT OLD.expiry_policy_version
       OR NEW.freshness_basis <> OLD.freshness_basis;
    -- strict transition matrix for terminal and confirmed states
    SELECT RAISE(ABORT, 'a terminal assessment can only be reinstated to provisional after a human accept review')
    WHERE OLD.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review')
      AND NOT (NEW.assessment_status = 'provisional' AND NEW.status_reason = 'reinstated'
               AND NEW.actor_type = 'human');
    SELECT RAISE(ABORT, 'a confirmed conclusion can only be revalidated or withdrawn by the system, or rejected by review')
    WHERE OLD.assessment_status = 'confirmed_conclusion'
      AND NOT ((NEW.assessment_status IN ('needs_revalidation','withdrawn_evidence_invalid')
                AND NEW.actor_type = 'system' AND NEW.last_review_id IS OLD.last_review_id)
               OR (NEW.assessment_status = 'rejected_by_review' AND NEW.actor_type = 'human'));
    -- human reasons need a matching review of this assessment, written for this transition
    SELECT RAISE(ABORT, 'human decision requires a matching new review of this assessment')
    WHERE NEW.status_reason IN ('reviewer_accepted','reviewer_rejected','reviewer_needs_more_evidence',
                                'reviewer_requested_revalidation','reinstated')
      AND (NEW.last_review_id IS OLD.last_review_id OR NOT EXISTS (
            SELECT 1 FROM impact_reviews r WHERE r.review_id = NEW.last_review_id
              AND r.assessment_id = NEW.assessment_id AND r.status_at_decision = OLD.assessment_status
              AND r.decision = CASE NEW.status_reason
                    WHEN 'reviewer_accepted' THEN 'accept' WHEN 'reinstated' THEN 'accept'
                    WHEN 'reviewer_rejected' THEN 'reject'
                    WHEN 'reviewer_needs_more_evidence' THEN 'needs_more_evidence'
                    ELSE 'request_revalidation' END));
    SELECT RAISE(ABORT, 'confirmation requires a prior provisional status')
    WHERE NEW.assessment_status = 'confirmed_conclusion' AND OLD.assessment_status <> 'provisional';
    -- a chain that was ever confirmed returns to provisional only by human reinstatement
    SELECT RAISE(ABORT, 'a previously confirmed or terminal assessment needs human reinstatement')
    WHERE NEW.assessment_status = 'provisional' AND NEW.status_reason <> 'reinstated'
      AND (OLD.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review')
           OR EXISTS (SELECT 1 FROM impact_assessment_revisions h WHERE h.assessment_id = OLD.assessment_id
                      AND h.new_status = 'confirmed_conclusion'));
    SELECT RAISE(ABORT, 'reinstatement leads to provisional only')
    WHERE NEW.status_reason = 'reinstated' AND NEW.assessment_status <> 'provisional';
    -- write-time evidence checks for provisional / confirmed
    SELECT RAISE(ABORT, 'provisional or confirmed requires valid inputs')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND EXISTS (
        SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = NEW.assessment_id);
    SELECT RAISE(ABORT, 'provisional or confirmed requires an eligible exposure input')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NOT EXISTS (
        SELECT 1 FROM impact_assessment_inputs i JOIN exposure_candidates_current c
          ON c.candidate_id = i.exposure_candidate_id
        WHERE i.assessment_id = NEW.assessment_id
          AND c.effective_status IN ('strongly_supported','confirmed'));
    SELECT RAISE(ABORT, 'every exposure input of a provisional assessment must be strongly supported or confirmed')
    WHERE NEW.assessment_status = 'provisional' AND EXISTS (
        SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
          ON c.candidate_id = i.exposure_candidate_id
        WHERE i.assessment_id = NEW.assessment_id AND i.exposure_candidate_id IS NOT NULL
          AND (c.effective_status IS NULL OR c.effective_status NOT IN ('strongly_supported','confirmed')));
    SELECT RAISE(ABORT, 'a confirmed conclusion requires confirmed exposures and a corroborated event')
    WHERE NEW.assessment_status = 'confirmed_conclusion' AND (
        EXISTS (SELECT 1 FROM impact_assessment_inputs i JOIN exposure_candidates_current c
                  ON c.candidate_id = i.exposure_candidate_id
                WHERE i.assessment_id = NEW.assessment_id AND c.effective_status <> 'confirmed')
        OR NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
                       AND e.verification_state IN ('corroborated','primary_confirmed')));
    SELECT RAISE(ABORT, 'refuted, rumour or disputed events cannot support provisional or confirmed current assessments')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NEW.scenario_kind = 'current'
      AND EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id
                  AND (e.verification_state = 'refuted' OR e.status_stage = 'rumour'
                       OR (e.verification_state = 'disputed' AND NEW.assessment_status = 'confirmed_conclusion')));
    SELECT RAISE(ABORT, 'a disputed event allows only mixed or unknown direction')
    WHERE NEW.assessment_status = 'provisional' AND NEW.direction NOT IN ('mixed','unknown')
      AND EXISTS (SELECT 1 FROM events e WHERE e.event_id = NEW.event_id AND e.verification_state = 'disputed');
    SELECT RAISE(ABORT, 'freshness not established: at most needs_review')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'not_established';
    -- policy-based freshness cannot be evaluated by the database yet (rules are not machine-checked), so it
    -- never unlocks provisional/confirmed; explicit expiry must be verifiable from a linked exposure record
    SELECT RAISE(ABORT, 'policy-based freshness is not yet database-verifiable: at most needs_review')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'policy_expiry';
    SELECT RAISE(ABORT, 'explicit source expiry not verified: every linked exposure record needs a real, unexpired valid_to')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion')
      AND NEW.freshness_basis = 'explicit_source_expiry'
      AND NOT EXISTS (SELECT 1 FROM impact_explicit_freshness f WHERE f.assessment_id = NEW.assessment_id);
    SELECT RAISE(ABORT, 'an unknown transmission step requires unknown direction')
    WHERE NEW.assessment_status IN ('provisional','confirmed_conclusion') AND NEW.direction <> 'unknown'
      AND EXISTS (SELECT 1 FROM impact_transmission_steps t WHERE t.assessment_id = NEW.assessment_id
                  AND t.revision_no = OLD.current_revision AND t.sign IS NULL);
    SELECT RAISE(ABORT, 'evidence_expired requires an explicit source expiry or an approved policy')
    WHERE NEW.status_reason = 'evidence_expired' AND NEW.freshness_basis = 'not_established';
    -- review binding (replay protection) and direction-change authorisation
    SELECT RAISE(ABORT, 'a linked review cannot be removed')
    WHERE OLD.last_review_id IS NOT NULL AND NEW.last_review_id IS NULL;
    SELECT RAISE(ABORT, 'a review can only be linked by a human decision')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id
      AND NOT (NEW.actor_type = 'human' AND NEW.status_reason IN ('reviewer_accepted','reviewer_rejected',
               'reviewer_needs_more_evidence','reviewer_requested_revalidation','reinstated'));
    SELECT RAISE(ABORT, 'review already used: each review authorises exactly one transition')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id AND EXISTS (
        SELECT 1 FROM impact_assessment_revisions h WHERE h.review_id = NEW.last_review_id);
    SELECT RAISE(ABORT, 'stale review: only the assessment''s newest review can authorise a transition')
    WHERE NEW.last_review_id IS NOT OLD.last_review_id AND NEW.last_review_id IS NOT (
        SELECT MAX(r.review_id) FROM impact_reviews r WHERE r.assessment_id = NEW.assessment_id);
    -- Substantive fields change only with a new human review. Without one, a single field may move one way:
    -- towards caution (direction/horizon -> unknown, magnitude -> not_assessable, a confidence downwards,
    -- scenario uncertainty wider). Other fields, magnitude_basis and affected lines, never change unreviewed.
    SELECT RAISE(ABORT, 'substantive change requires a new human review (only single moves towards caution are exempt)')
    WHERE NOT (NEW.actor_type = 'human' AND NEW.last_review_id IS NOT OLD.last_review_id) AND (
           (NEW.direction IS NOT OLD.direction AND NEW.direction <> 'unknown')
        OR (NEW.horizon IS NOT OLD.horizon AND NEW.horizon <> 'unknown')
        OR (NEW.magnitude_level IS NOT OLD.magnitude_level AND NEW.magnitude_level <> 'not_assessable')
        OR NEW.magnitude_basis IS NOT OLD.magnitude_basis
        OR NEW.affected_lines_json IS NOT OLD.affected_lines_json
        OR (CASE NEW.evidence_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.evidence_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.exposure_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.exposure_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.direction_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.direction_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.magnitude_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
         > (CASE OLD.magnitude_confidence WHEN 'low' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END)
        OR (CASE NEW.scenario_uncertainty WHEN 'narrow' THEN 1 WHEN 'wide' THEN 2 ELSE 3 END)
         < (CASE OLD.scenario_uncertainty WHEN 'narrow' THEN 1 WHEN 'wide' THEN 2 ELSE 3 END));
    SELECT RAISE(ABORT, 'without a new human review only one substantive field may change per update')
    WHERE NOT (NEW.actor_type = 'human' AND NEW.last_review_id IS NOT OLD.last_review_id)
      AND (NEW.direction IS NOT OLD.direction) + (NEW.horizon IS NOT OLD.horizon)
        + (NEW.magnitude_level IS NOT OLD.magnitude_level)
        + (NEW.evidence_confidence IS NOT OLD.evidence_confidence)
        + (NEW.exposure_confidence IS NOT OLD.exposure_confidence)
        + (NEW.direction_confidence IS NOT OLD.direction_confidence)
        + (NEW.magnitude_confidence IS NOT OLD.magnitude_confidence)
        + (NEW.scenario_uncertainty IS NOT OLD.scenario_uncertainty) > 1;
END;

CREATE TRIGGER trg_impact_assessments_revision AFTER UPDATE ON impact_assessments
BEGIN
    INSERT INTO impact_assessment_revisions VALUES (
        NEW.assessment_id, NEW.current_revision, NEW.updated_at_utc, OLD.assessment_status,
        NEW.assessment_status, NEW.status_reason, NEW.actor_type, NEW.changed_by,
        CASE WHEN NEW.last_review_id IS NOT OLD.last_review_id THEN NEW.last_review_id END,
        json_object('assessment_status', NEW.assessment_status, 'status_reason', NEW.status_reason,
                    'direction', NEW.direction, 'magnitude_level', NEW.magnitude_level,
                    'magnitude_basis', NEW.magnitude_basis, 'horizon', NEW.horizon,
                    'evidence_confidence', NEW.evidence_confidence, 'exposure_confidence', NEW.exposure_confidence,
                    'direction_confidence', NEW.direction_confidence,
                    'magnitude_confidence', NEW.magnitude_confidence,
                    'scenario_uncertainty', NEW.scenario_uncertainty, 'event_revision_no', NEW.event_revision_no,
                    'expiry_policy_version', NEW.expiry_policy_version, 'freshness_basis', NEW.freshness_basis,
                    'is_synthetic', NEW.is_synthetic),
        COALESCE((SELECT json_group_array(json_object('input_id', i.input_id, 'kind', i.input_kind,
                    'valid', CASE WHEN v.input_id IS NULL THEN 1 ELSE 0 END, 'invalid_reason', v.invalid_reason))
                  FROM impact_assessment_inputs i LEFT JOIN impact_invalid_inputs v ON v.input_id = i.input_id
                  WHERE i.assessment_id = NEW.assessment_id), '[]'));
END;

CREATE TRIGGER trg_impact_assessments_no_delete BEFORE DELETE ON impact_assessments
BEGIN SELECT RAISE(ABORT, 'impact assessments cannot be deleted'); END;

-- Event refutation: every non-terminal current assessment of the event is withdrawn by the system,
-- each with a new audit revision, in the same transaction as the event update.
CREATE TRIGGER trg_events_refutation_withdraws_assessments AFTER UPDATE OF verification_state ON events
WHEN NEW.verification_state = 'refuted' AND OLD.verification_state <> 'refuted'
BEGIN
    UPDATE impact_assessments
       SET assessment_status = 'withdrawn_evidence_invalid', status_reason = 'event_refuted',
           actor_type = 'system', changed_by = 'system:event_refutation',
           change_reason = 'event refuted (event revision ' || NEW.current_revision || ')',
           current_revision = current_revision + 1,
           updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
     WHERE event_id = NEW.event_id AND scenario_kind = 'current'
       AND assessment_status NOT IN ('withdrawn_evidence_invalid','rejected_by_review');
END;

-- Close the 0003 gap: analyses are versioned and now also delete-protected.
CREATE TRIGGER trg_analyses_no_delete BEFORE DELETE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are versioned records and cannot be deleted'); END;


-- ---------------------------------------------------------------- duplicate-key guards (REPLACE bypass)
-- SQLite's REPLACE conflict resolution deletes the existing row WITHOUT firing delete triggers unless
-- recursive_triggers is on. These BEFORE INSERT guards run before conflict resolution and refuse any
-- insert whose primary or unique key already exists, so INSERT OR REPLACE / REPLACE INTO can never
-- overwrite an immutable or audited row. Ordinary first-time inserts are unaffected.
CREATE TRIGGER trg_impact_expiry_policy_versions_no_replace BEFORE INSERT ON impact_expiry_policy_versions
WHEN EXISTS (SELECT 1 FROM impact_expiry_policy_versions t WHERE t.policy_version = NEW.policy_version)
BEGIN SELECT RAISE(ABORT, 'impact_expiry_policy_versions: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_expiry_policy_events_no_replace BEFORE INSERT ON impact_expiry_policy_events
WHEN EXISTS (SELECT 1 FROM impact_expiry_policy_events t WHERE t.policy_event_id = NEW.policy_event_id OR (t.policy_version = NEW.policy_version AND t.event_type = NEW.event_type))
BEGIN SELECT RAISE(ABORT, 'impact_expiry_policy_events: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_assessments_no_replace BEFORE INSERT ON impact_assessments
WHEN EXISTS (SELECT 1 FROM impact_assessments t WHERE t.assessment_id = NEW.assessment_id OR (t.event_id = NEW.event_id AND t.company_id = NEW.company_id AND t.mechanism_id = NEW.mechanism_id AND t.scenario_kind = NEW.scenario_kind AND t.transmission_version = NEW.transmission_version))
BEGIN SELECT RAISE(ABORT, 'impact_assessments: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_reviews_no_replace BEFORE INSERT ON impact_reviews
WHEN EXISTS (SELECT 1 FROM impact_reviews t WHERE t.review_id = NEW.review_id)
BEGIN SELECT RAISE(ABORT, 'impact_reviews: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_assessment_inputs_no_replace BEFORE INSERT ON impact_assessment_inputs
WHEN EXISTS (SELECT 1 FROM impact_assessment_inputs t WHERE t.input_id = NEW.input_id)
BEGIN SELECT RAISE(ABORT, 'impact_assessment_inputs: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_assessment_revisions_no_replace BEFORE INSERT ON impact_assessment_revisions
WHEN EXISTS (SELECT 1 FROM impact_assessment_revisions t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no)
BEGIN SELECT RAISE(ABORT, 'impact_assessment_revisions: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_transmission_steps_no_replace BEFORE INSERT ON impact_transmission_steps
WHEN EXISTS (SELECT 1 FROM impact_transmission_steps t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no AND t.step_no = NEW.step_no)
BEGIN SELECT RAISE(ABORT, 'impact_transmission_steps: duplicate key; existing rows cannot be replaced'); END;
CREATE TRIGGER trg_impact_scenarios_no_replace BEFORE INSERT ON impact_scenarios
WHEN EXISTS (SELECT 1 FROM impact_scenarios t WHERE t.assessment_id = NEW.assessment_id AND t.revision_no = NEW.revision_no AND t.scenario_case = NEW.scenario_case)
BEGIN SELECT RAISE(ABORT, 'impact_scenarios: duplicate key; existing rows cannot be replaced'); END;

-- ---------------------------------------------------------------- review binding (replay protection)
-- Every human review is single-use and bound to exactly one transition of its own assessment: it must be
-- the assessment's newest review, never previously linked to any revision, and can only be linked by a
-- human decision. A partial unique index makes reuse impossible even if a trigger were bypassed. The binding checks themselves are in trg_impact_assessments_update.
CREATE UNIQUE INDEX ux_impact_revisions_review_once ON impact_assessment_revisions(review_id)
WHERE review_id IS NOT NULL;

-- ---------------------------------------------------------------- linked exposure evidence is immutable
-- Once a company_exposures record backs an exposure candidate (it is referenced by
-- exposure_candidate_evidence.company_exposure_id, which the 0008 schema allows only with role
-- 'company_specific'), its evidentiary contents can no longer change. Otherwise an expired record could be
-- 'revived' by editing valid_to (or any other field) without a new candidate revision or human review.
-- A correction is a retraction (evidence_retractions) plus a NEW exposure record; expiry then depends only on
-- the database clock and is irreversible for that record. Unlinked records keep the existing behaviour.
-- (Additive: new triggers on a 0002 table; 0002 itself is unchanged.)
CREATE TRIGGER trg_company_exposures_linked_immutable BEFORE UPDATE ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l
             WHERE l.company_exposure_id IN (OLD.exposure_id, NEW.exposure_id))
 AND (NEW.exposure_id IS NOT OLD.exposure_id OR NEW.valid_to IS NOT OLD.valid_to
      OR NEW.valid_from IS NOT OLD.valid_from OR NEW.company_id IS NOT OLD.company_id
      OR NEW.exposure_kind IS NOT OLD.exposure_kind OR NEW.subject IS NOT OLD.subject
      OR NEW.confidence IS NOT OLD.confidence OR NEW.source_item_id IS NOT OLD.source_item_id
      OR NEW.evidence_excerpt IS NOT OLD.evidence_excerpt OR NEW.last_verified_utc IS NOT OLD.last_verified_utc
      OR NEW.segment_id IS NOT OLD.segment_id OR NEW.scope IS NOT OLD.scope)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate is immutable; retract it and record a new exposure'); END;
-- REPLACE / INSERT OR REPLACE onto a linked record's key would delete and re-create it without firing
-- UPDATE or DELETE triggers (recursive_triggers off), so the key itself is guarded before conflict resolution.
CREATE TRIGGER trg_company_exposures_linked_no_replace BEFORE INSERT ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l WHERE l.company_exposure_id = NEW.exposure_id)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate cannot be replaced'); END;
CREATE TRIGGER trg_company_exposures_linked_no_delete BEFORE DELETE ON company_exposures
WHEN EXISTS (SELECT 1 FROM exposure_candidate_evidence l WHERE l.company_exposure_id = OLD.exposure_id)
BEGIN SELECT RAISE(ABORT, 'company_exposures: evidence linked to an exposure candidate cannot be deleted'); END;

-- ---------------------------------------------------------------- retractions are permanent
-- evidence_retractions (0008) is protected against UPDATE and DELETE, but REPLACE deletes the conflicting row
-- without firing delete triggers (recursive_triggers off). A REPLACE reusing a retraction_id, or a
-- (record_table, record_id) pair, could therefore erase a retraction, after which the retracted evidence
-- could be re-mapped and re-accepted with no trace. This guard runs before conflict resolution and refuses any
-- insert that collides with either identity. (Additive: 0008 is unchanged; migration 0010 covers the
-- remaining legacy tables.)
CREATE TRIGGER trg_evidence_retractions_no_replace BEFORE INSERT ON evidence_retractions
WHEN EXISTS (SELECT 1 FROM evidence_retractions r
             WHERE r.retraction_id = NEW.retraction_id
                OR (r.record_table = NEW.record_table AND r.record_id = NEW.record_id))
BEGIN SELECT RAISE(ABORT, 'evidence_retractions: a retraction already exists for this id or record; retractions are permanent'); END;

-- ---------------------------------------------------------------- read models
CREATE VIEW impact_assessments_current AS
SELECT a.*,
       CASE WHEN a.assessment_status IN ('withdrawn_evidence_invalid','rejected_by_review') THEN a.assessment_status
            WHEN EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = a.assessment_id)
              THEN 'needs_revalidation'
            WHEN a.assessment_status = 'provisional' AND EXISTS (
                 SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
                   ON c.candidate_id = i.exposure_candidate_id
                 WHERE i.assessment_id = a.assessment_id AND i.exposure_candidate_id IS NOT NULL
                   AND (c.effective_status IS NULL OR c.effective_status NOT IN ('strongly_supported','confirmed')))
              THEN 'needs_revalidation'
            WHEN a.assessment_status = 'confirmed_conclusion' AND EXISTS (
                 SELECT 1 FROM impact_assessment_inputs i LEFT JOIN exposure_candidates_current c
                   ON c.candidate_id = i.exposure_candidate_id
                 WHERE i.assessment_id = a.assessment_id AND i.exposure_candidate_id IS NOT NULL
                   AND (c.effective_status IS NULL OR c.effective_status <> 'confirmed'))
              THEN 'needs_revalidation'
            WHEN a.assessment_status IN ('provisional','confirmed_conclusion')
                 AND (a.freshness_basis <> 'explicit_source_expiry' OR NOT EXISTS (
                      SELECT 1 FROM impact_explicit_freshness f WHERE f.assessment_id = a.assessment_id))
              THEN 'needs_revalidation'
            ELSE a.assessment_status END AS effective_status,
       CASE WHEN EXISTS (SELECT 1 FROM impact_invalid_inputs v WHERE v.assessment_id = a.assessment_id)
            THEN 0 ELSE 1 END AS inputs_currently_valid,
       CASE WHEN a.is_synthetic = 1 THEN 'SYNTHETIC TEST DATA' ELSE 'real' END AS data_label
FROM impact_assessments a;

-- Point-in-time company eligibility per event: sector classification valid at the event date (or the
-- current classification for undated events), and listing status established from company_status_history.
CREATE VIEW impact_event_company_eligibility AS
WITH ev AS (
    SELECT e.event_id,
           CASE WHEN e.event_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN e.event_date END AS d
    FROM events e
), cls AS (
    SELECT ev.event_id, cc.company_id, cc.sector_id,
           CASE WHEN ev.d IS NULL THEN 'current_classification' ELSE 'event_date_classification' END AS basis,
           ev.d
    FROM ev JOIN company_classifications cc
      ON (ev.d IS NULL AND cc.valid_to IS NULL)
      OR (ev.d IS NOT NULL AND (cc.valid_from IS NULL OR cc.valid_from <= ev.d)
          AND (cc.valid_to IS NULL OR cc.valid_to >= ev.d))
)
SELECT cls.event_id, cls.company_id, cls.sector_id, cls.basis AS eligibility_basis,
       CASE
         WHEN cls.d IS NULL THEN CASE c.listing_status WHEN 'listed' THEN 'listed' WHEN 'suspended' THEN 'suspended'
                                     WHEN 'delisted' THEN 'not_listed' ELSE 'unknown' END
         ELSE COALESCE(
           (SELECT CASE h.status WHEN 'listed' THEN 'listed' WHEN 'suspended' THEN 'suspended'
                                 ELSE 'not_listed' END
            FROM company_status_history h
            WHERE h.company_id = cls.company_id AND h.effective_date IS NOT NULL AND h.effective_date <= cls.d
              AND h.status IN ('listed','suspended','delisted','merged_into')
            ORDER BY h.effective_date DESC, h.status_event_id DESC LIMIT 1),
           CASE WHEN c.listing_status = 'listed' AND NOT EXISTS (
                       SELECT 1 FROM company_status_history h2 WHERE h2.company_id = cls.company_id)
                THEN 'listed' ELSE 'unknown' END)
       END AS listing_at_event
FROM cls JOIN companies c ON c.company_id = cls.company_id;

-- Companies without a sector classification at the event date are reported separately, never assigned.
CREATE VIEW impact_unclassified_companies AS
SELECT DISTINCT a.event_id, a.company_id, 'no_sector_classification' AS reason
FROM impact_assessments a
WHERE NOT EXISTS (SELECT 1 FROM impact_event_company_eligibility g
                  WHERE g.event_id = a.event_id AND g.company_id = a.company_id);

CREATE VIEW impact_sector_aggregates_current AS
WITH combos AS (
    SELECT DISTINCT g.sector_id, a.event_id, a.mechanism_id, a.scenario_kind, a.transmission_version,
                    g.eligibility_basis
    FROM impact_assessments a JOIN impact_event_company_eligibility g
      ON g.event_id = a.event_id AND g.company_id = a.company_id
), members AS (
    SELECT k.*, g.company_id, g.listing_at_event,
           x.assessment_id, x.effective_status, x.direction, x.is_synthetic,
           CASE
             WHEN g.listing_at_event = 'not_listed' THEN 'not_listed_at_event_date'
             WHEN g.listing_at_event = 'suspended' THEN 'suspended_at_event_date'
             WHEN g.listing_at_event = 'unknown' THEN 'listing_status_unknown'
             WHEN x.assessment_id IS NULL THEN 'no_assessment'
             WHEN x.effective_status = 'needs_review' THEN 'assessment_needs_review'
             WHEN x.effective_status = 'needs_revalidation' THEN 'assessment_needs_revalidation'
             WHEN x.effective_status = 'withdrawn_evidence_invalid' THEN 'assessment_withdrawn'
             WHEN x.effective_status = 'rejected_by_review' THEN 'assessment_rejected'
           END AS exclusion_reason
    FROM combos k
    JOIN impact_event_company_eligibility g ON g.event_id = k.event_id AND g.sector_id = k.sector_id
    LEFT JOIN impact_assessments_current x
      ON x.event_id = k.event_id AND x.company_id = g.company_id AND x.mechanism_id = k.mechanism_id
     AND x.scenario_kind = k.scenario_kind AND x.transmission_version = k.transmission_version
), agg AS (
    SELECT sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis,
           SUM(listing_at_event <> 'not_listed') AS eligible_n,
           SUM(listing_at_event <> 'not_listed' AND assessment_id IS NOT NULL
               AND effective_status IN ('scenario_only','provisional','confirmed_conclusion')) AS assessed_valid_n,
           SUM(listing_at_event <> 'not_listed'
               AND effective_status IN ('needs_review','needs_revalidation')) AS assessed_review_n,
           SUM(listing_at_event <> 'not_listed'
               AND effective_status IN ('withdrawn_evidence_invalid','rejected_by_review')) AS assessed_terminal_n,
           SUM(listing_at_event <> 'not_listed' AND assessment_id IS NULL) AS unassessed_n,
           SUM(listing_at_event = 'suspended') AS suspended_n,
           SUM(listing_at_event = 'unknown') AS eligibility_uncertain_n,
           SUM(exclusion_reason IS NULL AND direction = 'positive') AS positive_n,
           SUM(exclusion_reason IS NULL AND direction = 'negative') AS negative_n,
           SUM(exclusion_reason IS NULL AND direction = 'mixed') AS mixed_n,
           SUM(exclusion_reason IS NULL AND direction = 'neutral') AS neutral_n,
           SUM(exclusion_reason IS NULL AND direction = 'unknown') AS unknown_n,
           SUM(exclusion_reason IS NULL) AS directional_n,
           SUM(exclusion_reason IS NULL AND effective_status = 'scenario_only') AS scenario_only_n,
           SUM(exclusion_reason IS NULL AND effective_status IN ('provisional','confirmed_conclusion'))
               AS evidence_backed_n,
           MIN(CASE WHEN exclusion_reason IS NULL THEN CASE effective_status
                    WHEN 'scenario_only' THEN 1 WHEN 'provisional' THEN 2 WHEN 'confirmed_conclusion' THEN 3 END
               END) AS weakest_rank,
           MAX(COALESCE(is_synthetic, 0)) AS is_synthetic,
           json_group_array(CASE WHEN exclusion_reason IS NULL THEN json_object('company_id', company_id,
               'assessment_id', assessment_id, 'effective_status', effective_status, 'direction', direction)
               END) AS included_raw,
           json_group_array(CASE WHEN exclusion_reason IS NOT NULL THEN json_object('company_id', company_id,
               'reason', exclusion_reason, 'listing_at_event', listing_at_event,
               'assessment_id', assessment_id, 'effective_status', effective_status) END) AS excluded_raw
    FROM members
    GROUP BY sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis
)
SELECT sector_id, event_id, mechanism_id, scenario_kind, transmission_version, eligibility_basis,
       eligible_n, assessed_valid_n, assessed_review_n, assessed_terminal_n, unassessed_n,
       suspended_n, eligibility_uncertain_n,
       CASE WHEN eligible_n > 0 THEN ROUND(100.0 * assessed_valid_n / eligible_n, 1) END AS coverage_pct,
       CASE WHEN eligible_n > 0 AND assessed_valid_n = eligible_n AND suspended_n = 0
                 AND eligibility_uncertain_n = 0 THEN 'complete' ELSE 'partial' END AS completeness,
       positive_n, negative_n, mixed_n, neutral_n, unknown_n,
       scenario_only_n, evidence_backed_n,
       CASE weakest_rank WHEN 1 THEN 'scenario_only' WHEN 2 THEN 'provisional'
            WHEN 3 THEN 'confirmed_conclusion' END AS weakest_status,
       CASE WHEN directional_n = 0 THEN 'unknown'
            WHEN positive_n = directional_n THEN 'positive'
            WHEN negative_n = directional_n THEN 'negative'
            WHEN neutral_n = directional_n THEN 'neutral'
            WHEN unknown_n > 0 AND (positive_n + unknown_n = directional_n OR negative_n + unknown_n = directional_n
                                    OR neutral_n + unknown_n = directional_n) THEN 'unknown'
            ELSE 'mixed' END AS direction_among_assessed,
       CASE WHEN NOT (eligible_n > 0 AND assessed_valid_n = eligible_n AND suspended_n = 0
                      AND eligibility_uncertain_n = 0) THEN 'not_concluded_partial_coverage'
            WHEN scenario_only_n > 0 THEN 'not_concluded_scenario_only_components'
            ELSE CASE WHEN directional_n = 0 THEN 'unknown'
                      WHEN positive_n = directional_n THEN 'positive'
                      WHEN negative_n = directional_n THEN 'negative'
                      WHEN neutral_n = directional_n THEN 'neutral'
                      WHEN unknown_n > 0 AND (positive_n + unknown_n = directional_n
                                              OR negative_n + unknown_n = directional_n
                                              OR neutral_n + unknown_n = directional_n) THEN 'unknown'
                      ELSE 'mixed' END
       END AS sector_conclusion,
       (SELECT json_group_array(json(value)) FROM json_each(included_raw) WHERE value IS NOT NULL) AS included_json,
       (SELECT json_group_array(json(value)) FROM json_each(excluded_raw) WHERE value IS NOT NULL) AS excluded_json,
       is_synthetic,
       CASE WHEN is_synthetic = 1 THEN 'SYNTHETIC TEST DATA' ELSE 'real' END AS data_label
FROM agg;
