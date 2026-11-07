-- 0001: source registry, source items (provenance), company master, identifiers, aliases,
-- classifications, status history and index membership.
-- Conventions (docs/DATA_MODEL.md): timestamps are ISO-8601 UTC text ending in 'Z';
-- original source strings are kept in *_raw columns. Nothing in this file deletes data.

CREATE TABLE sources (
    source_id          TEXT PRIMARY KEY CHECK (source_id GLOB '[a-z0-9]*' AND length(source_id) <= 64),
    name               TEXT NOT NULL,
    source_type        TEXT NOT NULL CHECK (source_type IN (
                         'exchange','official_regulator','government','news_media','international_news',
                         'broker_research','asset_manager','industry_body','data_provider',
                         'social_x','social_youtube','other')),
    domain             TEXT,
    platform           TEXT,
    owner              TEXT,
    reliability_tier   TEXT NOT NULL DEFAULT 'unrated'
                         CHECK (reliability_tier IN ('primary_official','established_media','specialist',
                                                     'commentary','unrated')),
    access_method      TEXT NOT NULL DEFAULT 'pending_review'
                         CHECK (access_method IN ('rss','official_api','html_permitted','pdf','manual',
                                                  'authorised_provider','pending_review','not_permitted')),
    access_status      TEXT NOT NULL DEFAULT 'unverified'
                         CHECK (access_status IN ('unverified','verified_permitted','restricted',
                                                  'licence_required','blocked')),
    terms_notes        TEXT,
    terms_reviewed_at_utc TEXT,
    update_cadence     TEXT,
    enabled            INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    last_success_at_utc TEXT,
    notes              TEXT,
    created_at_utc     TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL,
    -- a source can only be enabled for collection after its access/terms are verified
    CHECK (enabled = 0 OR access_status = 'verified_permitted')
);

CREATE TABLE source_items (
    source_item_id       INTEGER PRIMARY KEY,
    source_id            TEXT NOT NULL REFERENCES sources(source_id),
    canonical_url        TEXT,
    external_id          TEXT,
    title                TEXT,
    language             TEXT,
    published_at_utc     TEXT,
    published_at_raw     TEXT,
    published_tz_offset  TEXT,
    event_date           TEXT,
    collected_at_utc     TEXT NOT NULL,
    content_sha256       TEXT NOT NULL CHECK (length(content_sha256) = 64),
    permitted_excerpt    TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000),
    content_location     TEXT,
    access_status        TEXT NOT NULL DEFAULT 'public'
                           CHECK (access_status IN ('public','permitted','restricted','unavailable')),
    duplicate_of_item_id INTEGER REFERENCES source_items(source_item_id),
    relevance_score      REAL CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1),
    relevance_reason     TEXT,
    CHECK (canonical_url IS NOT NULL OR external_id IS NOT NULL),
    UNIQUE (source_id, canonical_url),
    UNIQUE (source_id, external_id)
);
CREATE INDEX ix_source_items_published ON source_items(published_at_utc);
CREATE INDEX ix_source_items_collected ON source_items(collected_at_utc);
CREATE INDEX ix_source_items_hash ON source_items(content_sha256);
CREATE INDEX ix_source_items_event_date ON source_items(event_date);

-- Each time an item's content changes, a new version is appended; versions are never edited.
CREATE TABLE source_item_versions (
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    version_no        INTEGER NOT NULL CHECK (version_no >= 1),
    content_sha256    TEXT NOT NULL CHECK (length(content_sha256) = 64),
    collected_at_utc  TEXT NOT NULL,
    permitted_excerpt TEXT CHECK (permitted_excerpt IS NULL OR length(permitted_excerpt) <= 1000),
    PRIMARY KEY (source_item_id, version_no),
    UNIQUE (source_item_id, content_sha256)
);

CREATE TRIGGER trg_source_items_no_delete BEFORE DELETE ON source_items
BEGIN SELECT RAISE(ABORT, 'source_items are append-only: deletion is not allowed'); END;

CREATE TRIGGER trg_source_items_immutable BEFORE UPDATE OF
    source_id, canonical_url, external_id, collected_at_utc, content_sha256, published_at_raw
ON source_items
BEGIN SELECT RAISE(ABORT, 'source_items provenance fields are immutable; append a version instead'); END;

CREATE TRIGGER trg_source_item_versions_no_update BEFORE UPDATE ON source_item_versions
BEGIN SELECT RAISE(ABORT, 'source_item_versions are append-only'); END;
CREATE TRIGGER trg_source_item_versions_no_delete BEFORE DELETE ON source_item_versions
BEGIN SELECT RAISE(ABORT, 'source_item_versions are append-only'); END;

CREATE TABLE sectors (
    sector_id      TEXT PRIMARY KEY,
    scheme         TEXT NOT NULL CHECK (scheme IN ('PSX')),
    name           TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (scheme, name)
);

