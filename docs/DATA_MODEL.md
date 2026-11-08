# Data model (Phase 1 data foundation)

The schema is event-centred and relational (spec section 11), and it runs on this project's own
Turso database. Migrations live in `database/migrations/`. This document describes what they
create and the rules the database enforces.

## Conventions

| Topic | Rule |
|---|---|
| Time | Stored as ISO-8601 UTC text ending in `Z`. The source's original string (`*_raw`) and offset (`*_tz_offset`) are kept. A timestamp without a zone is rejected unless the source's zone is known (e.g. PSX pages use PKT, UTC+05:00). It is never guessed. |
| Unknown values | Stored as `NULL`, never filled with a guess (e.g. `valid_from` when a listing start date isn't known). |
| Identity | `company_id` (`cmp-<ticker at registration>`) is permanent. Tickers live in `company_identifiers` with validity dates, so a ticker change never rewrites identity. |
| Provenance | Every company, alias, classification, status change, index membership, segment, exposure, metric and evidence row points to a `source_items` row, which points to a `sources` registry entry. |
| History | Changes are appended, never overwritten. Triggers block UPDATE/DELETE on `source_item_versions`, `event_revisions`, `event_evidence`, `company_status_history` and `alerts_predictions`, and DELETE on `source_items` and `events`. |
| Collection safety | A source can't be `enabled` unless `access_status = 'verified_permitted'`. A media account can't be `active` unless its identity is `verified`. Both are CHECK constraints. |
| Foreign keys | Enforced on every connection (`PRAGMA foreign_keys = ON` is sent with every Turso request). |

## Tables

### Sources and provenance (migration 0001)
* **sources**: the registry of every planned source (exchange, regulators, government, news, international news, AMCs, MUFAP, brokers, X, YouTube). Stores type, domain, reliability tier, access method, access status, terms notes and enabled flag. All 38 are seeded **disabled** and **unverified**. Reuters is `licence_required`.
* **source_items**: one row per retrieved item. Holds the canonical URL or external ID, title, published (UTC + raw + offset), event date, collected time, content SHA-256, a short permitted excerpt (≤ 1,000 characters, so no long copyrighted text), access status, `duplicate_of_item_id` and relevance fields. It is unique per `(source_id, canonical_url)` and per `(source_id, external_id)`. Provenance columns are immutable.
* **source_item_versions**: append-only content versions of an item. When a page changes, a new version is added, and the original row and hash stay as first recorded.

### Company master (0001)
* **sectors**: the official PSX sector list (scheme `PSX`).
* **companies**: legal name, listing status, fiscal year-end month, share class, a short source-backed business summary, and the source item of the profile page.
* **company_identifiers**: PSX tickers with `valid_from` / `valid_to` / `verified_at_utc`. A partial unique index allows only one current holder per ticker.
* **company_aliases**: ticker, legal name and derived short name, normalised for matching. Each has a confidence of `verified`, `derived` or `candidate`, plus evidence.
* **company_classifications**: sector assignment over time (one current per company).
* **company_status_history**: append-only listing events (delisted, merged_into, renamed, ticker_changed), with date precision and the related company.
* **company_segments**: business, product or geographic segments. These need a source item and an evidence excerpt (filled in Phase 4).
* **index_memberships**: observed index membership snapshots (KSE-30), with observation time and source.

### Events and evidence (0002)
* **events**: the current state of an event. Includes type, headline, summary, date and date precision, geography, **lifecycle stage** (rumour → discussion → proposal → consultation → committee recommendation → approval → notification → implementation, plus amendment / delay / suspension / reversal, spec section 8), verification state, direction, magnitude, novelty, horizon and confidence.
* **event_revisions**: a full snapshot of every version, with the reason, author and model/prompt version. An event row can only be updated to a revision number that has already been recorded (trigger). Events can't be deleted.
* **event_evidence**: one row per **claim**. It links the event to a source item with the excerpt, claim type (fact, official statement, report, interpretation, opinion, prediction, rumour, advertisement, model inference), relation (supports / contradicts / context), verification state and an independence flag. Append-only.
* **event_companies**: event-to-company links, with exposure type (direct / indirect / uncertain / **excluded**, with the rationale), impact direction, channel and reviewer status.
* **company_exposures**: evidence-backed exposures (input, product, market, FX, debt, regulation, logistics, energy …). These need a source item and an excerpt.

### Metrics, research and outcomes (0003); filled from Phase 5 onwards
`financial_metrics`, `sector_metrics`, `commodity_prices` (grade, location, currency, unit, price type), `funds`, `fund_holdings`, `research_views`, `analyses` (versioned, never updated), `alerts_predictions` (a frozen point-in-time snapshot) and `market_outcomes`.

### Media, operations and watchlist (0004)
`media_accounts` (the exact supplied handles, all `disabled`; Donald Trump and Reuters are `pending_handle` with no guessed URL), `media_items` (with `transcript_status`), `media_mentions`, `media_event_links` (independent / repost / syndicated), `media_predictions`, `media_metrics_history`, `collector_runs` and `user_watchlist`.

### schema_migrations
Records each migration's version, name, SHA-256 checksum and applied time.

## Deduplication foundations
* `canonical_url()` lowercases the scheme and host, drops default ports, fragments and tracking parameters (`utm_*`, `fbclid`, `gclid` …), sorts the query string and trims a trailing slash.
* `content_sha256()` hashes Unicode-normalised, whitespace-collapsed text, so whitespace-only changes don't create a new version.
* `record_source_item()` returns one of four outcomes:
  * `inserted`: a new item;
  * `unchanged`: same URL or ID with the same hash, so nothing is written;
  * `new_version`: same URL or ID with new content, so a version is appended;
  * `duplicate_content`: a different URL with identical content, so the item is linked to the first copy and not counted as independent.
* `base_ticker()` strips PSX status markers (`XD`, `XB`, `XR`, `XW`). For example, PSX shows `HBLXD` while HBL is ex-dividend.

## Point-in-time
`company_by_ticker(db, ticker, as_of=...)` resolves a ticker as of a date using identifier validity. Example: FFBL resolves on 2024-06-01 but is not current. It was delisted after merging into FFC, and that history is recorded in `company_status_history` from the PSX page.

## Company universe (seed v1, 2026-11-07)
50 listed companies plus 1 delisted record (FFBL), all read from the official PSX Data Portal.
* **KSE-30 (30 companies, from dps.psx.com.pk/indices/KSE30):** ATRL, BAFL, BOP, DGKC, EFERT, ENGROH, FATIMA, FCCL, FFC, HBL, HUBC, KEL, LUCK, MARI, MCB, MEBL, MLCF, NBP, NRL, OGDC, PAEL, POL, PPL, PSO, PTC, SAZEW, SEARL, SNGP, SYS, UBL.
* **Additions (20), chosen across the sectors named in ADR-0003:**
  * banks: ABL, BAHL, AKBL, FABL
  * gas utility: SSGC
  * oil marketing: APL, SHEL
  * refineries: PRL, CNERGY
  * power: KAPCO, NPL
  * cement: CHCC, KOHC
  * steel: ISL, ASTL, MUGHAL
  * technology: TRG
  * autos / chemicals: INDU, HCAR, EPCL

Each record stores the PSX page URL, retrieval time and page SHA-256. Only the official PSX sector is recorded. PSX classifies SNGP and SSGC under "Oil & Gas Marketing Companies", and that is kept as-is. Company-specific segments and exposures need evidence and are Phase 4 work.

**Refreshing the seed:** it was compiled once by reading the public PSX pages. A repeatable, terms-reviewed PSX collector belongs to Phase 2. Until then, change the seed only through a reviewed PR that keeps the source fields.

## Commands
```bash
export PSXNI_TURSO_DATABASE_URL=libsql://<db>.turso.io   # this project's database only
export PSXNI_TURSO_AUTH_TOKEN=...                         # never commit
python -m database.migrate --dry-run      # show pending migrations
python -m database.migrate                # apply (safe to re-run)
python -m database.seed_loader --dry-run  # validate reference data only
python -m database.seed_loader            # load reference data (idempotent)
```

## Phase 2 additions (migration 0006)
* `sources`: official URL, category/subcategory, geography, industries, content format, feed URL, adapter, retention mode, terms/licensing/verification status, lifecycle status (NOT REVIEWED … ACTIVE / DISABLED), priority, frequency, review notes, plus health fields (last attempt/error, failure counts, last content time). A trigger refuses ACTIVE unless terms are approved and access is verified.
* `source_items`: original URL, retrieval method, collection run, HTTP status, document type, publication-time status, source metadata. These are immutable once set.
* `source_item_versions`: collection run and title per version.
* `collector_runs`: duplicates, new versions, failed items, HTTP requests/status, duration, not-modified.
* `collector_checkpoints`: ETag / Last-Modified / last seen item per source.
* `media_accounts`: category and access status.
* `source_health` view.

## Phase 3 and Phase 4 additions (migrations 0007, 0008)
* 0007: `llm_calls` (append-only ledger), `event_extractions` (append-only), `story_clusters`,
  `story_cluster_members`.
* 0008 tables and columns:
  * `sources.is_synthetic`.
  * `company_relationships`: append-only, with corrections superseding earlier rows; view
    `current_company_relationships`.
  * `exposure_candidates`: revisions only, no delete.
  * `exposure_candidate_evidence`: normalised foreign-key evidence links, append-only.
  * `exposure_candidate_revisions`: written by triggers.
  * `exposure_reviews`: append-only.
* Triggers verify that evidence belongs to the right event or company, that sources are approved for
  `potential` and above, that the event is corroborated for `strongly_supported`, and that a real
  acceptance review exists for `confirmed`.
* Applied to local and CI databases only. Production Turso is still at 0005.
* See `docs/EXPOSURE_MAPPING.md`.

## Phase 5 schema (migration 0009; implemented on a branch, not applied to production)
- **Tables:** company-level `impact_assessments` with append-only inputs, revisions, transmission
  steps, scenarios and reviews; immutable expiry-policy versions and lifecycle events, shipped empty.
- **Views:** `impact_invalid_inputs`, `impact_assessments_current`, `impact_event_company_eligibility`,
  `impact_unclassified_companies`, `impact_sector_aggregates_current`, `impact_expiry_policies_current`
  and `impact_expiry_policy_overlaps`.
- **Triggers:** event-refutation propagation, and delete protection for `analyses`.
- **Design:** `docs/MIGRATION_0009_DESIGN.md`. Gate 3 (disposable Turso):
  `docs/TURSO_DISPOSABLE_VERIFICATION.md`.

## Free-tier quota protection
Turso's free plan caps rows read, rows written and storage. Check the current limits on Turso's site before increasing collection.
* **Usage meter:** every Turso response reports `rows_read` / `rows_written`. `db.usage()` totals them per run, and the loader prints them.
* **Per-run budget:** a run stops with `DatabaseBudgetError` before exceeding `PSXNI_DB_MAX_ROWS_READ` (default 50,000), `PSXNI_DB_MAX_ROWS_WRITTEN` (default 5,000) or `PSXNI_DB_MAX_REQUESTS` (default 2,000).
* **Kill switch:** `PSXNI_KILL_SWITCH=true` blocks all Turso requests.
* **Unchanged data is skipped:** `dataset_loads` stores a hash of the seed files. Re-loading the same reference data costs 1 request, 1 row read and 0 writes (measured on Turso). Before this change it cost 226 requests, 1,085 reads and 38 writes.
* **No-op upserts:** an unchanged source registry entry is not rewritten.
* **Batched writes:** the seed is written as one atomic request per ~10 companies.
* **Indexed lookups:** a test checks that ticker, alias, URL, content-hash, evidence and dataset lookups use indexes, not table scans.
* **Integration tests:** they use rolled-back batches and small queries, so they leave no data and write nothing permanent.

## Backup and restore (plan)
Turso has point-in-time restore on its own platform. Check the current plan limits on Turso's site.
For an independent copy, use `turso db shell <db> .dump > backup.sql`, kept in **private** storage and never in this public repo (ADR-0003 D6 is still open). A tested restore procedure is a Phase 14 deliverable (spec section 11.1).
