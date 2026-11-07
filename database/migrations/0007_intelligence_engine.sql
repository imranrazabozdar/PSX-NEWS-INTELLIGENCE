-- 0007: Phase 3 intelligence engine (additive only). LLM call ledger, validated extractions,
-- story clusters and their members. Ledger and extractions are append-only audit records.

CREATE TABLE llm_calls (
    call_id            INTEGER PRIMARY KEY,
    called_at_utc      TEXT NOT NULL,
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    prompt_id          TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    prompt_sha256      TEXT NOT NULL CHECK (length(prompt_sha256) = 64),
    input_sha256       TEXT NOT NULL CHECK (length(input_sha256) = 64),
    input_tokens       INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cost_usd           REAL NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
    attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    outcome            TEXT NOT NULL CHECK (outcome IN ('ok','cached','invalid_output','error','refused_budget',
                                                        'refused_kill_switch','not_connected')),
    error              TEXT
);
CREATE INDEX ix_llm_calls_time ON llm_calls(called_at_utc);
CREATE TRIGGER trg_llm_calls_no_update BEFORE UPDATE ON llm_calls
BEGIN SELECT RAISE(ABORT, 'llm_calls are append-only'); END;
CREATE TRIGGER trg_llm_calls_no_delete BEFORE DELETE ON llm_calls
BEGIN SELECT RAISE(ABORT, 'llm_calls are append-only'); END;

CREATE TABLE event_extractions (
    extraction_id      INTEGER PRIMARY KEY,
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    event_id           INTEGER REFERENCES events(event_id),
    call_id            INTEGER REFERENCES llm_calls(call_id),
    schema_version     TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    model              TEXT NOT NULL,
    extracted_json     TEXT NOT NULL CHECK (json_valid(extracted_json)),
    confidence         REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    confidence_explanation TEXT NOT NULL,
    needs_human_review INTEGER NOT NULL CHECK (needs_human_review IN (0,1)),
    review_reasons_json TEXT NOT NULL CHECK (json_valid(review_reasons_json)),
    provenance_json    TEXT NOT NULL CHECK (json_valid(provenance_json)),
    created_at_utc     TEXT NOT NULL,
    UNIQUE (source_item_id, schema_version, prompt_version, model)
);
CREATE INDEX ix_event_extractions_review ON event_extractions(needs_human_review);
CREATE TRIGGER trg_event_extractions_no_update BEFORE UPDATE ON event_extractions
BEGIN SELECT RAISE(ABORT, 'event_extractions are append-only'); END;
CREATE TRIGGER trg_event_extractions_no_delete BEFORE DELETE ON event_extractions
BEGIN SELECT RAISE(ABORT, 'event_extractions are append-only'); END;

CREATE TABLE story_clusters (
    cluster_id         INTEGER PRIMARY KEY,
    cluster_key        TEXT NOT NULL UNIQUE,
    event_id           INTEGER REFERENCES events(event_id),
    created_at_utc     TEXT NOT NULL
);
CREATE TABLE story_cluster_members (
    cluster_id         INTEGER NOT NULL REFERENCES story_clusters(cluster_id),
    source_item_id     INTEGER NOT NULL REFERENCES source_items(source_item_id),
    similarity         REAL NOT NULL CHECK (similarity BETWEEN 0 AND 1),
    is_near_duplicate  INTEGER NOT NULL CHECK (is_near_duplicate IN (0,1)),
    added_at_utc       TEXT NOT NULL,
    PRIMARY KEY (cluster_id, source_item_id)
);
CREATE INDEX ix_story_cluster_members_item ON story_cluster_members(source_item_id);
