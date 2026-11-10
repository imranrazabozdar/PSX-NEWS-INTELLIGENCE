# Next 30 implementation tasks

Last verified: 2026-11-10. Order is priority within each group. Each task must start by inspecting the named files and their branch. Reuse before rebuilding. Owner approval flags: **A** = needs owner approval before merge; **P** = needs owner approval before any production action.

## Group 1: integration and safety (do first)
1. **Merge-readiness of PR #57.** Objective: keep the provider port merge-ready. Files: `engines/llm_live.py`, `config/llm_providers.json`, `tests/test_llm_live.py`, `.gitleaksignore`. Dependencies: none. Acceptance: CI green, owner approval. Tests: `tests/test_llm_live.py` (21). DoD: owner merges. Approval: A.
2. **Fix secret-scan on PRs #58–#63.** Objective: each branch includes `.gitleaksignore` from main after #57 merges. Method: merge `main` into each branch (no force push, no history rewrite). Files: `.gitleaksignore`. Acceptance: `secret-scan` green on each PR. Approval: none to fix; A to merge.
3. **Merge PR #58 (database ownership) first among the safety branches.** Files: `database/connection.py`, `tests/test_database_ownership.py`, callers listed in the PR. Acceptance: full suite, independence check. Approval: A.
4. **Extend quarantine to every legacy table.** Objective: identify technical-origin rows in `market_bars`, `companies` (stubs), `company_aliases`, `source_items` (Investify) and `llm_calls` by provenance (`collector_runs` ids 38–41 and schema versions), and expose them through a read-only helper. Files: `engines/quarantine.py`, new read helpers. Tests: extend `tests/test_quarantine.py`. Acceptance: no read path in news scoring uses them unless the owner approves. Approval: A.
5. **Full read-path audit for quarantine.** Objective: list every query on `event_extractions`, `market_bars`, `companies`, `source_items`, and check each. Files: all `engines/*.py`, `collectors/*.py`, `app.py`. Acceptance: a written table in the testing register; a test per path. Approval: A.
6. **Read-only production verification with a fresh token.** Objective: confirm row counts and legacy rows. Needs owner's read token (OWNER_ACTIONS 3). Files: a read-only script under `scripts/`. Tests: the script refuses any non-SELECT statement. Approval: P for the token, none for read.
7. **Verify the ownership guard on main after #58 merges.** Check: `TursoHTTPDatabase` refuses non-owned hosts. Tests: `tests/test_database_ownership.py`. Approval: A.

## Group 2: review and port of pending technical work
8. **Review PR #66 (technical) line by line.** Objective: decide, per module, port, adapt or discard. Files: `fundamental_engine/extract/dedup.py`, `fundamental_engine/extract/entities.py`, `fundamental_engine/extract/evaluate.py`, `fundamental_engine/sources/acquire.py`, `docs/EXTRACTION_QUALITY.md`. Output: a decision table in the PR register. Approval: A (owner decides).
9. **Port the cross-source dedup logic (if approved by task 8)** into the news repository, using `engines/similarity.py`, with its own tests. Do not copy. Tests: near-duplicate and exact-duplicate cases; number-preservation test. Approval: A.
10. **Port the acquisition gating logic as a dormant framework (if approved)**, default refusing, with `metadata_only` sources never eligible. Tests: refusal for every retention mode other than full-text permitted; robots and paywall rules. Approval: A.
11. **Review PR #59 (technical) Patterns tab.** Decide keep or merge. It is the technical project's, so it stays there. Approval: A (owner).

