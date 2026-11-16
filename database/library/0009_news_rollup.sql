-- One row per day per entity (company ticker, SECTOR:<X>, MACRO:PAKISTAN): how much news there was and what it
-- was about. Built by engines/news_rollup.py from news_item with no model; small and cheap to keep for years.
CREATE TABLE IF NOT EXISTS news_rollup (
  day TEXT NOT NULL,
  entity TEXT NOT NULL,
  stories INTEGER NOT NULL,
  topics TEXT NOT NULL,
  top_title TEXT,
  top_url TEXT,
  updated_utc TEXT NOT NULL,
  PRIMARY KEY (day, entity)
);
