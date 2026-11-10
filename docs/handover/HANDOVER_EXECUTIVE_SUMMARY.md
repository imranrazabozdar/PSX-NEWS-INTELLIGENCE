# Handover executive summary

Last verified: 2026-11-10.

## What the project is
A research platform for the Pakistan Stock Exchange. It aims to turn permitted news, official disclosures, annual reports and macro data into evidence-backed company analysis: financial quality, valuation, exposure to events, and research reports. Every conclusion must trace to a source and a page. It is not a trading system.

## Two repositories, kept separate
- **PSX-NEWS-INTELLIGENCE** is the project to continue. Its `main` branch holds the database layer, collectors, extraction and financial engines, the dashboard and 14 migrations.
- **PSX-INTELLIGENCE-NEW-2026** is a separate technical-analysis project. It must not share a database or code with the news project. Only one exception was approved: reading and porting its `fundamental_engine/` folder, until 2026-12-09.

## What works today
- The news production database is on a consistent schema: migrations 1–14 applied. A migration collision caused by the technical project was fixed in a guarded, verified operation.
- Offline financial tools exist: statement import, ratios, free cash flow, DCF and multiples, scenario models. They are tested on synthetic data.
- The news collectors are permission-aware and metadata-only. Eleven sources are verified for that.
- A relevance filter that runs before any model call is on `main`.
- The test suite passes: 932 tests plus 49 opt-in skips on the main line, and CI is green on the merge-ready provider PR.

## What went wrong, and is being fixed
- The technical engine wrote into the news database: market bars, company stubs, restricted listing rows and live model output. The rows are documented and not yet cleaned up. Guards to stop it are written and waiting for review.
- Several earlier reports overstated progress. This package records only what was checked.
- Live model output has not been reviewed by a human.

## What does not exist yet
- Processing of a real annual report end to end. This is the first real validation gap, and it needs a document from the owner.
- Multi-year normalisation, receivable ageing, notes schedules, auditor-text extraction, forecasts, sector frameworks for banks, and sourced peer valuation.
- Collectors for policy, commodities, brokers, YouTube and X.
- Any measured accuracy of the extraction. The only evaluations are synthetic, and they guard behaviour only.

## Where to begin
1. Read `MASTER_PROJECT_HANDOVER.md`.
2. Read `OWNER_ACTIONS_REQUIRED.md` and see what the owner must decide.
3. Give the agent `MASTER_PROMPT_FOR_NEXT_CODING_AGENT.md`.
4. Work through `NEXT_30_IMPLEMENTATION_TASKS.md`. Start with the safety PRs, then the real-report pipeline once a document arrives.

## Owner decisions now waiting
Separate the technical database, approve or reject the open PRs, decide what to do with the historical shared rows, and supply an annual report. Full list in `OWNER_ACTIONS_REQUIRED.md`.
