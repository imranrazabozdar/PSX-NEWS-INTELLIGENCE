-- 0002: events, append-only event revisions, claim-level evidence, event-company links and
-- evidence-backed company exposures (spec sections 8, 9, 11).

CREATE TABLE events (
    event_id          INTEGER PRIMARY KEY,
    event_type        TEXT NOT NULL,
    headline          TEXT NOT NULL,
    summary           TEXT,
    event_date        TEXT,
    event_date_precision TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (event_date_precision IN ('exact','day','month','quarter','year','unknown')),
    geography         TEXT,
    status_stage      TEXT NOT NULL CHECK (status_stage IN (
                        'rumour','discussion','proposal','consultation','committee_recommendation',
                        'approval','notification','implementation','amendment','delay','suspension',
                        'reversal','confirmed_fact','not_applicable')),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (verification_state IN ('unverified','single_source','corroborated',
                                                      'primary_confirmed','disputed','refuted')),
    direction         TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    magnitude         TEXT NOT NULL DEFAULT 'unknown' CHECK (magnitude IN ('low','medium','high','unknown')),
    novelty           TEXT NOT NULL DEFAULT 'unknown' CHECK (novelty IN ('new','update','repeat','unknown')),
    horizon           TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (horizon IN ('immediate','days_weeks','quarterly','annual','long_term','unknown')),
    confidence        REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    first_seen_at_utc TEXT NOT NULL,
    current_revision  INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    created_at_utc    TEXT NOT NULL,
    updated_at_utc    TEXT NOT NULL
);
CREATE INDEX ix_events_date ON events(event_date);
CREATE INDEX ix_events_stage ON events(status_stage);
CREATE INDEX ix_events_first_seen ON events(first_seen_at_utc);

-- Full snapshot of every version of an event. Never updated or deleted.
CREATE TABLE event_revisions (
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    revision_no       INTEGER NOT NULL CHECK (revision_no >= 1),
    recorded_at_utc   TEXT NOT NULL,
    status_stage      TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    headline          TEXT NOT NULL,
    summary           TEXT,
    snapshot_json     TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    change_reason     TEXT NOT NULL,
    changed_by        TEXT NOT NULL,
    model_version     TEXT,
    prompt_version    TEXT,
    PRIMARY KEY (event_id, revision_no)
);
CREATE TRIGGER trg_event_revisions_no_update BEFORE UPDATE ON event_revisions
BEGIN SELECT RAISE(ABORT, 'event_revisions are append-only'); END;
CREATE TRIGGER trg_event_revisions_no_delete BEFORE DELETE ON event_revisions
BEGIN SELECT RAISE(ABORT, 'event_revisions are append-only'); END;

-- An event may only move to a new revision that has already been recorded.
CREATE TRIGGER trg_events_require_revision BEFORE UPDATE ON events
WHEN NEW.current_revision <> OLD.current_revision + 1
  OR NOT EXISTS (SELECT 1 FROM event_revisions r
                 WHERE r.event_id = NEW.event_id AND r.revision_no = NEW.current_revision)
BEGIN SELECT RAISE(ABORT, 'update events only through a new recorded revision'); END;
CREATE TRIGGER trg_events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events cannot be deleted; record a revision instead'); END;

-- Evidence links one claim of an event to one source item, with the supporting excerpt.
CREATE TABLE event_evidence (
    evidence_id       INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    claim             TEXT NOT NULL,
    claim_type        TEXT NOT NULL CHECK (claim_type IN (
                        'verified_fact','official_statement','news_report','analyst_interpretation',
                        'personal_opinion','prediction','rumour','advertisement','model_inference','unclear')),
    relation          TEXT NOT NULL CHECK (relation IN ('supports','contradicts','context')),
    excerpt           TEXT NOT NULL CHECK (length(excerpt) BETWEEN 1 AND 1000),
    verification_state TEXT NOT NULL DEFAULT 'unverified'
                        CHECK (verification_state IN ('unverified','checked_against_primary','corroborated',
                                                      'disputed','refuted')),
    is_independent    INTEGER CHECK (is_independent IS NULL OR is_independent IN (0,1)),
    recorded_at_utc   TEXT NOT NULL,
    recorded_by       TEXT NOT NULL,
    UNIQUE (event_id, source_item_id, claim)
);
CREATE INDEX ix_evidence_event ON event_evidence(event_id);
CREATE INDEX ix_evidence_source_item ON event_evidence(source_item_id);
CREATE TRIGGER trg_evidence_no_update BEFORE UPDATE ON event_evidence
BEGIN SELECT RAISE(ABORT, 'event_evidence is append-only; add a new evidence row'); END;
CREATE TRIGGER trg_evidence_no_delete BEFORE DELETE ON event_evidence
BEGIN SELECT RAISE(ABORT, 'event_evidence is append-only'); END;

CREATE TABLE event_companies (
    event_company_id  INTEGER PRIMARY KEY,
    event_id          INTEGER NOT NULL REFERENCES events(event_id),
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    exposure_type     TEXT NOT NULL CHECK (exposure_type IN ('direct','indirect','uncertain','excluded')),
    impact_direction  TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (impact_direction IN ('positive','negative','mixed','neutral','unknown')),
    channel           TEXT,
    rationale         TEXT NOT NULL,
    confidence        REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    reviewer_status   TEXT NOT NULL DEFAULT 'pending' CHECK (reviewer_status IN ('pending','accepted','rejected')),
    created_at_utc    TEXT NOT NULL,
    UNIQUE (event_id, company_id)
);
CREATE INDEX ix_event_companies_company ON event_companies(company_id);

CREATE TABLE company_exposures (
    exposure_id       INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    segment_id        INTEGER REFERENCES company_segments(segment_id),
    exposure_kind     TEXT NOT NULL CHECK (exposure_kind IN ('input','product','market','geography','customer',
                                                             'supplier','fx','debt','regulation','logistics','energy')),
    subject           TEXT NOT NULL,
    scope             TEXT,
    confidence        TEXT NOT NULL CHECK (confidence IN ('documented','probable','uncertain')),
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    evidence_excerpt  TEXT NOT NULL,
    valid_from        TEXT,
    valid_to          TEXT,
    last_verified_utc TEXT NOT NULL
);
CREATE INDEX ix_exposures_company ON company_exposures(company_id);
CREATE INDEX ix_exposures_subject ON company_exposures(subject);
