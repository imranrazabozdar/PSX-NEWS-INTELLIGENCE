-- 0014: validation runs (M7) and reproducible report snapshots (M9). Additive only.

CREATE TABLE validation_runs (
    run_id           INTEGER PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('labelled_accuracy','event_study','walk_forward','extraction')),
    engine_versions_json TEXT NOT NULL CHECK (json_valid(engine_versions_json)),
    label_version    TEXT,
    label_count      INTEGER NOT NULL CHECK (label_count >= 0),
    data_kind        TEXT NOT NULL CHECK (data_kind IN ('human_labelled','synthetic_test','real_market')),
    status           TEXT NOT NULL,
    metrics_json     TEXT NOT NULL CHECK (json_valid(metrics_json)),
    created_at_utc   TEXT NOT NULL
);
CREATE TRIGGER trg_validation_runs_immutable BEFORE UPDATE ON validation_runs
BEGIN SELECT RAISE(ABORT, 'validation_runs are immutable'); END;

CREATE TABLE report_snapshots (
    snapshot_id      INTEGER PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('company','sector','market')),
    subject          TEXT NOT NULL,
    as_of_date       TEXT NOT NULL,
    generated_at_utc TEXT NOT NULL,
    input_versions_json TEXT NOT NULL CHECK (json_valid(input_versions_json)),
    content_sha256   TEXT NOT NULL CHECK (length(content_sha256) = 64),
    body_json        TEXT NOT NULL CHECK (json_valid(body_json)),
    UNIQUE (kind, subject, as_of_date, content_sha256)
);
CREATE INDEX ix_report_snapshots ON report_snapshots(kind, subject, as_of_date);
CREATE TRIGGER trg_report_snapshots_immutable BEFORE UPDATE ON report_snapshots
BEGIN SELECT RAISE(ABORT, 'report snapshots are immutable'); END;
