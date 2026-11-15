-- Where a video-derived fact came from, and HOW RECENT it is relative to the other videos.
-- The archive carries no publication dates, but it is in reverse-chronological order, so
-- archive_position (0 = newest) is the recency key: when two videos disagree about the same company,
-- the lower position is the later view and the higher is history. It is a RANK, not a date.
-- Join to research_fact through its source_url, which holds the video URL.
CREATE TABLE IF NOT EXISTS video_source (
  video_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  channel TEXT NOT NULL,
  archive_position INTEGER NOT NULL CHECK (archive_position >= 0),
  sector_bucket TEXT,
  url TEXT NOT NULL,
  speaker_may_differ INTEGER NOT NULL CHECK (speaker_may_differ IN (0, 1)),
  status TEXT NOT NULL
);
