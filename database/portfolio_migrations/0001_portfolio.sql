-- Portfolio database (master plan M8): a SEPARATE database from the research database, with its own
-- PSXNI_PORTFOLIO_* credentials. Every row is scoped by owner_id. There are no order or execution tables:
-- this records the owner's own transactions and theses only.

CREATE TABLE portfolios (
    portfolio_id     INTEGER PRIMARY KEY,
    owner_id         TEXT NOT NULL,
    name             TEXT NOT NULL,
    base_currency    TEXT NOT NULL DEFAULT 'PKR',
    created_at_utc   TEXT NOT NULL,
    UNIQUE (owner_id, name)
);

CREATE TABLE transactions (
    txn_id           INTEGER PRIMARY KEY,
    portfolio_id     INTEGER NOT NULL REFERENCES portfolios(portfolio_id),
    owner_id         TEXT NOT NULL,
    ticker           TEXT NOT NULL CHECK (ticker GLOB '[A-Z0-9]*'),
    trade_date       TEXT NOT NULL CHECK (trade_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    side             TEXT NOT NULL CHECK (side IN ('buy','sell','bonus_in','rights_in','dividend')),
    quantity         REAL NOT NULL CHECK (quantity >= 0),
    price            REAL CHECK (price IS NULL OR price >= 0),
    fees             REAL NOT NULL DEFAULT 0 CHECK (fees >= 0),
    note             TEXT,
    recorded_at_utc  TEXT NOT NULL,
    CHECK (side IN ('bonus_in','dividend') OR price IS NOT NULL)
);
CREATE INDEX ix_txn_owner ON transactions(owner_id, portfolio_id, ticker, trade_date);
CREATE TRIGGER trg_txn_no_update BEFORE UPDATE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are append-only: record a correcting entry'); END;

CREATE TABLE theses (
    thesis_id        INTEGER PRIMARY KEY,
    owner_id         TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    title            TEXT NOT NULL,
    statement        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
    created_at_utc   TEXT NOT NULL
);

CREATE TABLE thesis_conditions (
    condition_id     INTEGER PRIMARY KEY,
    thesis_id        INTEGER NOT NULL REFERENCES theses(thesis_id),
    owner_id         TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('ratio','dimension_state','liquidity_state','no_adverse_event')),
    subject          TEXT NOT NULL,          -- ratio name, dimension letter, or 'liquidity' / 'events'
    operator         TEXT CHECK (operator IS NULL OR operator IN ('>=','<=','==','!=')),
    threshold        TEXT,                   -- set by the owner; never defaulted
    description      TEXT NOT NULL
);

CREATE TABLE alert_rules (
    rule_id          INTEGER PRIMARY KEY,
    owner_id         TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('new_event','thesis_condition','liquidity_change')),
    ticker           TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at_utc   TEXT NOT NULL
);

CREATE TABLE alert_events (
    alert_id         INTEGER PRIMARY KEY,
    rule_id          INTEGER NOT NULL REFERENCES alert_rules(rule_id),
    owner_id         TEXT NOT NULL,
    dedupe_key       TEXT NOT NULL,
    message          TEXT NOT NULL,
    evidence_json    TEXT NOT NULL CHECK (json_valid(evidence_json)),
    created_at_utc   TEXT NOT NULL,
    UNIQUE (rule_id, dedupe_key)
);