-- company_id is a permanent identifier; it never changes when a ticker or name changes.
CREATE TABLE companies (
    company_id            TEXT PRIMARY KEY CHECK (company_id GLOB 'cmp-*'),
    legal_name            TEXT NOT NULL,
    listing_status        TEXT NOT NULL CHECK (listing_status IN ('listed','delisted','suspended','unknown')),
    fiscal_year_end_month INTEGER CHECK (fiscal_year_end_month BETWEEN 1 AND 12),
    share_class           TEXT NOT NULL DEFAULT 'ordinary',
    website               TEXT,
    business_summary      TEXT CHECK (business_summary IS NULL OR length(business_summary) <= 600),
    profile_source_item_id INTEGER REFERENCES source_items(source_item_id),
    created_at_utc        TEXT NOT NULL,
    updated_at_utc        TEXT NOT NULL
);
CREATE INDEX ix_companies_status ON companies(listing_status);

CREATE TABLE company_identifiers (
    identifier_id   INTEGER PRIMARY KEY,
    company_id      TEXT NOT NULL REFERENCES companies(company_id),
    id_type         TEXT NOT NULL CHECK (id_type IN ('psx_ticker','isin')),
    value           TEXT NOT NULL,
    valid_from      TEXT,            -- NULL = start date not known (never guessed)
    valid_to        TEXT,            -- NULL = still current
    verified_at_utc TEXT NOT NULL,   -- when this project last verified the record
    source_item_id  INTEGER REFERENCES source_items(source_item_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    CHECK (id_type <> 'psx_ticker' OR value GLOB '[A-Z0-9]*'),
    UNIQUE (id_type, value, valid_from)
);
-- one current holder per ticker
CREATE UNIQUE INDEX ux_identifiers_current ON company_identifiers(id_type, value) WHERE valid_to IS NULL;
CREATE INDEX ix_identifiers_company ON company_identifiers(company_id);

CREATE TABLE company_aliases (
    alias_id         INTEGER PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    alias            TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    alias_type       TEXT NOT NULL CHECK (alias_type IN ('ticker','legal_name','short_name','former_name',
                                                         'abbreviation','brand','misspelling')),
    language         TEXT NOT NULL DEFAULT 'en',
    confidence       TEXT NOT NULL CHECK (confidence IN ('verified','derived','candidate')),
    valid_from       TEXT,
    valid_to         TEXT,
    source_item_id   INTEGER REFERENCES source_items(source_item_id),
    evidence         TEXT,
    UNIQUE (company_id, alias_normalized, alias_type)
);
CREATE INDEX ix_aliases_normalized ON company_aliases(alias_normalized);

CREATE TABLE company_classifications (
    classification_id INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    sector_id         TEXT NOT NULL REFERENCES sectors(sector_id),
    valid_from        TEXT,
    valid_to          TEXT,
    verified_at_utc   TEXT NOT NULL,
    source_item_id    INTEGER REFERENCES source_items(source_item_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
    UNIQUE (company_id, sector_id, valid_from)
);
CREATE UNIQUE INDEX ux_classification_current ON company_classifications(company_id) WHERE valid_to IS NULL;

CREATE TABLE company_status_history (
    status_event_id    INTEGER PRIMARY KEY,
    company_id         TEXT NOT NULL REFERENCES companies(company_id),
    status             TEXT NOT NULL CHECK (status IN ('listed','delisted','suspended','merged_into',
                                                       'renamed','ticker_changed')),
    effective_date     TEXT,
    date_precision     TEXT NOT NULL CHECK (date_precision IN ('exact','observed','month','year','unknown')),
    related_company_id TEXT REFERENCES companies(company_id),
    details            TEXT,
    source_item_id     INTEGER REFERENCES source_items(source_item_id),
    recorded_at_utc    TEXT NOT NULL
);
CREATE TRIGGER trg_status_history_no_update BEFORE UPDATE ON company_status_history
BEGIN SELECT RAISE(ABORT, 'company_status_history is append-only'); END;
CREATE TRIGGER trg_status_history_no_delete BEFORE DELETE ON company_status_history
BEGIN SELECT RAISE(ABORT, 'company_status_history is append-only'); END;

CREATE TABLE company_segments (
    segment_id        INTEGER PRIMARY KEY,
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    segment_name      TEXT NOT NULL,
    segment_type      TEXT NOT NULL CHECK (segment_type IN ('business','product','geography')),
    revenue_share_pct REAL CHECK (revenue_share_pct IS NULL OR revenue_share_pct BETWEEN 0 AND 100),
    period            TEXT,
    source_item_id    INTEGER NOT NULL REFERENCES source_items(source_item_id),
    evidence_excerpt  TEXT NOT NULL,
    last_verified_utc TEXT NOT NULL
);

CREATE TABLE index_memberships (
    membership_id   INTEGER PRIMARY KEY,
    index_code      TEXT NOT NULL,
    company_id      TEXT NOT NULL REFERENCES companies(company_id),
    observed_at_utc TEXT NOT NULL,
    source_item_id  INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (index_code, company_id, observed_at_utc)
);
