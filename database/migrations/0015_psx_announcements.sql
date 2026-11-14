-- 0015: PSX announcement feed rows (metadata only; no binaries). Additive only.
-- Dedup key: (symbol, date, time, title). time may be NULL, so the unique index coalesces it.

CREATE TABLE psx_announcements (
    announcement_id INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,
    company_name    TEXT,
    date            TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    time            TEXT CHECK (time IS NULL OR time GLOB '[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    category        TEXT,
    title           TEXT NOT NULL,
    doc_id          INTEGER CHECK (doc_id IS NULL OR doc_id >= 1),
    track           TEXT NOT NULL CHECK (track IN ('flash','heavy')),
    source          TEXT NOT NULL CHECK (source IN ('open_mirror','corporate_ir','exchange_edge','unresolved')),
    target_url      TEXT,
    ingested_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ux_psx_announcements_key
    ON psx_announcements(symbol, date, COALESCE(time, ''), title);
