# Nukta Business (@NuktaBusiness): distilled knowledge (DATED)

Source: the channel's videos from 29 Apr 2025 to 14 Nov 2026 that run over 4 minutes: 334 videos, each with a
verified upload date (`dates.txt`) and title (`titles.json`). 324 have YouTube auto-caption transcripts (Urdu speech
in Devanagari); 10 have none (see `ledger.json`). The channel is business news and interviews, so the extraction
spec (`EXTRACTION_SPEC.md`) attributes views to guests, reporters or company management, never to the channel.

## Status: IN PROGRESS (resume point)
Extraction paused by the account's weekly usage limit (resets 21 Nov 2026, 02:00 UTC). `ledger.json` records, per
video id, what is done: 65 extracted (1,739 rows loaded into psx-library), 259 pending, 10 without captions.
To resume: audit by video id (`ledger.json` / `out/` files), re-launch only the chunks with pending videos
(`clean_captions` chunks, one video per chunk for most), then `repair_extraction` (+ a Haiku figures pass for videos
the gate flags), `prepare_transcript_capsule --channel "Nukta Business" ...` and `absorb_sector_capsule --apply`.
Each step is idempotent, so a restart never repeats work.

Proof before scaling (same method as Standard Capital): Haiku with the figures sweep on an earnings segment and a
property interview passed the dated gate (59 rows).
