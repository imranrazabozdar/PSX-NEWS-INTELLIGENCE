-- Our OWN record of free-tier LLM calls, used only to decide whether to try an account again.
-- This is not a vendor ledger: it is what we have attempted, so an account can be skipped before a
-- call is made rather than after it fails. Pruned to the last 2 days; nothing older is kept.
CREATE TABLE IF NOT EXISTS llm_quota_call (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor TEXT NOT NULL,
  account INTEGER NOT NULL,
  called_at_utc TEXT NOT NULL
);
