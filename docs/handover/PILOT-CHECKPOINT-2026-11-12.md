# Pilot checkpoint, 2026-11-12: feature/financial-pdf-reconciliation

Status: CHECKPOINT. Not merged to main. Owner decision pending on merge. No watchlist scale-up has started.

## What this branch delivers

1. **PDF extraction and reconciliation (offline).** Coordinate-based de-overprint, de-shadow of copy-columns, the
   distinct-column integrity gate, interim income-statement period roles from header groups, and equity without
   assets-minus-liabilities (`engines/layout_words.py`, `engines/position_identities.py`, `scripts/run_position_identities.py`).
2. **IR fetcher (polite, live-tested on four companies).** Registry, robots, per-host interval, backoff, PDF vault
   (`engines/ir_fetcher.py`, `config/ir_registry.json`, `scripts/run_ir_batch.py`).
3. **Investify, consented (announcements, fundamentals, profile, competitors).** Shared policy with the 15-minute cap,
   robots, conditional requests, backoff, audit log and attribution (`collectors/investify_policy.py`,
   `collectors/investify_job.py`, `collectors/investify_fundamentals.py`, `engines/investify_extract.py`,
   `engines/investify_collector.py`).
4. **Consent records.** `docs/consent/investify-2026-11-12.md` (announcements) and
   `docs/consent/investify-fundamentals-2026-11-12.md` (fundamentals, profile, competitors; gate decisions).
5. **Extraction findings.** `docs/coverage/EXTRACTION_FINDINGS-2026-11-12.md`: the parser works on the pilots;
   input quality is the binding constraint.

## Gated or working

| Item | State |
|---|---|
| Deterministic extraction on pilots (UBL, OGDC, LUCK) | TESTED: 30 of 30 cells green, from owner-supplied PDFs |
| NRL | needs_manual: text layer shadow-corrupted; identities hand-verified; key totals to be keyed by hand |
| HUBC annual | NOT PROVEN by identity checks (balance sheet ambiguous, income statement unresolved) |
| HUBC quarterly, PSO | needs_OCR (no text layer). OCR is NOT approved |
| LUCK live fetch | needs_manual: report host robots-disallowed |
| POL, ATRL, PPL | unreachable / unverified / blocked by site; not bypassed |
| Investify HUBC pilot | IMPLEMENTED and TESTED. Fundamentals (first fill, 25 metric cards), announcements (40 items, no trigger), competitors (sector-derived, 16), profile (with description). Live proof and audit: see STATUS |
| Investify, first fill and refresh rules | Owner-confirmed. Tests in `tests/test_investify_fundamentals.py` |
| Competitors | Owner-confirmed as sector-derived (16). Displayed tab is 14 |
| Investify private retention and analysis-output restriction | Owner-confirmed |

## Deferred

- **Watchlist scale-up** (the same extractors across the full watchlist): not started; needs owner approval.
- **On-demand PDF-upload tab:** a separate phase; not started.
- **Parked architecture decisions:**
  - the acquisition strategy for scale (authorized data vendor vs free manual-import watchlist), a pending owner decision;
  - OCR for image-only and vector-outline PDFs (not approved);
  - archive DDL and production migrations (awaiting owner approval, unchanged);
  - the Turso database (not written; policy unchanged).

## Known caveats

1. **Pre-fix throwaway file.** Before the storage fix, the structured fields were not kept: `store_structured` persisted
   only a hash. Rows from that period (HUBC profile of 08:32Z, announcements of 08:50Z, and the first fundamentals
   store) live in `operational_local_PRE_FIX_hash_only.sqlite` in the session scratchpad, not in the gate database. They
   are NOT evidence. The gate evidence is in `operational_local.sqlite`.
2. **Sector-derived versus displayed (16 vs 14).** The competitors record is a superset by two (GEMMEL and NGLEL are
   same-sector but excluded by Investify). The record states this. Analysis must say which set it uses.
3. **Audit label.** The 09:47:26Z competitors request was logged `manual=true` in error (a first backfill). A correction
   line is appended; the original is kept. The code now records `manual` only for genuine manual refreshes.
4. **Probe script is development-only.** `probe.py` (session scratchpad) is not part of the repository. It made the
   policy-compliant development requests and held one transient copy each. The repository path is `run_endpoint`.
5. **Structured fields only.** The raw body is never persisted. The company description is stored per the owner's
   decision. Investify's copyright terms (`conditionsOfAccess`: "shown for viewing only, not for redistribution") apply.
6. **Pagination.** The announcements page has 5 pages. Only page 1 is read. For HUBC that covers about 12 months.
7. **Peer cards render client-side.** The competitors set comes from the embedded index, not from the displayed tab.

## Gate and verification

- `scripts/check_independence.py`, `ruff check .`, and `pytest` pass on this commit.
- Archive, production and Turso: not written. Turso and archive URL variables are unset in the working environment.
- The operational database used for the gate is a local SQLite file (`operational_local.sqlite`).

## Owner decisions still needed

1. Merge `feature/financial-pdf-reconciliation` to main (large branch; owner decision).
2. Approve or defer the watchlist scale-up.
