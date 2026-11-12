-- psx-library: fetch state for the autonomous good-citizen fetcher. PROPOSED. Not applied to any database until the
-- owner approves the migration. Append-only style: rows are upserted by key, never deleted.
CREATE TABLE IF NOT EXISTS fetch_control (
    key TEXT PRIMARY KEY,              -- 'fetch_mode' | 'kill_switch' | 'breaker_tripped' | 'cooldown_until_utc'
                                       -- | 'global_last_request_utc' | 'daily_day_pkt' | 'daily_count'
    value TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_progress (
    resource_key TEXT PRIMARY KEY,     -- e.g. 'HUBC:profile'
    status TEXT NOT NULL,              -- pending | done | skipped
    etag TEXT,
    last_modified TEXT,
    last_result TEXT,                  -- ok | not_modified | blocked | error
    updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    event TEXT NOT NULL,               -- tick_noop | request | not_modified | breaker_tripped | eod_report
    detail TEXT NOT NULL
);
