-- 0003: financial / sector / commodity metrics, funds, research views, analyses, alerts and
-- outcomes. Tables only: they are filled in later phases (5, 8-10, 12, 14).

CREATE TABLE financial_metrics (
    metric_id      INTEGER PRIMARY KEY,
    company_id     TEXT NOT NULL REFERENCES companies(company_id),
    period_end     TEXT NOT NULL,
    period_type    TEXT NOT NULL CHECK (period_type IN ('Q1','Q2','Q3','Q4','H1','H2','9M','FY','TTM')),
    metric         TEXT NOT NULL,
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    currency       TEXT,
    basis          TEXT NOT NULL CHECK (basis IN ('reported','restated','calculated','estimated')),
    calculation_method TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL,
    UNIQUE (company_id, period_end, period_type, metric, basis, source_item_id)
);
CREATE INDEX ix_fin_metrics_company ON financial_metrics(company_id, period_end);

CREATE TABLE sector_metrics (
    metric_id      INTEGER PRIMARY KEY,
    sector_id      TEXT REFERENCES sectors(sector_id),
    company_id     TEXT REFERENCES companies(company_id),
    metric         TEXT NOT NULL,
    period         TEXT NOT NULL,
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    geography      TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL,
    CHECK (sector_id IS NOT NULL OR company_id IS NOT NULL)
);

CREATE TABLE commodity_prices (
    price_id       INTEGER PRIMARY KEY,
    commodity      TEXT NOT NULL,
    grade_contract TEXT NOT NULL,
    location       TEXT,
    observation_date TEXT NOT NULL,
    published_at_utc TEXT,
    price          REAL NOT NULL,
    currency       TEXT NOT NULL,
    unit           TEXT NOT NULL,
    price_type     TEXT NOT NULL CHECK (price_type IN ('spot','futures','administered','assessed','contract')),
    methodology    TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (commodity, grade_contract, location, observation_date, price_type, source_item_id)
);
CREATE INDEX ix_commodity_date ON commodity_prices(commodity, observation_date);

CREATE TABLE funds (
    fund_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    amc            TEXT NOT NULL,
    category       TEXT,
    benchmark      TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE fund_holdings (
    holding_id     INTEGER PRIMARY KEY,
    fund_id        TEXT NOT NULL REFERENCES funds(fund_id),
    company_id     TEXT REFERENCES companies(company_id),
    report_date    TEXT NOT NULL,
    shares         REAL,
    weight_pct     REAL CHECK (weight_pct IS NULL OR weight_pct BETWEEN 0 AND 100),
    reported_value REAL,
    currency       TEXT,
    sector_allocation_pct REAL,
    aum            REAL,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    UNIQUE (fund_id, company_id, report_date, source_item_id)
);

CREATE TABLE research_views (
    view_id        INTEGER PRIMARY KEY,
    author_source_id TEXT NOT NULL REFERENCES sources(source_id),
    company_id     TEXT REFERENCES companies(company_id),
    view_date      TEXT NOT NULL,
    direction      TEXT CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    recommendation TEXT,
    target_price   REAL,
    currency       TEXT,
    horizon        TEXT,
    valuation_method TEXT,
    assumptions    TEXT,
    source_item_id INTEGER NOT NULL REFERENCES source_items(source_item_id),
    recorded_at_utc TEXT NOT NULL
);

CREATE TABLE analyses (
    analysis_id    INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES events(event_id),
    company_id     TEXT NOT NULL REFERENCES companies(company_id),
    analysis_version INTEGER NOT NULL CHECK (analysis_version >= 1),
    label          TEXT NOT NULL CHECK (label IN ('quantitative','qualitative')),
    transmission   TEXT,
    financial_impact_json TEXT CHECK (financial_impact_json IS NULL OR json_valid(financial_impact_json)),
    missing_inputs_json   TEXT CHECK (missing_inputs_json IS NULL OR json_valid(missing_inputs_json)),
    confidence     REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    risk           TEXT,
    model_version  TEXT,
    prompt_version TEXT,
    calculation_version TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE (event_id, company_id, analysis_version)
);
CREATE TRIGGER trg_analyses_no_update BEFORE UPDATE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are versioned; insert a new analysis_version'); END;

CREATE TABLE alerts_predictions (
    alert_id       INTEGER PRIMARY KEY,
    company_id     TEXT REFERENCES companies(company_id),
    event_id       INTEGER REFERENCES events(event_id),
    created_at_utc TEXT NOT NULL,
    reference_price REAL,
    reference_price_at_utc TEXT,
    direction      TEXT NOT NULL CHECK (direction IN ('positive','negative','mixed','neutral','unknown')),
    horizon_sessions INTEGER CHECK (horizon_sessions IS NULL OR horizon_sessions > 0),
    confidence     REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    thesis         TEXT NOT NULL,
    invalidation   TEXT,
    snapshot_json  TEXT NOT NULL CHECK (json_valid(snapshot_json)),
    CHECK (company_id IS NOT NULL OR event_id IS NOT NULL)
);
-- Point-in-time snapshot: frozen at alert time.
CREATE TRIGGER trg_alerts_no_update BEFORE UPDATE ON alerts_predictions
BEGIN SELECT RAISE(ABORT, 'alerts_predictions are frozen point-in-time records'); END;
CREATE TRIGGER trg_alerts_no_delete BEFORE DELETE ON alerts_predictions
BEGIN SELECT RAISE(ABORT, 'alerts_predictions are frozen point-in-time records'); END;

CREATE TABLE market_outcomes (
    outcome_id     INTEGER PRIMARY KEY,
    alert_id       INTEGER NOT NULL REFERENCES alerts_predictions(alert_id),
    evaluation_date TEXT NOT NULL,
    sessions_after INTEGER NOT NULL CHECK (sessions_after > 0),
    stock_return   REAL,
    benchmark_return REAL,
    sector_return  REAL,
    dividend_adjusted_return REAL,
    costs          REAL,
    outcome        TEXT CHECK (outcome IN ('hit','miss','partial','invalidated','not_evaluable')),
    computed_at_utc TEXT NOT NULL,
    UNIQUE (alert_id, sessions_after)
);
