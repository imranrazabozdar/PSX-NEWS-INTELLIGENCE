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
