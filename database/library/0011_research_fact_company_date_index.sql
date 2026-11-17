-- Replaces idx_research_fact_company (company, topic) with (company, source_date): every read goes through
-- `company`, and a loader that only needs recent rows adds a source_date range. One index, so each insert
-- still costs the same number of row writes. Undo: recreate (company, topic) and drop this one.
CREATE INDEX IF NOT EXISTS idx_research_fact_company_date ON research_fact (company, source_date);
DROP INDEX IF EXISTS idx_research_fact_company;
