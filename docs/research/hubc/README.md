# HUBC (The Hub Power Company Ltd) — research folder

**Compiled:** 2026-11-12 (price reference in the briefs: about Rs 207, 12 Nov 2026).

**Nature of this material:** analyst research, prepared for private study. It is **not investment advice**, and it is
**not an input to any buy or sell decision** of this project. Nothing here is a recommendation.

## Files (stored unchanged)
| File | What it is |
|---|---|
| `hubc_financials_3yr.json` | Consolidated figures FY2024–FY2026 read from the audited statements (FY2025 filed 2025-09-03; FY2026 filed 2026-08-27). PKR thousands. |
| `HUBC_research_brief.md` | Part 1: financials and drivers. |
| `HUBC_research_brief_part2_macro.md` | Part 2: macro and policy, with cited external sources. |
| `HUBC_research_brief_part3_analyst_management.md` | Part 3: analyst and management views (SCS / Standard Capital 9MFY26 review, 22 Apr 2026; HUBC corporate briefing, 2 Sep 2026). |
| `HUBC_research_brief_part4_consensus_credit.md` | Part 4: credit rating and Street consensus. |

Note: the upload names were `HUBC_brief_part3_analyst_management.md` and `HUBC_brief_part4_consensus_credit.md`. They
are stored here under the names above. The contents are byte-identical to the uploads.

## Sources cited in the briefs
- Audited consolidated accounts FY2025 and FY2026 (HUBC filings).
- SCS / Standard Capital Securities, 9MFY26 result review (22 Apr 2026).
- HUBC corporate briefing takeaways (2 Sep 2026).
- PACRA rating maintained 02 Jun 2026 (AA+ / A1+, stable).
- S&P Global and MarketScreener consensus; Topline Pakistan DCF (Dec 2026 target).
- Macro and policy: Dawn (Dec 2024, 2025, Nov 2026); The News (2026); propakistani and profit.pk (2026); ARY News
  (Oct 2026); State Bank of Pakistan; Tribune; ArabNews and BR (Nov 2026).
- The briefs also cite Investify market data for the price reference. No Investify request was made to compile this folder.

## Use rules
- Facts are stored in the database only as distilled, sourced, dated rows (see `docs/research/hubc` and the
  `research_fact` table proposal). No PDF or raw page text is stored anywhere.
- Forward-looking or analyst-view items are labelled as analyst views, not as facts.

## YouTube commentary (added 14 Nov 2026)

`commentary_youtube.json` holds 87 distilled rows from three identified videos plus one unidentified compilation,
loaded into psx-library under the `commentary.*` topics. **Every row is `analyst_view`, never `fact`**: this is
third-party and management commentary relayed through video transcripts, not audited filings.

| Source | Speaker | Link |
|---|---|---|
| "Will HUBCO be the next SAZGAR?" | Abdul Rehman Najam (analyst) | https://www.youtube.com/watch?v=LLv27CaL9Fg |
| CFO interview, Pakistan & Counting | Muhammad Saqib, CFO | https://www.youtube.com/watch?v=dYhXldyQ-qY |
| Aaj News EP#05 | Kamran Kamal, CEO | https://www.youtube.com/watch?v=AqejJQFxAzE |
| Segment and EPS tables | not identified | owner to supply the link |

Each row carries its timestamp, so any claim can be checked against the video.

**Known limits.** The publication dates of the videos are not known, so `source_date` is the date this material
entered the system (2026-11-14) and `as_of` is left empty. Supply the dates and they can be corrected.

**Conflicts recorded, not resolved.** The sources disagree, and both sides are stored:
- **SECMC stake:** the analyst says it rose from 8% to 17.5% via HBL; the CFO says that purchase did not
  materialise and it stays at 8%. The research brief also says 8%.
- **CPHGC stake:** the brief says 47.5%, the analyst says 46%, the segment table says 50%.
- **Base plant in FY2027:** the EPS table assumes it is active again, while the analyst and CFO both describe
  the PPA as terminated.
