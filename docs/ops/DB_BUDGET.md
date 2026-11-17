# Database read and write economy (psx-library)

Every process has a budget (`PSXNI_DB_MAX_ROWS_READ` 50,000, `PSXNI_DB_MAX_ROWS_WRITTEN` 5,000, requests 2,000). The
table grows every day, so nothing may cost more as it grows. Rules, and what enforces them:

| Rule | How |
|---|---|
| Read `research_fact` only through `company` | `idx_research_fact_company_date (company, source_date)`; `research_facts.facts_for` is the one reader |
| Frequent loads read a date window, not an entity's whole history | `facts_for(..., since=)`; `absorb_sector_capsule --since-days N` (news: 14, signals: 30) |
| Never `DISTINCT`/`LIKE` over the table for a short list | `sector_names` is a loose index scan: about 25 reads for 24 sectors |
| Ask about candidates, not about everything stored | `news_collector.Store.known_among`: primary-key lookups for the URLs about to be fetched |
| Write only what changed | the rollup writes only new or changed days (`changed_rows`); the loader skips exact and near repeats |
| Read recent headlines by index | `idx_news_item_published (published_at)`, created by the collector's `ensure_tables` |
| One-off heavy jobs raise their own cap, in that process only | `apply_library_indexes` (env override); `validate_entities` (owner-run report) |

Measured on 17 Nov 2026 (research_fact 46,376 rows): an automatic news run reads about 6,100 rows (it was about
25,000) and writes only new or changed rows; the rollup wrote 12 of 120 rows. Building the new index cost one
46,000-row read and write, once. Inserting a fact still costs about three row writes (the table and its indexes);
bulk loads therefore run in passes of about 1,800 rows.

Still full-table by design (owner-run, rare): `scripts/validate_entities.py`, `scripts/check_research_rows.py`.
