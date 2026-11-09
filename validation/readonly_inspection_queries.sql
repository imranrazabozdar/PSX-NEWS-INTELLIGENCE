-- READ-ONLY inspection queries for the SCS validation milestone. Every statement is a SELECT.
-- Cost rule: no statement scans all of market_bars. Each series uses the primary-key index with a bounded
-- predicate (source_id, symbol, timeframe) and either MIN/MAX on bar_start_utc or a bounded window count.
-- The market_coverage view is NOT used: it groups over every bar.

-- Q1 series boundaries (indexed MIN/MAX per series; 5 symbols x 4 timeframes = 20 series)
SELECT MIN(bar_start_utc) AS first_bar, MAX(bar_start_utc) AS last_bar
FROM market_bars WHERE source_id = 'scs_chart' AND symbol = :symbol AND timeframe = :timeframe;

-- Q2 per-series daily session list, bounded to a recent window (daily only; ~5 years is 1,300 rows)
SELECT session_date_pkt, bar_start_utc, open, high, low, close, volume, retrieved_at_utc
FROM market_bars WHERE source_id = 'scs_chart' AND symbol = :symbol AND timeframe = '1d'
  AND bar_start_utc >= :since_utc ORDER BY bar_start_utc;

-- Q3 intraday sample for one recent session (bounded by a date range, never the whole table)
SELECT bar_start_utc, open, high, low, close, volume FROM market_bars
WHERE source_id = 'scs_chart' AND symbol = :symbol AND timeframe = :timeframe
  AND bar_start_utc >= :start_utc AND bar_start_utc < :end_utc ORDER BY bar_start_utc;

-- Q4 corporate-action records for the five symbols' companies (small table)
SELECT ca.company_id, ca.action_type, ca.ex_date, ca.ratio, ca.amount_per_share, ca.status
FROM corporate_actions ca JOIN company_identifiers ci ON ci.company_id = ca.company_id
WHERE ci.id_type = 'psx_ticker' AND ci.value IN (:s1, :s2, :s3, :s4, :s5) AND ci.valid_to IS NULL;

-- Q5 market-data collection runs (small table; newest first, bounded)
SELECT run_id, job, started_at_utc, finished_at_utc, status, items_fetched, items_accepted, errors
FROM collector_runs WHERE source_id = 'scs_chart' ORDER BY run_id DESC LIMIT 50;

-- Q6 correction history per symbol (bounded by the bar key; reports revisions, never edits them)
SELECT COUNT(*) AS corrections FROM market_bar_corrections
WHERE source_id = 'scs_chart' AND symbol = :symbol;

-- Q7 schema check: the indexes the queries above depend on
SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('market_bars', 'corporate_actions');
