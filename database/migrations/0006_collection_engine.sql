-- 0006: Phase 2 collection engine (ADR-0005). Additive only: new columns, tables, triggers
-- and a view. No existing column, constraint or row is changed or removed.

-- ---------------------------------------------------------------- source registry
ALTER TABLE sources ADD COLUMN official_url TEXT;
ALTER TABLE sources ADD COLUMN category TEXT;
ALTER TABLE sources ADD COLUMN subcategory TEXT;
ALTER TABLE sources ADD COLUMN geographic_coverage TEXT;
ALTER TABLE sources ADD COLUMN industries_json TEXT CHECK (industries_json IS NULL OR json_valid(industries_json));
ALTER TABLE sources ADD COLUMN related_companies_json TEXT
    CHECK (related_companies_json IS NULL OR json_valid(related_companies_json));
ALTER TABLE sources ADD COLUMN content_format TEXT NOT NULL DEFAULT 'unknown'
    CHECK (content_format IN ('rss','atom','api','html','pdf','mixed','social','video','unknown'));
ALTER TABLE sources ADD COLUMN feed_url TEXT;
ALTER TABLE sources ADD COLUMN adapter TEXT;
ALTER TABLE sources ADD COLUMN retention_mode TEXT NOT NULL DEFAULT 'metadata_only'
    CHECK (retention_mode IN ('metadata_only','excerpt','full_text_permitted'));
ALTER TABLE sources ADD COLUMN terms_status TEXT NOT NULL DEFAULT 'not_reviewed'
    CHECK (terms_status IN ('not_reviewed','not_found','reviewed_ok','restricted','prohibits_automation',
                            'licence_required','approved'));
ALTER TABLE sources ADD COLUMN licensing_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (licensing_status IN ('unknown','public_domain','open_licence','free_with_attribution',
                                'personal_non_commercial','permission_required','licence_required','paid_api'));
ALTER TABLE sources ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('unverified','url_verified','identity_verified','unreachable'));
ALTER TABLE sources ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'NOT REVIEWED'
    CHECK (lifecycle_status IN ('NOT REVIEWED','REVIEWED','APPROVED','RESTRICTED','LICENCE REQUIRED',
                                'BLOCKED','IMPLEMENTED','TESTED','ACTIVE','DISABLED'));
ALTER TABLE sources ADD COLUMN priority INTEGER CHECK (priority IS NULL OR priority BETWEEN 1 AND 5);
ALTER TABLE sources ADD COLUMN collection_frequency_minutes INTEGER
    CHECK (collection_frequency_minutes IS NULL OR collection_frequency_minutes >= 60);
ALTER TABLE sources ADD COLUMN review_notes TEXT;
ALTER TABLE sources ADD COLUMN reviewed_at_utc TEXT;
ALTER TABLE sources ADD COLUMN last_attempt_at_utc TEXT;
ALTER TABLE sources ADD COLUMN last_error TEXT;
ALTER TABLE sources ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0);
ALTER TABLE sources ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0);
ALTER TABLE sources ADD COLUMN last_content_at_utc TEXT;

-- A source can only be ACTIVE once its terms are approved and its access verified.
CREATE TRIGGER trg_sources_active_requires_approval BEFORE UPDATE OF lifecycle_status ON sources
WHEN NEW.lifecycle_status = 'ACTIVE'
 AND (NEW.terms_status <> 'approved' OR NEW.access_status <> 'verified_permitted' OR NEW.enabled <> 1)
BEGIN SELECT RAISE(ABORT, 'ACTIVE requires approved terms, verified access and enabled = 1'); END;

CREATE TRIGGER trg_sources_insert_active_requires_approval BEFORE INSERT ON sources
WHEN NEW.lifecycle_status = 'ACTIVE'
 AND (NEW.terms_status <> 'approved' OR NEW.access_status <> 'verified_permitted' OR NEW.enabled <> 1)
BEGIN SELECT RAISE(ABORT, 'ACTIVE requires approved terms, verified access and enabled = 1'); END;

