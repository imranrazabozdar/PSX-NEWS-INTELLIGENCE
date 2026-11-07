# Phase 2 acceptance review (PR #5, `phase-2-collectors` @ 0f4651d)

Reviewed 2026-11-07 against spec §14 Phase 2, §16 collector tests, §19 News MVP and the owner's
Phase 2 instructions. This is a read-only review: PR #5 was not modified. Findings that need a
change are listed in §4 for the owner to approve before they are applied on the PR #5 branch.

**Verdict:** the engineering acceptance criteria are met and tested. Phase 2 cannot be called
operationally complete, because no source is ACTIVE: no publisher's terms have been approved. Fix
issue F1 before merge. F2–F6 can be fixed before or right after merge, as the owner prefers.

## 1. Evidence run for this review
| Check (on the PR #5 head, local) | Result |
|---|---|
| `python scripts/check_independence.py` | pass |
| `ruff check .` | pass |
| `pytest` | 123 passed, 11 skipped (Turso and opt-in live-source tests) |
| GitHub CI on PR #5 (`test`, `secret-scan`) | green (last run on 0f4651d) |
| Try to enable a restricted source (`UPDATE sources SET enabled=1 WHERE source_id='psx'`) | refused by CHECK constraint |
| Sources with `enabled=1` or `ACTIVE` in seed v2 | none |

## 2. Acceptance criteria
| Criterion | Evidence | Status |
|---|---|---|
| 3–5 permitted high-value sources (spec §14) | 4 RSS sources live-dry-run tested (PBS, Dawn, Business Recorder, Express Tribune); The News implemented (feed stale) | MET technically. **Not ACTIVE**: terms pages not found, so permission is unconfirmed |
| Two runs idempotent | `tests/test_collectors.py` repeat-run and dedup tests | MET |
| URLs and dates traceable | canonical + original URL, raw and UTC timestamps, tz offset, publication-time status, immutable provenance trigger | MET |
| robots.txt respected | `HttpClient.allowed_by_robots`; 401/403 robots → disallow all; EIA `/rss` correctly refused live | MET |
| Rate limits, retries, Retry-After cap, size cap | `collectors/http.py` per-host throttle, backoff, capped Retry-After, 5 MB cap; tests | MET |
| Incremental collection | conditional requests (ETag / If-Modified-Since), `collector_checkpoints`, `since_utc` | MET |
| Deduplication | canonical URL, external ID, content hash, versions, syndicated-copy flag | MET |
| Provenance | migration 0006 `original_url`, `retrieval_method`, `collection_run_id`, `http_status`, `document_type`, `source_metadata_json` | MET |
| Source-health monitoring | `source_health` view, failure counters, `last_error` | MET |
| Migration 0006 | additive only (ALTER ADD COLUMN, new tables, triggers, view); ACTIVE gated by approved terms + verified access + enabled | MET (tested locally; **not applied to production Turso**) |
| No restricted source activated | none ACTIVE or enabled; DB constraint and triggers enforce it | MET |
| Scheduled collection | `scheduled-jobs.yml` (every 6 h, concurrency group) | NOT EXERCISED: repository Turso secrets not set; nothing ACTIVE to collect |

## 3. Registry review (64 sources)
Lifecycle counts: NOT REVIEWED 39 · REVIEWED 9 · BLOCKED 5 · RESTRICTED 4 · TESTED 4 ·
LICENCE REQUIRED 2 · IMPLEMENTED 1 · ACTIVE 0.

- **Categories:** 24 categories cover exchange, central bank, regulators, government, statistics,
  Pakistani media (8), international media (8), institutions (7 AMCs/MUFAP), brokers (11),
  international institutions, energy and social. The categories match the spec's source families.
- **Pakistan financial news:** Dawn, Business Recorder and Express Tribune are TESTED. The News is IMPLEMENTED,
  but its feed's newest item is from May 2026, so the right business feed must be found. Profit and
  Mettis are REVIEWED (no feed), Nukta is REVIEWED, and Investify is NOT REVIEWED (see F3).
- **Ministry of Commerce:** registered (`commerce`, high priority per owner). It is BLOCKED because the
  site and robots.txt return HTTP 403 to automated requests. It needs an official channel. The registration is correct.
- **Official sources:** SBP, SECP, Commerce and IMF are BLOCKED (403 or no permission). FBR, OGRA, NEPRA, MoF,
  World Bank and ADB are REVIEWED. PBS is TESTED. EIA is RESTRICTED: robots.txt disallows `/rss`; the
  permitted route is the EIA Open Data API with a free key from the owner.
- **PSX (`psx`, `psx_dps`):** RESTRICTED, `prohibits_automation`, `not_permitted`. This is correct.
- **Reuters:** LICENCE REQUIRED. Correct, per owner decision C6.
- **X and YouTube watchlists** (`media_watchlist.json`): 32 records, matching the owner's list:
  - 23 X handles stored exactly as supplied, including KhaqanNajeeb, iabdullah278 and 4xpakistan;
  - 2 pending entries without a confirmed handle (Trump, Reuters);
  - 7 YouTube channels.

  The platforms are `x_platform` (LICENCE REQUIRED, paid API) and `youtube_platform` (NOT REVIEWED,
  needs an API key). No collection is implemented, which is correct: it is deferred to Phase 11.

## 4. Outstanding issues (owner approval needed before changing PR #5)
| # | Severity | Finding | Proposed fix |
|---|---|---|---|
| F1 | **High (safety)** | `collect(..., dry_run=True)` is allowed for any lifecycle status. A dry run fetches and parses without writing, but it would still make network requests to a RESTRICTED, BLOCKED or LICENCE REQUIRED source if that source has an adapter and feed URL. Today only EIA qualifies, and robots.txt stops it. The guard should not depend on robots.txt. | Refuse dry runs unless lifecycle is REVIEWED, TESTED, IMPLEMENTED, APPROVED or ACTIVE (never RESTRICTED, BLOCKED or LICENCE REQUIRED). Add a regression test. |
| F2 | Medium | The PR #6 findings (merged on `main`) are not reflected: Investify terms prohibit automation; SCS Trade publishes no terms. PR #5 still shows both as NOT REVIEWED / "website not yet verified". PR #5 is also 2 commits behind `main`. | After merging `main` into PR #5: `investify` → RESTRICTED / `prohibits_automation`; `scstrade` → REVIEWED / `not_found`; regenerate the register. |
| F3 | Medium | The PR #7 §10 findings are not yet applied. | Apply as **register records only, none ACTIVE**: add `pucars` (REVIEWED, TLS certificate expired), `capitalstake` (LICENCE REQUIRED), `sarmaaya` (RESTRICTED); `mettis` licensing → `licence_required` for data; add the reCAPTCHA and data-request notes to `psx`/`psx_dps`. These findings record access routes. **They do not authorise collection.** |
| F4 | Low | `thenews` is IMPLEMENTED while its feed is stale (May 2026). | Keep it at IMPLEMENTED, not TESTED, until the correct business feed is identified and dry-run tested. |
| F5 | Low | The `collectors/run.py` docstring example uses `--source dawn_business`; the real ID is `dawn`. | Fix the docstring. |
| F6 | Info | Production Turso is still at migration 0005; 0006 has not been applied; GitHub has no Turso secrets. | After the PR #5 merge and owner approval, apply 0006 (its rolled-back integration test already checks it), then add the secrets so scheduled runs can be exercised. |

## 5. Blockers needing the owner
1. Approve F1–F5 to be applied on the PR #5 branch, then re-review and merge PR #5.
2. Terms approval per publisher. Without written terms or permission, no source can become ACTIVE.
   Options: contact the publishers (owner's decision; I will not contact them), or accept a
   documented RSS-headline-and-link-only policy for specific publishers.
3. EIA Open Data API key (free) if EIA data is wanted.
4. Turso production: approve applying 0006, and later 0007, and adding the GitHub repository secrets.
