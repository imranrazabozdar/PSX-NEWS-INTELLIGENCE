-- 0010: PSX market OHLCV bars (1m / 1h / 4h / 1d) with provenance and correction history.
-- Additive only. Bars are append-only: the first observation of a bar is never overwritten. A later
-- fetch that returns different values for the same bar is stored as a correction, and
-- market_bars_current exposes the latest values. Each row records its source and retrieval time. Run
-- audit uses the existing collector_runs table, and the provider is a row in the existing sources table.

CREATE TABLE market_bars (
    source_id         TEXT NOT NULL REFERENCES sources(source_id),
    symbol            TEXT NOT NULL CHECK (symbol GLOB '[A-Z0-9]*' AND length(symbol) BETWEEN 1 AND 16
                                           AND symbol NOT GLOB '*[^A-Z0-9]*'),
    timeframe         TEXT NOT NULL CHECK (timeframe IN ('1m','1h','4h','1d')),
    bar_start_utc     TEXT NOT NULL CHECK (bar_start_utc GLOB
                          '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:00Z'),
    session_date_pkt  TEXT NOT NULL CHECK (session_date_pkt GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    open              REAL NOT NULL,
    high              REAL NOT NULL,
    low               REAL NOT NULL,
    close             REAL NOT NULL,
    volume            REAL NOT NULL CHECK (volume >= 0),
    retrieved_at_utc  TEXT NOT NULL,
    collection_run_id INTEGER REFERENCES collector_runs(run_id),
    CHECK (low > 0 AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
    CHECK (timeframe <> '1d' OR substr(bar_start_utc, 12) = '00:00:00Z'),
    CHECK (timeframe NOT IN ('1h','4h') OR substr(bar_start_utc, 15) = '00:00Z'),
    PRIMARY KEY (source_id, symbol, timeframe, bar_start_utc)
);
CREATE INDEX ix_market_bars_symbol ON market_bars(symbol, timeframe, bar_start_utc);

CREATE TABLE market_bar_corrections (
    correction_id     INTEGER PRIMARY KEY,
    source_id         TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    bar_start_utc     TEXT NOT NULL,
    open              REAL NOT NULL,
    high              REAL NOT NULL,
    low               REAL NOT NULL,
    close             REAL NOT NULL,
    volume            REAL NOT NULL CHECK (volume >= 0),
    retrieved_at_utc  TEXT NOT NULL,
    collection_run_id INTEGER REFERENCES collector_runs(run_id),
    CHECK (low > 0 AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close),
    FOREIGN KEY (source_id, symbol, timeframe, bar_start_utc)
        REFERENCES market_bars(source_id, symbol, timeframe, bar_start_utc)
);
CREATE INDEX ix_market_bar_corrections_bar ON market_bar_corrections(source_id, symbol, timeframe, bar_start_utc);

-- append-only: no UPDATE or DELETE, and no REPLACE onto an existing key (REPLACE deletes without firing
-- delete triggers, so the key is checked before conflict resolution)
CREATE TRIGGER trg_market_bars_no_update BEFORE UPDATE ON market_bars
BEGIN SELECT RAISE(ABORT, 'market_bars are append-only; record a correction instead'); END;
CREATE TRIGGER trg_market_bars_no_delete BEFORE DELETE ON market_bars
BEGIN SELECT RAISE(ABORT, 'market_bars are append-only'); END;
CREATE TRIGGER trg_market_bars_no_replace BEFORE INSERT ON market_bars
WHEN EXISTS (SELECT 1 FROM market_bars b WHERE b.source_id = NEW.source_id AND b.symbol = NEW.symbol
             AND b.timeframe = NEW.timeframe AND b.bar_start_utc = NEW.bar_start_utc)
BEGIN SELECT RAISE(ABORT, 'market_bars: duplicate key; existing bars cannot be replaced'); END;
CREATE TRIGGER trg_market_bar_corrections_no_update BEFORE UPDATE ON market_bar_corrections
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections are append-only'); END;
CREATE TRIGGER trg_market_bar_corrections_no_delete BEFORE DELETE ON market_bar_corrections
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections are append-only'); END;
CREATE TRIGGER trg_market_bar_corrections_no_replace BEFORE INSERT ON market_bar_corrections
WHEN EXISTS (SELECT 1 FROM market_bar_corrections c WHERE c.correction_id = NEW.correction_id)
BEGIN SELECT RAISE(ABORT, 'market_bar_corrections: duplicate key; existing corrections cannot be replaced'); END;

-- latest values per bar (the newest correction wins; otherwise the first observation)
CREATE VIEW market_bars_current AS
SELECT b.source_id, b.symbol, b.timeframe, b.bar_start_utc, b.session_date_pkt,
       COALESCE(c.open, b.open) AS open, COALESCE(c.high, b.high) AS high,
       COALESCE(c.low, b.low) AS low, COALESCE(c.close, b.close) AS close,
       COALESCE(c.volume, b.volume) AS volume,
       b.retrieved_at_utc AS first_retrieved_at_utc,
       COALESCE(c.retrieved_at_utc, b.retrieved_at_utc) AS last_retrieved_at_utc,
       (SELECT COUNT(*) FROM market_bar_corrections x WHERE x.source_id = b.source_id AND x.symbol = b.symbol
          AND x.timeframe = b.timeframe AND x.bar_start_utc = b.bar_start_utc) AS correction_count
FROM market_bars b
LEFT JOIN market_bar_corrections c ON c.correction_id = (
    SELECT MAX(x.correction_id) FROM market_bar_corrections x WHERE x.source_id = b.source_id
       AND x.symbol = b.symbol AND x.timeframe = b.timeframe AND x.bar_start_utc = b.bar_start_utc);

-- coverage and freshness per source, symbol and timeframe
CREATE VIEW market_coverage AS
SELECT source_id, symbol, timeframe, COUNT(*) AS bars, MIN(bar_start_utc) AS first_bar_utc,
       MAX(bar_start_utc) AS last_bar_utc, MAX(retrieved_at_utc) AS last_retrieved_at_utc,
       COUNT(DISTINCT session_date_pkt) AS sessions
FROM market_bars GROUP BY source_id, symbol, timeframe;
