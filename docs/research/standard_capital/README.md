# Standard Capital Securities (@SCStradepk): distilled knowledge (DATED)

Source: the channel's videos from 21 Nov 2023 to 13 Nov 2026 that run over 4 minutes: 466 videos, each with a
**verified upload date** (`dates.txt`, from yt-dlp) and title (`titles.json`, from YouTube oEmbed). Transcripts are
YouTube auto-captions (Urdu speech written in Devanagari); no raw transcript text is stored here or in Turso.

Status (see `ledger.json`, per video id): 449 extracted, 3 reviewed-empty (tutorials / account opening), 5 caption
too short to use, 9 with no captions at all. The last 14 are the retrieval gaps (try `youtube_transcript_api`).
7,269 rows extracted, 7,161 after near-duplicate removal, all loaded into psx-library `research_fact`.

Every row carries the video's real date as `source_date` and in the source line, so a view from 2024 is never
mistaken for one from this month. Numbers in a row must appear in its own transcript (digits), so a figure the
captions garbled or only spoke in words is left out rather than guessed.

## How it was made (reproducible, Python first)
1. `python -m scripts.clean_captions --raw <vtt dir> --dates dates.txt --titles titles.json --out <work>`: clean
   rolling captions, cut 30k-char work chunks that never split a video.
2. Extraction on Haiku per chunk with `EXTRACTION_SPEC.md` (dated rules + figures sweep). Proof on one video:
   Haiku without the sweep found 52% of the figures, with it 96%; Sonnet 100%. Haiku-with-sweep was chosen.
3. `python -m scripts.check_extraction_batch --dated ...` gates each video (grounding, bleed, relative time
   words, advice, figure coverage).
4. `python -m scripts.repair_extraction ...` drops defective rows (about 4.5%) and builds targeted missed-figure
   hints; a second small Haiku pass turns those into rows; `--add-dir/--final-dir` merges them.
5. `python -m scripts.prepare_transcript_capsule --in-dir extracted --channel "Standard Capital Securities"
   --dates dates.txt --titles titles.json --out capsule.json`, then
   `python -m scripts.absorb_sector_capsule capsule.json --apply` (idempotent; re-run if the write budget stops it).
