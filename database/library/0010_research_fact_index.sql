-- Lets a loader or a pack read only the entities it needs instead of the whole research_fact table.
-- Additive: no data changes. Undo with: DROP INDEX idx_research_fact_company;
CREATE INDEX IF NOT EXISTS idx_research_fact_company ON research_fact (company, topic);