## Group 3: financial statement engine (core)
12. **Real-report pipeline, end to end, for one company (OGDC if supplied).** Objective: import a real annual report via `engines/document_intake.py`, extract statements with `engines/pdf_extraction.py` and `engines/financials.py`, reconcile subtotals, record page evidence. Files: as listed. Tests: a test that reads the stored report and checks every subtotal. Acceptance: reconciliation within tolerance with page numbers. Approval: P for storing the report in production. Depends on: OWNER_ACTIONS 19.
13. **Notes extraction on the real report.** Use `engines/notes_extraction.py` (branch PR #62) for receivables, borrowings, tax, leases and segment notes. Acceptance: every value has page and verbatim line; ambiguous rows are reported, not chosen. Depends on: 12, 19.
14. **Receivables ageing parser.** Objective: extract ageing buckets from the receivables note; reconcile to the total. Files: new `engines/receivables_ageing.py`. Tests: synthetic table; reconciliation failure case; real-report case. Acceptance: unreconciled → no buckets presented. Depends on: 13.
15. **Multi-year series builder.** Objective: normalise a company's statements across years, with restatements tracked. Files: extend `engines/financials.py`. Tests: restatement and comparative tests. Acceptance: point-in-time `as_of` respected. Depends on: 12.
16. **Auditor's report extraction.** Objective: find the opinion wording and KAM headings on the auditor page, with page evidence, and feed `engines/earnings_quality.py` `audit_signals`. Files: new extraction helper. Tests: qualified, unqualified, adverse wording samples. Acceptance: nothing assumed clean. Depends on: 12.
17. **Earnings quality on real multi-year data.** Objective: trend analysis (receivables against revenue, CFO against profit) over at least three years, with improvement and deterioration detection. Files: `engines/earnings_quality.py`. Tests: a case where receivables grow faster than revenue then collection improves, and the output names the improvement. Depends on: 15.
18. **Cash conversion and working capital schedule.** Inventory, payables, working-capital days, with missing-input handling. Files: extend `engines/fundamentals.py`. Tests: unit and real-report. Depends on: 13.
19. **Debt, finance cost and liquidity schedule.** From notes; interest-bearing debt by type. Files: `engines/fundamentals.py`. Tests: as above. Depends on: 13.
20. **Capex, free cash flow and capital allocation.** Use the capex line from the cash flow statement; reconcile FCF definitions. Files: `engines/fundamentals.py`. Tests: definition consistency. Depends on: 12.
21. **Segment analysis on the real report.** Use `engines/segments.py` with the segment note. Acceptance: reconciled shares; unreconciled presents none. Depends on: 13.
22. **Subsidiary and associate mapping.** Populate the relationship tables from the report's group note, with evidence. Files: exposure tables (migration 0008) through repository functions. Acceptance: direct and indirect labelled separately. Approval: P for production writes.

## Group 4: valuation and forecasts
23. **Forecast engine, revenue and margins.** Driver-based, with explicit assumptions and provenance. Files: new `engines/forecast.py`. Tests: reproducibility; missing-driver refusal. Acceptance: no forecast without drivers. Depends on: 15.
24. **Forecast engine, cash flow and working capital.** Depends on: 18, 23.
25. **DCF with explicit assumptions and ranges.** Use `engines/valuation.py`, add sensitivity grid and margin of safety. Tests: formula tests with units; refusal when inputs are missing. Depends on: 24. Approval: A (owner approves assumptions).
26. **Relative valuation with sourced peers.** Peer data must be sourced; no invented multiples. Depends on: sourced peer data (blocked until supplied).
27. **Bank and insurer frameworks.** Separate valuation approach (for example book value and ROE based). Tests: industrial DCF refused for banks. Approval: A.

## Group 5: news, events and exposure
28. **Wire the relevance pre-filter into extraction.** Use `engines/relevance_prefilter.py` before any model call. Tests: no model call for irrelevant items; reasons recorded. Approval: A.
29. **Financial transmission for one sourced input** (for example, a sourced input-cost sensitivity). Output is quantified only with a sourced sensitivity. Files: `engines/impact_intel.py`. Depends on: 12, 22.

## Group 6: operations
30. **Scheduling review.** Confirm the scheduled-jobs workflow's activation, its Turso consumption, and the market-hours intervals (5–15 min, not one-minute). Acceptance: a written budget and a test on the scheduler's timing. Approval: P for any production schedule change.
