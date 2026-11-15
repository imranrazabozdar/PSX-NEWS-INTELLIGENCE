-- A video's publication time as an INTERVAL, with how it was derived. The archive has no dates, so this is a
-- bound and never a pretended date. date_from is NULL when nothing older constrains it. basis is one of
-- title_exact_day, title_budget, title_year, order_bounded, verified. When a real date arrives, set date_from =
-- date_to = that date and basis = 'verified'; no fact row needs rewriting.
CREATE TABLE IF NOT EXISTS video_dating (
  video_id TEXT PRIMARY KEY,
  date_from TEXT,
  date_to TEXT NOT NULL,
  basis TEXT NOT NULL,
  note TEXT NOT NULL
);
