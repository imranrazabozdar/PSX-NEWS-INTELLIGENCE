# ARN transcript archive: distilled knowledge (undated)

Source: an archive of 215 long-form videos by one analyst, supplied by the owner as transcripts. The
speech is Urdu, auto-captioned into Devanagari.

**What is here**: `extracted/*.json` are distilled rows (one sourced fact per row, in our own words,
<= 300 characters). `ledger.json` records, per video, whether it is `extracted`, `pending` or
`skipped_personal_finance`, and which model extracted it. **No raw transcript text is stored here** and
none goes into Turso: the transcripts are large and the rows are what the brain needs.

**The archive carries no publication dates.** Every row says so (`source` ends "undated") and its
`source_date` is the date the archive was captured, never a publication date. The era a claim belongs
to is in `period` and only ever holds an absolute period the speaker stated ("FY25", "Budget 2026").
A time-bound claim with no stated period was dropped at extraction rather than left to mix eras.

**Relative recency IS recoverable**: the archive is in reverse-chronological order (newest first), checked
against 13 titles that state their own year. Position, not date, is therefore the recency key until real
upload dates are supplied.

**Attribution is to the channel, never assumed to be one person.** Some videos are hosted by someone else
("Shafy's Weekly") or feature a guest, and a transcript does not say who is speaking. Each row's source
therefore reads "Abdul Rehman Najam channel, '<title>' (YouTube transcript, undated)", and where the title
suggests a different host or guest it adds "speaker may be a host or guest, not the channel owner".
`scripts/prepare_transcript_capsule.py` applies this deterministically, so extraction does not have to.

**Not investment advice.** The rows are one analyst's views and mechanics, labelled `analyst_view` unless
they are checkable structural facts.

Workflow: extract -> `scripts/prepare_transcript_capsule.py` (validate, fold entity names, collapse
near-duplicates across ALL batches at once) -> `scripts/absorb_sector_capsule.py` (dry run, then `--apply`).

## Status: loaded into psx-library

All 215 videos are accounted for: **174 extracted** (60 by Opus, 112 by Haiku, 2 by Sonnet), **41 skipped as
personal finance**. 3,897 rows are in `research_fact`, and `video_source` holds all 215 videos with their
recency rank. Nothing here depends on Claude being available.

**Ask the brain with plain SQL** (newest video first):

```sql
SELECT v.archive_position, v.title, f.topic, f.fact_text
FROM research_fact f JOIN video_source v ON f.source_url = v.url
WHERE f.company = 'HUBC' ORDER BY v.archive_position;
```

**Rebuild and reload from this folder alone** (idempotent: a second run writes nothing):

```
python -m scripts.prepare_transcript_capsule --in-dir docs/research/arn/extracted \
  --in-dir docs/research/arn/extracted_haiku --in-dir docs/research/arn/extracted_dense \
  --in-dir docs/research/arn/extracted_sonnet --exclude docs/research/arn/excluded_rows.json --out capsule.json
python -m scripts.absorb_sector_capsule capsule.json          # dry run
python -m scripts.absorb_sector_capsule capsule.json --apply
python -m scripts.load_video_sources --apply
```

**Folders**: `extracted/` Opus, `extracted_haiku/` first Haiku pass, `extracted_dense/` Haiku re-run of the
eight chunks first extracted on a sparser prompt, `extracted_sonnet/` the two videos Haiku failed the gate on.
`quarantine/` holds those two failed Haiku files for audit; they are never loaded. `excluded_rows.json` lists
11 Opus rows ruled out because their numbers belong to another video of the same chunk.

**Known limits**
- Models reading several videos in one chunk can file a fact under the wrong video. The gate catches this
  only when a row carries a distinctive number (a year, a decimal, three or more digits); a bled row with no
  number would pass. Chunks of one video cannot bleed.
- `MACRO:PAKISTAN` holds about a third of all rows. Macro knowledge is not yet indexed by sub-topic.
- Companies without a known ticker are stored under their names; if one later gets a ticker, its rows need
  merging.

## Adding another channel (or Investify data)
The brain is built to take many sources. For each new source: keep its own folder `docs/research/<source>/`
with an index (id, title, url, channel), get verified upload dates (yt-dlp `id YYYYMMDD` lines, see
`scripts/build_video_dating.py`), extract with the same gated routine (Python first, Haiku default, Sonnet on
gate failure), then absorb with `scripts/absorb_sector_capsule.py`. Facts from different sources about the same
company merge under one entity; the company brief reports how many distinct sources back it, and warns when
knowledge is single-source. Conflicts between sources are surfaced by the council, never averaged.

## Company links (cause and effect)
`company_link` holds 2,579 analyst-stated links (driver -> affected company/sector/macro, direction, exact quote, fact id)
extracted from the archive by Haiku and gated in Python (`scripts/check_links_batch.py`: real fact, exact quote, valid
direction). Reload with `python -m scripts.load_company_links --dir <work dir> --apply`; it is idempotent and, like
every loader, may need a second run if the per-process write budget is reached. The council pack shows the most
event-relevant, newest links for the companies, their sectors and MACRO:PAKISTAN. They are views, never facts.
