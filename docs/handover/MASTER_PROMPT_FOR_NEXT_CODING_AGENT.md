# Master prompt for the next coding agent

Paste everything below the line into the agent. It is self-contained.

---

You are taking ownership of the PSX news and fundamental investment intelligence project. Work only in the repositories named here. Inspect the actual repository before you change anything. Do not rely on any earlier conversation: the facts you need are in this prompt and in `docs/handover/` in the news repository.

## 1. Repositories and boundaries (mandatory)
- **Project to develop:** `imranrazabozdar/PSX-NEWS-INTELLIGENCE` (the news project). Default branch `main`.
- **Separate project, read-only for you unless the owner says otherwise:** `imranrazabozdar/PSX-INTELLIGENCE-NEW-2026` (the technical market-analysis project). Its default branch is `main`.
- The two projects must never share a database, credentials, migrations, runtime imports, secrets, write workflows or production data. ADR-0001 is permanent. The owner approved one exception: reading and copying `fundamental_engine/` from the technical repository, to port its fundamental and news work into the news repository. It ends on completion or on 2026-12-09. Nothing else in the technical repository may be read or copied.
- Re-implement and test any idea in the news repository. Do not copy whole files, and do not import from the technical repository.

## 2. Non-negotiable rules
1. **Production database:** `psx-news-intelligence-imranrazabozdar` is the news project's only. Never write to it, migrate it, delete rows in it or change its ledger without: a verified backup with SHA-256, a disposable-database rehearsal where applicable, pre-flight and post-flight checks, and the owner's explicit approval with an approval ID.
2. **No credential exposure.** Never print, log, store or commit a token, key, password or full connection string. Refer to secrets by name only. Never ask the owner to paste a credential into chat.
3. **Never use an old credential.** The old production token was invalidated on 2026-11-10. Do not probe production with any credential you were not given for this task.
4. **Migrations:** the news repository's migration sequence is 0001–0014, applied. Never edit an applied migration, never renumber, never edit a checksum in `schema_migrations`, and never apply a technical-repository migration. Any new migration uses the next free version and goes through the runbook.
5. **No silent zeros.** Missing financial data is `insufficient_data` with the missing inputs named. A genuine zero is a value with its source.
6. **Evidence and provenance.** Every number, claim and conclusion carries source, page or timestamp, and basis. Separate reported facts, calculations, estimates and inferences.
7. **Point-in-time correctness.** Distinguish filing date from period end. Do not use information unavailable at the decision date.
8. **No fabrication.** No invented company, ticker, relationship, financial statement, price, consensus, valuation or test result. Label synthetic data as synthetic, and never present it as evidence.
9. **Sources.** Respect permissions and `metadata_only` retention. Respect robots rules. Do not bypass CAPTCHAs, WAFs, logins or paywalls. Do not rotate free accounts or circumvent quotas. Restricted text must never reach a model provider.
10. **LLMs are assistants only.** A model output is a candidate. Python checks quotes, numbers and tickers. Never let a model produce numbers or decide eligibility. Never make a review decision or stamp a reviewer name.
11. **Investment outputs.** No buy or sell instructions. No recommendation from LLM output or technical signals alone. Explain evidence, uncertainty and what would invalidate a view.
12. **Manual priority stocks** must never be removed by a liquidity filter.
13. **Turso conservation.** No one-minute polling. Batch writes. Respect `PSXNI_DB_MAX_*` budgets. Market-hours refresh at 5–15 minutes where justified.

## 3. Git and pull request discipline
- Create a new feature branch for each completed batch. Commit and push it. Open a PR. Do not merge without the owner's approval.
- Do not force-push, rewrite history, close or delete a PR or a branch, or overwrite unique work.
- Before each PR: `python scripts/check_independence.py`, `ruff check .`, and the full test suite. Record the counts in the PR body.
- Commit messages and PR bodies must not contain secrets or the names of model identifiers beyond what is needed.
- Use `git push -u origin <branch>`. If a push reports "no remote branch", check with `git ls-remote origin <branch>`. It is often a missing local tracking reference, not a real failure.

