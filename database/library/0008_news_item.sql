-- News headlines collected from sources whose robots.txt allows it (engines/news_collector.py).
-- Metadata only: headline, publication date, link, a short snippet. Never the article body.
CREATE TABLE IF NOT EXISTS news_item (
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  published_at TEXT NOT NULL,
  section TEXT,
  snippet TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (source, url)
);

-- Collector state per source: the stored robots.txt, the day's request count, and URLs not worth refetching.
CREATE TABLE IF NOT EXISTS news_progress (
  source TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT,
  updated_utc TEXT NOT NULL,
  PRIMARY KEY (source, key)
);

-- Lets the facts and rollup steps read only the last few days of headlines instead of the whole table.
CREATE INDEX IF NOT EXISTS idx_news_item_published ON news_item (published_at);
