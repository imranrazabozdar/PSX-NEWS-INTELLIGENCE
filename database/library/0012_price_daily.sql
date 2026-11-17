-- Compact daily price bars for the symbols the technical engine covers, read through the ADR-0008 link.
-- Only a recent window is kept (default 120 sessions); older history stays in the technical database and is read
-- on demand. Additive only. WITHOUT ROWID: one B-tree, so each row costs about one row write.
-- Undo: DROP TABLE price_daily (nothing else depends on it).
CREATE TABLE IF NOT EXISTS price_daily (
  symbol TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  source TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  PRIMARY KEY (symbol, trade_date)
) WITHOUT ROWID;