-- ---------------------------------------------------------------- collection runs
ALTER TABLE collector_runs ADD COLUMN items_duplicate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collector_runs ADD COLUMN items_new_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collector_runs ADD COLUMN items_failed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collector_runs ADD COLUMN http_requests INTEGER NOT NULL DEFAULT 0;
ALTER TABLE collector_runs ADD COLUMN http_status INTEGER;
ALTER TABLE collector_runs ADD COLUMN duration_ms INTEGER;
ALTER TABLE collector_runs ADD COLUMN not_modified INTEGER NOT NULL DEFAULT 0 CHECK (not_modified IN (0,1));

-- ---------------------------------------------------------------- item provenance
ALTER TABLE source_items ADD COLUMN original_url TEXT;
ALTER TABLE source_items ADD COLUMN retrieval_method TEXT
    CHECK (retrieval_method IS NULL OR retrieval_method IN ('rss','atom','api','html','pdf','manual','seed'));
ALTER TABLE source_items ADD COLUMN collection_run_id INTEGER REFERENCES collector_runs(run_id);
ALTER TABLE source_items ADD COLUMN http_status INTEGER;
ALTER TABLE source_items ADD COLUMN document_type TEXT;
ALTER TABLE source_items ADD COLUMN publication_time_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (publication_time_status IN ('known','date_only','unavailable','unknown'));
ALTER TABLE source_items ADD COLUMN source_metadata_json TEXT
    CHECK (source_metadata_json IS NULL OR json_valid(source_metadata_json));

CREATE TRIGGER trg_source_items_original_url_immutable BEFORE UPDATE OF original_url, retrieval_method,
    collection_run_id, publication_time_status ON source_items
WHEN OLD.original_url IS NOT NULL OR OLD.collection_run_id IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'source_items provenance fields are immutable; append a version instead'); END;

ALTER TABLE source_item_versions ADD COLUMN collection_run_id INTEGER REFERENCES collector_runs(run_id);
ALTER TABLE source_item_versions ADD COLUMN title TEXT;

CREATE INDEX ix_source_items_run ON source_items(collection_run_id);
CREATE INDEX ix_collector_runs_status ON collector_runs(status, started_at_utc);

-- ---------------------------------------------------------------- incremental collection
CREATE TABLE collector_checkpoints (
    source_id              TEXT PRIMARY KEY REFERENCES sources(source_id),
    endpoint_url           TEXT NOT NULL,
    etag                   TEXT,
    last_modified          TEXT,
    last_seen_external_id  TEXT,
    last_seen_published_utc TEXT,
    cursor                 TEXT,
    updated_at_utc         TEXT NOT NULL
);

-- ---------------------------------------------------------------- media watchlist
ALTER TABLE media_accounts ADD COLUMN category TEXT;
ALTER TABLE media_accounts ADD COLUMN access_status TEXT NOT NULL DEFAULT 'no_authorised_access'
    CHECK (access_status IN ('no_authorised_access','official_api_required','authorised','not_applicable'));

-- ---------------------------------------------------------------- source health
CREATE VIEW source_health AS
SELECT s.source_id,
       s.lifecycle_status,
       s.last_attempt_at_utc,
       s.last_success_at_utc,
       s.last_error,
       s.consecutive_failures,
       s.failure_count,
       s.last_content_at_utc,
       COUNT(r.run_id)                                          AS runs,
       SUM(CASE WHEN r.status = 'succeeded' THEN 1 ELSE 0 END)  AS runs_succeeded,
       SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END)     AS runs_failed,
       ROUND(AVG(r.duration_ms))                                AS avg_duration_ms,
       SUM(r.items_accepted)                                    AS items_new,
       SUM(r.items_duplicate)                                   AS items_duplicate,
       SUM(r.items_new_version)                                 AS items_new_version,
       SUM(r.items_failed)                                      AS items_failed,
       MAX(CASE WHEN r.status = 'failed' THEN r.started_at_utc END) AS last_failed_run_utc
FROM sources s LEFT JOIN collector_runs r ON r.source_id = s.source_id AND r.status <> 'dry_run'
GROUP BY s.source_id;
