# ADR-0005: Source collection engine and source governance

* **Status:** Accepted for Phase 2 (pending owner review of PR)
* **Date:** 2026-11-07
* **Spec reference:** sections 2, 2.2, 3.1, 4, 11.1, 16, 17, 18; Phase 2 instruction (owner)

## Decision

1. **One reusable pipeline** (`collectors/engine.py`):
   registry → policy checks → conditional fetch → parse → canonicalise → hash → dedupe/version →
   persist with provenance → run audit → source health. Adapters are configuration (`adapter`,
   `feed_url`, `retention_mode` in the registry), not one-off scripts. Implemented adapters:
   `rss`, `atom`, `json_api`, plus a document-metadata collector for official PDFs and a generic
   HTML-table extractor for permitted listing pages.
2. **Standard library only.** HTTP (`urllib`), XML (`xml.etree`, with DOCTYPE/ENTITY refused
   before parsing), HTML (`html.parser`) and JSON. No new dependencies, so the independence
   and dependency guards are unchanged.
3. **Governance is enforced in code and in the database, not only in docs:**
   * Real collection runs only for `lifecycle_status = 'ACTIVE'`. A database trigger refuses
     ACTIVE unless `terms_status = 'approved'`, `access_status = 'verified_permitted'` and
     `enabled = 1`. Activation happens only through a reviewed change to the registry seed.
   * Every other source can only be dry-run (fetch + parse, no writes).
   * robots.txt is obeyed; a robots.txt that refuses us (401/403) is treated as "disallow all".
   * Per-host rate limit, retries with exponential backoff, capped `Retry-After`, a response
     size cap and timeouts.
   * Retention: `metadata_only` by default (title, links, timestamps, hash). Short excerpts
     only where terms are approved. Document bodies are never stored.
   * `PSXNI_KILL_SWITCH` and the per-run Turso budgets stop runs.
4. **Provenance and history** (migration 0006, additive only):
   * New `source_items` columns: original URL, retrieval method, collection run, HTTP status,
     document type, publication-time status (`known` / `date_only` / `unavailable`) and source
     metadata. These are immutable once set.
   * Changed content is appended to `source_item_versions` (now with title and run ID).
     Identical content at a new URL is linked through `duplicate_of_item_id`.
   * A missing publication time is stored as `unavailable`. It is never replaced by the
     retrieval time.
5. **Operations:**
   * `collector_runs` holds counts, duration, HTTP requests and errors for every run.
   * `collector_checkpoints` stores ETag/Last-Modified for incremental fetches.
   * The `source_health` view gives success and failure rates, consecutive failures, freshness
     and last error.
   * A failed run increments failure counters, so a broken source never appears healthy.
6. **Scheduling:** one GitHub Actions workflow (`scheduled-jobs.yml`, every 6 hours) runs
   `collectors.run --due`. That selects ACTIVE sources whose own `collection_frequency_minutes`
   has elapsed. A single workflow with per-source frequency uses fewer Actions minutes and
   Turso requests than one workflow per source family; separate workflows can be split out later
   if families need different schedules.

## Consequences
* With no ACTIVE source, the scheduled job collects nothing. That is intended until the owner
  approves each source's terms.
* Production Turso is migrated only after the PR is merged. The integration test verifies the
  unmerged migration on Turso inside a rolled-back batch.
