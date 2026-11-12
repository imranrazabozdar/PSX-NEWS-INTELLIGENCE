-- psx-library: distilled, sourced, dated research facts. PROPOSED. NOT APPLIED until the owner approves.
-- Only CREATE TABLE IF NOT EXISTS is allowed (scripts/apply_library_migration.py refuses anything else).
-- Each row is ONE sourced, dated fact in our own words. No paragraphs, no raw PDF text.
CREATE TABLE IF NOT EXISTS research_fact (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    topic TEXT NOT NULL,
    fact_text TEXT NOT NULL CHECK (length(fact_text) BETWEEN 1 AND 300),
    value REAL,
    unit TEXT,
    period TEXT,
    source_name TEXT NOT NULL CHECK (length(trim(source_name)) > 0),
    source_url TEXT,
    source_date TEXT NOT NULL CHECK (length(trim(source_date)) > 0),
    as_of TEXT,
    confidence TEXT NOT NULL CHECK (confidence IN ('fact', 'analyst_view')),
    created_at TEXT NOT NULL
);
