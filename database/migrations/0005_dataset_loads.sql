-- 0005: record which version of each reference dataset is loaded, so an unchanged dataset
-- is skipped with a single indexed read (protects the free-tier read/write quota).

CREATE TABLE dataset_loads (
    dataset        TEXT PRIMARY KEY,
    sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
    loaded_at_utc  TEXT NOT NULL,
    record_count   INTEGER NOT NULL CHECK (record_count >= 0)
);