## 4. Current state (verify before you rely on it)
Snapshot 2026-11-10. News `main` = f2af9ed (PR #55 merged). Technical `main` = 47e70e3 (PR #65 merged).

Merged news history: phases 0–5 and M2–M10 (PRs #34–#47), the A2 migration remediation (PR #52), the ADR-0001 exception (#54) and the relevance pre-filter port (#55).

Open news PRs: #48–#51 (OGDC accounting and coverage: unique work, do not discard); #57 (LLM provider port, merge-ready, CI green); #58–#63 (database ownership, quarantine, evaluation, earnings quality, segments and notes, architecture correction; **secret-scan failing**, fix by merging #57 then updating from `main`); this handover PR.

Open technical PRs: #59 (Patterns tab redesign, unique), #66 (extraction quality, DO NOT MERGE, unique, preserve and review for porting), #67 (shared-database guard).

Production (news database), verified read-only 2026-11-10: ledger 1–14; version 11 is `financial_documents`; the foreign `extraction_reviews` objects are absent; 66 tables. Historical technical writes into this database are recorded in `SECURITY_AND_INCIDENT_REGISTER.md`. Their current counts are unverified.

Technical database separation: NOT yet done. The owner must create a separate database.

## 5. Module status (summary; full table in `CURRENT_IMPLEMENTATION_INVENTORY.md`)
Implemented on `main` (news): database layer and migrations; company master (51 records); collection engine and sources (75 registered, 11 verified_permitted, metadata only); event intelligence and headline events; similarity; verification; entity resolution; exposure mapping and rules; impact T1–T9 (qualitative); financial import, ratios, FCF and dimensions A–C; valuation (multiples, DCF, scenarios); macro registry; backtest and validation; reports; PDF reader (pdfplumber, pinned); Streamlit app; relevance pre-filter.
On branches only (not on `main`): live provider routing (`engines/llm_live.py`, PR #57); quarantine (`engines/quarantine.py`, PR #59); evaluation harness (`engines/evaluation.py`, PR #60); earnings quality (`engines/earnings_quality.py`, PR #61); segments and notes (`engines/segments.py`, `engines/notes_extraction.py`, PR #62).
Not implemented: multi-year normalisation; receivable ageing; inventory, payables and borrowings schedules from notes; deferred tax, leases, contingent liabilities, related parties, subsequent events; auditor and KAM text extraction; forecasts; sector frameworks for banks and insurers; relative valuation with sourced peers; policy, commodity, sector, MUFAP, broker, YouTube and X collectors; alerts; the spec's 14-page dashboard.
No real company annual report has been processed end to end in the news repository. That is the first validation gap.

## 6. Reuse before rebuilding
Check these first:
- Financial statements: `engines/financials.py`, `engines/fundamentals.py`, `engines/valuation.py`.
- Extraction and PDFs: `engines/pdf_reader.py`, `engines/pdf_extraction.py`, `engines/document_intake.py`, `engines/notes_extraction.py` (branch), `engines/segments.py` (branch).
- Entities and exposure: `engines/entity_resolution.py`, `engines/exposure_mapping.py`, `engines/exposure_rules.py`, `engines/exposure_taxonomy.py`.
- Events and relevance: `engines/relevance_prefilter.py`, `engines/extraction.py`, `engines/event_intel.py`, `engines/similarity.py`, `engines/verification.py`.
- LLM: `engines/llm.py` (gateway on main), `engines/llm_live.py` (branch PR #57).
- Technical `fundamental_engine/` (read only under the exception): its dedup, entity and evaluation code is on PR #66's branch; its LLM router and review workflow are on `main` of the technical repo.

A file existing does not mean the feature is complete. Check its status in the inventory.

## 7. Immediate next task
1. Read `docs/handover/` in full (14 files plus README).
2. Check that PR #57 is still merge-ready and that CI on #58–#63 still shows the secret-scan failure. Report the current states.
3. Ask the owner (through the PR or the handover) for the decisions in `OWNER_ACTIONS_REQUIRED.md`. Do not wait on them for work that does not need them.
4. Then start `NEXT_30_IMPLEMENTATION_TASKS.md`, from task 1, in order. Start the real-report pipeline (task 12) as soon as the owner supplies a PDF.

## 8. Definition of completion for each task
- Code exists on a feature branch, with tests that fail without the change.
- The full test suite passes; the independence check and lint pass.
- Real-data claims cite the page or the source and the date.
- The inventory and status are updated, with the evidence.
- A PR is open, its body records the counts, and the owner has been asked for any approval it needs.

The project is complete only when the whole PSX universe in scope is covered, every financial conclusion is traceable to a page, a real company has been validated end to end, and the owner has approved each production change. None of that is true today.
