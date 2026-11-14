-- 0016: parsed PUCAR financial results and the reconciliation status of each announcement. Additive only.
-- Idempotency key: (symbol, period_ended, period_type). NULLs are coalesced so they still deduplicate.

CREATE TABLE psx_financial_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol                  TEXT NOT NULL,
    period_ended            TEXT CHECK (period_ended IS NULL OR period_ended GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    period_type             TEXT CHECK (period_type IS NULL OR period_type IN ('quarterly','half_yearly','nine_months','annual')),
    currency                TEXT DEFAULT 'PKR' CHECK (currency IS NULL OR currency IN ('PKR','USD')),
    turnover_pkr            REAL,
    cost_of_sales_pkr       REAL,
    gross_profit_pkr        REAL,
    operating_profit_pkr    REAL,
    profit_before_tax_pkr   REAL,
    profit_after_tax_pkr    REAL,
    eps                     REAL,
    dividend_pkr            REAL,
    scale                   INTEGER DEFAULT 1 CHECK (scale IN (1, 1000, 1000000)),
    warnings                TEXT CHECK (warnings IS NULL OR json_valid(warnings)),
    created_at              TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ux_psx_financial_results_key
    ON psx_financial_results(symbol, COALESCE(period_ended, ''), COALESCE(period_type, ''));

CREATE TABLE psx_reconciliation_status (
    announcement_id INTEGER PRIMARY KEY REFERENCES psx_announcements(announcement_id),
    status          TEXT NOT NULL CHECK (status IN ('reconciled', 'no_figures')),
    result_id       INTEGER REFERENCES psx_financial_results(id),
    warnings        TEXT CHECK (warnings IS NULL OR json_valid(warnings)),
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
