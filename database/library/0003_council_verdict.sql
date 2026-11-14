-- Council verdicts: one row per deliberation. Approved shape: a small JSON record, never documents.
-- The verdict keeps its own provenance (lenses, models, prompt versions) inside verdict_json.
CREATE TABLE IF NOT EXISTS council_verdict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  created_at TEXT NOT NULL,
  lenses_answered TEXT NOT NULL,
  conflict_count INTEGER NOT NULL,
  verdict_json TEXT NOT NULL CHECK (length(verdict_json) < 65536)
);
