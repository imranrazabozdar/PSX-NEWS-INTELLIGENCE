# Nukta Business (@NuktaBusiness): distilled knowledge (DATED)

Source: the channel's videos from 29 Apr 2025 to 14 Nov 2026 that run over 4 minutes: 334 videos, each with a
verified upload date (`dates.txt`) and title (`titles.json`). 324 have YouTube auto-caption transcripts (Urdu speech
in Devanagari); 10 have none (see `ledger.json`). The channel is business news and interviews, so the extraction
spec (`EXTRACTION_SPEC.md`) attributes views to guests, reporters or company management, never to the channel.

## Status: LOADED (324 of 334 videos; 10 have no captions)
Every video with captions has been extracted, gated, repaired and loaded into psx-library (`research_fact`),
13,977 rows after near-duplicate removal, each with its real video date as `source_date`.
`ledger.json` records per video id: 318 extracted, 6 `no_rows` (personal-finance or profile videos where the
extraction agent found no market facts; not yet confirmed by a person), 10 `no_captions`.

Pipeline (same as Standard Capital): `clean_captions` chunks -> Haiku extraction -> `check_extraction_batch --dated`
-> `repair_extraction` (drops 646 defective rows: 599 numbers not in the source, 31 relative time words, 8 sibling
bleed, 8 advice wording) -> a Haiku figures pass on 55 videos (19 batches) -> merge -> gate again (304 of 324 pass; the 20
still flagged are long videos where garbled numbers were deliberately skipped, not guessed)
-> `prepare_transcript_capsule --channel "Nukta Business"` -> `absorb_sector_capsule --apply` (idempotent).

Known data-quality limits:
- The captions are Urdu speech written in Devanagari, so numbers are often garbled. Rows with a number that could not
  be confirmed were dropped, not guessed.
- 11 KSE-100 rows with an index level that lost a digit (for example 16,257 for about 162,000) and 2 more with
  garbled support levels were removed by hand after a plausibility sweep. Weekly and daily point-change rows were kept.
- Company names the agents could not map to a ticker stay as names (for example Hafco, FG); they are not
  invented tickers.
- The 10 videos with no captions can be fetched with the transcript-API fallback (to do).

Proof before scaling (same method as Standard Capital): Haiku with the figures sweep on an earnings segment and a
property interview passed the dated gate (59 rows).
