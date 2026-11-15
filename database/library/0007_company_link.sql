CREATE TABLE IF NOT EXISTS company_link (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver TEXT NOT NULL,
    affected TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('up','down','mixed','unclear')),
    fact_id INTEGER NOT NULL,
    quote TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (fact_id, driver, affected, quote)
);
