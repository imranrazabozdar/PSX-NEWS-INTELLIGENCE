# Collectors (Phase 2)

Architecture and rules: [ADR-0005](adr/0005-source-collection-engine.md). Each source's access
review: [SOURCE_ACCESS_REGISTER.md](SOURCE_ACCESS_REGISTER.md), generated from
`database/seed/sources.json`.

## Modules
| Module | Purpose |
|---|---|
| `collectors/http.py` | Polite HTTP client: robots.txt, per-host rate limit, timeouts, retries with backoff, `Retry-After`, conditional requests, size cap. Swappable transport for tests. |
| `collectors/parsers.py` | RSS 2.0, Atom, JSON API, permitted HTML tables, PDF document metadata, timestamp parsing. Refuses XML with DOCTYPE/ENTITY. |
| `collectors/engine.py` | Pipeline: `collect()` (feeds and APIs), `collect_document()` (official documents), `fetch_pages()` (pagination), `due_sources()` (scheduler). |
| `collectors/run.py` | CLI used by the workflow and for manual runs. |

## Running
```bash
# dry run: fetch + parse, nothing written (works for any source with an adapter)
python -m collectors.run --source dawn --dry-run
# collect all ACTIVE sources that are due (what the schedule runs)
python -m collectors.run --due
# bounded backfill of one ACTIVE source
python -m collectors.run --source <id> --since 2026-11-01T00:00:00Z --until 2026-11-07T00:00:00Z
```
The scheduled workflow (`.github/workflows/scheduled-jobs.yml`) needs the repository secrets
`PSXNI_TURSO_DATABASE_URL` and `PSXNI_TURSO_AUTH_TOKEN`. The repository variable
`PSXNI_KILL_SWITCH=true` stops it.

## Activating a source
1. Review the source's terms of use and licence, robots.txt and access method, and record the
   outcome in `database/seed/sources.json` (`terms_status`, `licensing_status`, `review_notes`).
2. The collector must pass its fixture tests and a live dry run.
3. In a PR, set `terms_status: approved`, `access_status: verified_permitted` and
   `lifecycle_status: ACTIVE`. The database refuses ACTIVE without the first two. Then
   regenerate the register (`python scripts/build_source_register.py`).
4. After merge, load the seed (`python -m database.seed_loader`).

## Item lifecycle
| Situation | Result |
|---|---|
| New URL / ID | `inserted` (version 1) |
| Same URL / ID, same content hash | `unchanged`, nothing written |
| Same URL / ID, changed content (e.g. corrected headline) | `new_version` appended; original row kept |
| Different URL, identical content (syndicated copy) | stored, `duplicate_of_item_id` set; not independent corroboration |
| No publication time in the source | `published_at_utc = NULL`, `publication_time_status = 'unavailable'` |
| Entry without link or ID, or malformed | item counted as failed; the run is `partial` |
| Fetch or parse failure | run `failed`; source failure counters incremented |

## PSX market bars (`collectors/market_ohlcv.py`)
- **Source:** `scs_chart`, the SCS Trade chart datafeed (TradingView UDF `/history`). The owner authorised it
  on 2026-11-08 on condition of honest requests: the project's own User-Agent, no spoofed browser headers,
  no Referer, and robots.txt respected.
- **Timeframes:** `1m`, `1h`, `4h`, `1d` (provider resolutions `1`, `60`, `240`, `D`).
- **Incremental:** each run resumes from the last stored bar, with a 3-bar overlap. The first run backfills
  5 days (1m), 90 days (1h), 365 days (4h) or 5 years (1d).
- **Storage (migration 0010):** append-only. A changed value becomes a correction, and invalid or
  misaligned bars are rejected and counted. The per-run database budget applies; a run that reaches it
  ends `partial`, and the next run resumes.
- **Running:**
  - `python -m collectors.market_ohlcv --symbols OGDC,HBL --dry-run` fetches and validates without writing.
  - `python -m collectors.market_ohlcv --due` is what the scheduled workflow runs.
  - The default symbols come from `PSXNI_MARKET_SYMBOLS`.

## News tagging (`engines/news_tagging.py`)
Companies, sectors, themes and "potentially market-moving" flags are computed from stored headlines at
read time:
- Companies come from capitalised PSX tickers or exact company-master names, confirmed by
  `engines.entity_resolution`. Name matches are flagged "needs review".
- Sectors come from the company master.
- Themes and flags are keyword matches.

Every tag shows its evidence, and nothing is presented as a verified impact.
