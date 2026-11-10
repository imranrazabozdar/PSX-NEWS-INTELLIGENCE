# Master project handover

Last verified: 2026-11-10. News `main` = f2af9ed73da21737a6e81fda5970e4246cb10506. Technical `main` = 47e70e39baa1aaf2ab8013ec3496b281b2be25c3.
Labels: see README.md.

## 1. What the project is
Two independent projects. Only the first is handed over for continued development.

**Project 1, PSX-NEWS-INTELLIGENCE** (`imranrazabozdar/PSX-NEWS-INTELLIGENCE`, [SRC] `app.py`, `engines/`, `database/`). An institutional PSX research platform: company fundamentals and financial statements, annual and interim reports, corporate announcements, news intelligence, macro intelligence, industry and commodity exposure, financial impact, forecasts, DCF and relative valuation, and evidence-backed research reports. It must cover the whole relevant PSX universe. Today it covers 51 company records, of which 50 are listed and 1 delisted [SRC `database/seed/companies.json`, STATUS].

**Project 2, PSX-INTELLIGENCE-NEW-2026** (`imranrazabozdar/PSX-INTELLIGENCE-NEW-2026`). Technical market analysis: indicators, scanners, candlestick patterns, volume analysis, relative strength, and the `fundamental_engine/` prototype, whose work was later ported. [GIT] `main` = 47e70e3. Its `backend/` and `fire_engine/` trees are technical-analysis code, not news work.

## 2. Permanent boundaries (ADR-0001)
Neither project may import, read, write, share a database, share credentials or share workflows with the other. Full rules: `REPOSITORY_AND_DATABASE_BOUNDARIES.md`. One exception was approved in writing: a scoped, time-limited port of `fundamental_engine/` (news ADR-0001, active until 2026-12-09 or until the port completes). It covers reading and copying that directory only.

## 3. Architecture (news project) [SRC]
Pipeline, as described in `docs/SPECIFICATION` and implemented in part:
Source → collector (`collectors/`) → canonical source item (`database/repositories.py`) → relevance pre-filter (`engines/relevance_prefilter.py`) → extraction (`engines/extraction.py`, LLM via `engines/llm.py`) → verification and clustering (`engines/verification.py`, `engines/similarity.py`) → entity resolution (`engines/entity_resolution.py`) → exposure (`engines/exposure_mapping.py`) → impact (`engines/impact_intel.py`) → financials and valuation (`engines/financials.py`, `engines/fundamentals.py`, `engines/valuation.py`) → reports and dashboard (`engines/reports.py`, `engines/research_views.py`, `app.py`).

Storage: Turso (libsql over HTTP), one production database, accessed through `database/connection.py`. Migrations in `database/migrations/` are the ledger of record (`schema_migrations`, SHA-256 per file). Schema: 14 migration files on `main`. There are 65 distinct `CREATE TABLE` statements and 15 `CREATE VIEW` statements in those files [SRC]. A live read-only check on 2026-11-10 counted 66 tables [PROD-RO].

## 4. History (verified from GitHub unless stated)
News repository, in order (all [GIT]):
- Phases 0–4 and M2–M10 were built through news PRs #34–#47, which are merged [GIT]. Earlier PRs (#1–#33) are [REPORTED] as the phase PRs in `docs/STATUS.md`, not rechecked.
- PR #52 (merged 2026-11-09): the version-11 remediation (A2). It removed the foreign migration and was verified on production. Migrations 0011–0014 were applied afterwards by the owner's instruction. Read-only check on 2026-11-10 confirmed ledger 1–14 [PROD-RO].
- PRs #54 and #55 (merged): the scoped ADR-0001 exception and the relevance pre-filter port.
- PRs #57–#63 (open): LLM providers, database ownership, quarantine, evaluation harness, earnings quality, segments and notes, architecture correction. PRs #48–#51 (open, older): OGDC accounting and coverage work, which is unique and must be preserved.
- PR #53 and #56 were closed as superseded. Neither was merged.

Technical repository (all [GIT]):
- PRs #57–#59 (merged except #59): Wyckoff and Patterns work, and the Patterns tab redesign.
- PR #59 is OPEN: "Patterns tab: presentation-only redesign" (head `07ed74d…`, branch `claude/11-stocks-forensics-report-3w23o7`). Unique work. Preserve.
- PRs #60–#65 (merged): Investify pilot, manual PDF vault, company-master stubs, the `fundamental_engine/` layer, relevance and provider cascade, and the review workflow with migration 0011.
- PR #66 (OPEN, "DO NOT MERGE YET"): extraction quality (dedup, entity resolution, gated acquisition, evaluation). Head `b81c26c`. Its evaluation and dedup code is not on `main`. Preserve.
- PR #67 (OPEN): refusal of the news database. Head `e5efbac`.

## 5. The shared-database incident (summary)
The technical engine wrote to the news production database: OHLCV bars, Investify rows, stub companies and aliases, extraction runs and a migration. The version-11 migration collided with the news migration sequence. Full account: `SECURITY_AND_INCIDENT_REGISTER.md` and `MIGRATION_AND_DATABASE_RUNBOOK.md`.

## 6. Current verified state
- Production ledger: versions 1–14 present; version 11 is `financial_documents` [PROD-RO 2026-11-10].
- Foreign objects (`extraction_reviews`, `v_review_queue`, its index and triggers): absent [PROD-RO].
- Old production write tokens: invalidated. A read with the old credential returned HTTP 401 on 2026-11-10 [PROD-RO]. Deletion of saved copies in the shared Default environment: [UNKNOWN] (owner to confirm).
- Live LLM output in production: 15 `llm_calls` and 15 extraction candidates, reported 2026-11-09 and not rechecked [REPORTED]. None reviewed.
- Technical database separation: NOT done. The owner has to create a separate database (`OWNER_ACTIONS_REQUIRED.md`).

## 7. What is safe to rely on
- The news `main` branch contains the relevance pre-filter, the financial, valuation, fundamentals, impact and exposure modules, and the entity resolver [SRC].
- The news branches listed in the PR register contain the code for quarantine, evaluation, earnings quality, segments, notes and providers. They are not on `main` until merged.
- Production migrations 0011–0014 exist and are applied, but no module that uses those tables has been activated [REPORTED plus PROD-RO ledger check].

## 8. What must not be assumed
- That a file existing means its feature works. See `CURRENT_IMPLEMENTATION_INVENTORY.md` for the status of each module.
- That any metric in a PR body is current. Re-run it.
- That synthetic evaluation proves accuracy. It does not.
- That the technical project's provider terms attestation applies to the news project. It does not.

## 9. Where to start
Read `MASTER_PROMPT_FOR_NEXT_CODING_AGENT.md`, then `NEXT_30_IMPLEMENTATION_TASKS.md`. Before changing code, inspect the branch and PR the task names.
