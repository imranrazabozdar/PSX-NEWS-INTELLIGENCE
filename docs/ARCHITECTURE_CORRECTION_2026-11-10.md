# Architecture correction, 2026-11-10

Purpose: record what happened to the shared production database, what each repository now owns, and what is
implemented, prototyped, validated or still incomplete. Every figure below cites the record it came from. Nothing
here changes production data. Production remediation waits for separate owner approval.

## 1. What was built where
| Work | Repository | Status | Source |
|---|---|---|---|
| Investify read-only announcements pilot, manual PDF vault and ingester | technical | merged to its `main` (PR #60–#62) | technical PRs #60–#62 |
| Company-master stub loader (16 stubs), name capture (21/21 linked) | technical | merged (PR #62) | technical PR #62 |
| Fundamental engine: schema baseline, LLM routing, Groq, first production extraction run (5 headlines) | technical | merged (PR #63) | technical PR #63 |
| Relevance pre-filter, Gemini and OpenRouter, fallback cascade | technical | merged (PR #64) | technical PR #64 |
| Candidate review workflow (migration 0011, review queue), 10-item production run | technical | merged (PR #65) | technical PR #65 |
| Extraction quality: dedup, entity resolution, evaluation, gated acquisition | technical | **open, not merged** (PR #66) | technical PR #66 |
| Relevance pre-filter (ported) | news | merged (PR #55) | news PR #55 |
| LLM providers, disabled until owner enables (ported) | news | pull request #57, merge-ready, not merged | news PR #57 |
| Database ownership guard | news | branch `feature/database-ownership` | pushed 2026-11-10 |
| Quarantine of legacy extraction records | news | branch `feature/candidate-quarantine` | pushed 2026-11-10 |
| Evaluation harness (ported, synthetic) | news | branch `feature/evaluation-harness` | pushed 2026-11-10 |
| Earnings quality and audit signals | news | branch `feature/earnings-quality` | pushed 2026-11-10 |
| Segment reconciliation, notes extraction with page evidence | news | branch `feature/segments-and-notes` | pushed 2026-11-10 |
| Technical-engine refusal of the news database | technical | branch `feature/refuse-shared-news-database` | pushed 2026-11-10 |

## 2. The shared database incident
* **One production database was used by both projects.** Host `psx-news-intelligence-imranrazabozdar`. The
  specification (section 1.3) and ADR-0001 require separate databases. The technical engine's runs wrote into
  this database, and the news repository's schema and its own migrations live in it too.
* **Migration collision.** Technical migration 0011 (`extraction_reviews`, PR #65) was applied to this database.
  Version 11 then belonged to two different migrations. The news repository's migration runner refused to start.
  Resolved by the approved remediation (A2, PR #52): the foreign version and its five objects were removed after a
  verified pre-flight and backup. Migrations 0011 to 0014 of the news repository were then applied and verified.
  Source: news PR #52, and `docs/MIGRATION_COLLISION_A2.md`.
* **Production writes made by the technical repository** (as recorded in its own PRs):

| Write | Amount | Source |
|---|---|---|
| OHLCV bars from the SCS chart pilot into `market_bars` | 120 rows, `collector_runs` 38 | technical PR #60 |
| Investify announcements into `source_items` (restricted, metadata only) | 21 rows, `collector_runs` 39 | technical PR #61 |
| Investify name backfill (`source_metadata_json`) | 21 rows, `collector_runs` 40 | technical PR #62 |
| Stub companies and candidate aliases | 16 companies (51 to 67), aliases 152 to 184, `collector_runs` 41 | technical PR #62 |
| Extraction runs: `llm_calls` and `event_extractions` | 5 (first run) and 10 more (review run); read-only check on 2026-11-09 showed 15 `llm_calls`, 15 extractions | technical PRs #63, #65, #66 |
| Review, cluster and event tables | 0 rows at 2026-11-09 (read-only check) | technical PR #66 |

* **Live model output.** The 15 extraction candidates were produced by model calls (Groq, `openai/gpt-oss-20b`).
  They are **legacy, unreviewed and unverified**. None was approved or rejected by any reviewer.
* **Not known from here.** The current row counts after 2026-11-09 are not verified. The owner must confirm them
  with a read-only query before any remediation.

## 3. Controls now in place (news repository)
* Fail-closed database ownership: production refuses any host other than the owned one, and every other connection
  declares a purpose (`production`, `disposable`, `test`), with tests (branch `feature/database-ownership`).
* Quarantine: extraction records whose schema version is not one of this project's are classified as quarantined,
  reported read-only, never modified, and never selected for scoring. A regression test requires every new read of
  extraction records to be schema-scoped (branch `feature/candidate-quarantine`).
* The technical engine refuses the news database in its client and its backend module, before any connection
  (branch `feature/refuse-shared-news-database` in the technical repository).

## 4. Remaining exposure that the current controls do NOT cover
These are real risks and need the owner's decision:
1. **`market_bars` (technical OHLCV pilot rows).** The news repository reads this table for market data. The rows
   are not quarantined by the current code. Proposed: identify them by `collector_runs` 38 and exclude them at read
   time, after the owner confirms the source.
2. **Stub companies and candidate aliases (16 companies).** The news company master and entity resolution can see
   them. They have `listing_status = unknown` and no sector or ISIN, but they are not yet excluded from matching.
3. **Investify source items (21 restricted rows).** They are metadata only and restricted. They must not feed any
   scoring. The news code does not currently exclude them by source status for every path.
4. **Live extraction rows and `llm_calls`.** Quarantined only where they carry a legacy schema version. Their
   `llm_calls` rows are counted as spend and have no quarantine marker.

## 5. Database separation (required, owner action)
1. Create a new Turso database for the technical engine. Scope its token to that database only.
2. Point the technical repository's secrets (`LIBSQL_URL`, `LIBSQL_AUTH_TOKEN`) at it.
3. Decide, for the news database, whether the technical rows listed in section 2 are kept, quarantined or removed.
   Any change needs a backup with a verified SHA-256, a rehearsal on a disposable database, and an approval ID.
4. Confirm the current row counts with a read-only query, using a fresh read-only token.

No step above was performed by this change.

## 6. Exact status of modules
| Module | Status | Evidence |
|---|---|---|
| Company master (50 seeded) | implemented and tested | `database/seed/companies.json`, seed tests |
| News collection, 11 `verified_permitted` sources, metadata only | implemented and tested; scheduled workflow exists | collectors tests, `scheduled-jobs.yml` |
| Event extraction, offline | implemented and tested; live provider code is disabled | `engines/extraction.py`, `engines/llm_live.py`, tests |
| Live model extraction in the news repository | **not enabled**; requires owner's terms review and verified model | `config/llm_providers.json` |
| Relevance pre-filter | implemented, tested; not yet wired into extraction | `engines/relevance_prefilter.py` |
| Impact framework T1–T9 | implemented, tested offline; no approved company inputs | `engines/impact_intel.py`, tests |
| Financial import, reconciliation, promotion | implemented, tested | `engines/financials.py`, tests |
| Ratios, growth, FCF, dimensions A–C | implemented, tested; bands not set (owner) | `engines/fundamentals.py`, tests |
| DCF, multiples, scenario models | implemented, tested; inputs must be sourced | `engines/valuation.py`, tests |
| Earnings quality and audit signals | implemented, tested on synthetic inputs | `engines/earnings_quality.py`, tests |
| Segment reconciliation | implemented, tested on synthetic inputs | `engines/segments.py`, tests |
| Notes extraction with page evidence | implemented, tested on synthetic text; not yet run on a real report | `engines/notes_extraction.py`, tests |
| Evaluation harness (synthetic, labelled) | implemented, tested; one resolver gap found and fixed | `engines/evaluation.py`, tests |
| Real company report through the full chain | **blocked**: needs an owner-supplied annual report (see section 7) | — |
| Phases 8–14 (policy, commodities, institutional, social, opportunity radar, backtesting audit) | not started or partial | `docs/STATUS.md` |

## 7. Blockers for the end-to-end demonstration
* The demonstration needs a real annual report for one company (for example OGDC). The owner must supply the PDF
  through the existing owner-document intake, with its rights attestation. Public PSX documents are not fetched
  automatically, because source permission is `metadata_only`.
* Live extraction needs the owner's terms review for this project and a verified model id.
* Production writes need separate approval, as do migrations, activation of any module, and any change to shared data.
