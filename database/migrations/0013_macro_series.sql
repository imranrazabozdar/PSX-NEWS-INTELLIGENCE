-- 0013: macro / commodity series with vintages (master plan M6). Additive only.
-- A revised official figure is a new observation (same reference period, later vintage), never an
-- overwrite. Point-in-time queries use release_date so no later revision leaks into an earlier view.

CREATE TABLE macro_series (
    series_code      TEXT PRIMARY KEY CHECK (series_code GLOB '[a-z0-9_]*'),
    name             TEXT NOT NULL,
    unit             TEXT NOT NULL,
    frequency        TEXT NOT NULL CHECK (frequency IN ('daily','weekly','monthly','quarterly','annual','irregular')),
    source_id        TEXT NOT NULL REFERENCES sources(source_id),
    mechanisms       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(mechanisms)),   -- T1..T9 it feeds
    definition       TEXT NOT NULL,
    access_state     TEXT NOT NULL CHECK (access_state IN ('manual_import','blocked','automated')),
    created_at_utc   TEXT NOT NULL
);

CREATE TABLE macro_observations (
    obs_id           INTEGER PRIMARY KEY,
    series_code      TEXT NOT NULL REFERENCES macro_series(series_code),
    reference_period TEXT NOT NULL,          -- YYYY-MM-DD (daily/weekly), YYYY-MM (monthly), YYYY-Qn, YYYY
    value            REAL NOT NULL,
    release_date     TEXT NOT NULL CHECK (release_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    vintage          INTEGER NOT NULL CHECK (vintage >= 1),
    source_item_id   INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc  TEXT NOT NULL,
    UNIQUE (series_code, reference_period, vintage)
);
CREATE INDEX ix_macro_obs ON macro_observations(series_code, reference_period);
CREATE TRIGGER trg_macro_obs_immutable BEFORE UPDATE ON macro_observations
BEGIN SELECT RAISE(ABORT, 'macro observations are immutable: record a new vintage'); END;
CREATE TRIGGER trg_macro_obs_no_delete BEFORE DELETE ON macro_observations
BEGIN SELECT RAISE(ABORT, 'macro observations are append-only'); END;
