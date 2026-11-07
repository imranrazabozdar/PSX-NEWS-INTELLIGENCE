-- 0004: social / media intelligence schema (spec section 4), collector runs and user watchlist.
-- Media collection itself is Phase 11; this phase only stores the supplied identifiers.

CREATE TABLE media_accounts (
    account_id      INTEGER PRIMARY KEY,
    platform        TEXT NOT NULL CHECK (platform IN ('x','youtube')),
    handle          TEXT,
    platform_account_id TEXT,
    supplied_url    TEXT,
    display_name    TEXT,
    person_or_org   TEXT,
    account_type    TEXT,
    monitoring_purpose TEXT,
    identity_verification TEXT NOT NULL DEFAULT 'unverified'
                      CHECK (identity_verification IN ('unverified','pending_confirmation','verified','rejected')),
    reliability_tier TEXT NOT NULL DEFAULT 'unrated',
    monitoring_status TEXT NOT NULL DEFAULT 'disabled'
                      CHECK (monitoring_status IN ('disabled','pending_handle','active','paused')),
    source_id       TEXT REFERENCES sources(source_id),
    notes           TEXT,
    created_at_utc  TEXT NOT NULL,
    CHECK (handle IS NOT NULL OR monitoring_status = 'pending_handle'),
    -- collection may only be active for a verified identity
    CHECK (monitoring_status <> 'active' OR identity_verification = 'verified')
);
CREATE UNIQUE INDEX ux_media_accounts_handle ON media_accounts(platform, handle) WHERE handle IS NOT NULL;

CREATE TABLE media_items (
    media_item_id   INTEGER PRIMARY KEY,
    platform        TEXT NOT NULL CHECK (platform IN ('x','youtube')),
    external_id     TEXT NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES media_accounts(account_id),
    canonical_url   TEXT NOT NULL,
    published_at_utc TEXT,
    published_at_raw TEXT,
    collected_at_utc TEXT NOT NULL,
    language        TEXT,
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64),
    text_pointer    TEXT,
    permitted_excerpt TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000),
    transcript_status TEXT NOT NULL DEFAULT 'not_applicable'
                      CHECK (transcript_status IN ('not_applicable','available','unavailable','pending','manual')),
    relevance_priority TEXT CHECK (relevance_priority IN ('high','conditional','low')),
    relevance_reason TEXT,
    rejection_reason TEXT,
    UNIQUE (platform, external_id)
);
CREATE INDEX ix_media_items_published ON media_items(published_at_utc);

CREATE TABLE media_mentions (
    mention_id      INTEGER PRIMARY KEY,
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    company_id      TEXT REFERENCES companies(company_id),
    entity          TEXT NOT NULL,
    mention_type    TEXT NOT NULL,
    sentiment       TEXT CHECK (sentiment IN ('positive','negative','mixed','neutral')),
    claim_type      TEXT NOT NULL CHECK (claim_type IN (
                      'verified_fact','official_statement','news_report','analyst_interpretation',
                      'personal_opinion','prediction','rumour','advertisement','unclear')),
    context_excerpt TEXT,
    relevance_score REAL CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1)
);

CREATE TABLE media_event_links (
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    event_id        INTEGER NOT NULL REFERENCES events(event_id),
    evidence_role   TEXT NOT NULL CHECK (evidence_role IN ('lead','supporting','contradicting','context')),
    independence    TEXT NOT NULL CHECK (independence IN ('independent','same_source','repost','syndicated','unknown')),
    confidence      REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    PRIMARY KEY (media_item_id, event_id)
);

CREATE TABLE media_predictions (
    prediction_id   INTEGER PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES media_accounts(account_id),
    media_item_id   INTEGER NOT NULL REFERENCES media_items(media_item_id),
    company_id      TEXT REFERENCES companies(company_id),
    direction       TEXT CHECK (direction IN ('positive','negative','mixed','neutral')),
    target          REAL,
    horizon         TEXT,
    prediction_date TEXT NOT NULL,
    assumptions     TEXT,
    result          TEXT,
    evaluated_at_utc TEXT
);

CREATE TABLE media_metrics_history (
    media_item_id   INTEGER REFERENCES media_items(media_item_id),
    account_id      INTEGER REFERENCES media_accounts(account_id),
    observed_at_utc TEXT NOT NULL,
    views INTEGER, likes INTEGER, reposts INTEGER, replies INTEGER, quotes INTEGER,
    CHECK (media_item_id IS NOT NULL OR account_id IS NOT NULL)
);
CREATE INDEX ix_media_metrics_item ON media_metrics_history(media_item_id, observed_at_utc);

CREATE TABLE collector_runs (
    run_id          INTEGER PRIMARY KEY,
    job             TEXT NOT NULL,
    source_id       TEXT REFERENCES sources(source_id),
    started_at_utc  TEXT NOT NULL,
    finished_at_utc TEXT,
    status          TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','partial','dry_run')),
    items_fetched   INTEGER NOT NULL DEFAULT 0,
    items_accepted  INTEGER NOT NULL DEFAULT 0,
    items_rejected  INTEGER NOT NULL DEFAULT 0,
    errors          TEXT,
    quota_usage_json TEXT CHECK (quota_usage_json IS NULL OR json_valid(quota_usage_json)),
    log_reference   TEXT
);
CREATE INDEX ix_collector_runs_source ON collector_runs(source_id, started_at_utc);

CREATE TABLE user_watchlist (
    watch_id        INTEGER PRIMARY KEY,
    item_type       TEXT NOT NULL CHECK (item_type IN ('ticker','keyword','account','sector','commodity')),
    value           TEXT NOT NULL,
    alert_preferences_json TEXT CHECK (alert_preferences_json IS NULL OR json_valid(alert_preferences_json)),
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at_utc  TEXT NOT NULL,
    UNIQUE (item_type, value)
);
