# Testing and validation register

Last verified: 2026-11-10. Commands run in this environment are marked [TEST].

## 1. Test suites and counts
| Repository and branch | Command | Result | Source |
|---|---|---|---|
| News, `docs/architecture-correction` (main plus docs) | `pytest --collect-only` | 981 collected = 932 passed + 49 skipped (the same tree before the docs were added) | [TEST] |
| News, `feature/port-llm-providers-v2` | full suite in CI | all checks green on cd5c72d | [CI] |
| News, other feature branches | full suite locally | 944–950 passed, 49 skipped, depending on the branch | [TEST] on each branch when built |
| Technical, `feature/refuse-shared-news-database` (`fundamental_engine` only) | `python3 -m pytest` in `fundamental_engine/` | 242 passed, 4 skipped; 246 collected | [TEST] |
| Technical, all of `backend/` and `fire_engine/` | not run in this package | [UNKNOWN] | — |

Skipped tests in the news repo are opt-in live or disposable-database tests (`PSXNI_TEST_*`, `PSXNI_LIVE_SOURCE_TESTS`, the disposable Turso gate). They are not evidence of live behaviour.

## 2. Lint and guards (news)
`ruff check .`, `scripts/check_independence.py` (ADR-0001 scanner, run on every branch), `pip check`, `scripts/check_installed_sources.py`, `pip-audit`, gitleaks (CI secret-scan with a canary). The secret-scan is failing on open PRs #58–#63 (see PR register).

## 3. Real-data validation (what has actually been checked)
| Area | What was checked | Evidence | Status |
|---|---|---|---|
| A2 remediation | SQLite and Turso rehearsal (Turso: 26 passed, 2026-11-09); production executed and verified | [REPORTED] PR #52; [PROD-RO] ledger 2026-11-10 | 7 for the production change |
| Migrations 0011–0014 | Applied on production; ledger and integrity read | [REPORTED] + [PROD-RO] | 7 for ledger; row counts [UNKNOWN] |
| Company master (50 listed) | Seeded from PSX sources | [REPORTED] STATUS | 6 for seeded records |
| Investify announcements (21 rows) | Live ingest, independent Turso queries | [REPORTED] PR #61 | 6 (restricted source) |
| OHLCV pilot (120 rows) | Live run, one symbol set | [REPORTED] PR #60 | 6 for that run; not a feed for production use |
| Extraction (15 candidates) | Live Groq calls, all headline-only | [REPORTED] PRs #63, #65, #66 | 6 for the mechanics; quality: direct company match 0/15 [REPORTED] |
| Relevance pre-filter | Tuned on 407 stored headlines (4% → 14% pass) | [REPORTED] PR #64 | 6 for that corpus only |
| Financial statements (any real company) | None imported and checked end to end in the news repo | [UNKNOWN] | 1–3 |
| OGDC annual report | Coverage register on PR #51 (not read in this package) | [GIT] branch exists | [UNKNOWN] |

## 4. Synthetic evaluations (do not cite as accuracy)
- Technical PR #66 controlled sample: dedup precision 1.00 / recall 0.83; entity direct P/R 1.00/1.00 (11 cases); 0 invented tickers; validator 8/8 [REPORTED]. Its author wrote both the code and the sample. It guards behaviour only.
- News `engines/evaluation.py` (branch PR #60): hand-labelled synthetic sample of 8 entity cases, 3 dedup items, 3 quote cases, 4 usefulness records. All measures pass after one fix (`and` vs `&`). Also author-written. It guards behaviour only.

## 5. Test gaps (open)
- No test on real annual report text (PDF) end to end.
- No back-test on point-in-time financial data.
- No test for multi-year normalisation (not built).
- No test for receivable ageing, auditor text or KAM extraction (not built).
- No test that a legacy record is excluded from *every* read path. The static guard checks SQL text only.
- The scheduled workflow activation in production is not tested [UNKNOWN].
- Technical `backend/` and `fire_engine/` suites are not run in this package.

## 6. How to validate a change
1. Run the unit tests for the module.
2. Run the full suite for the repository.
3. Run `scripts/check_independence.py` and `ruff check .`.
4. For a database change: the disposable rehearsal and its gate, per the migration runbook.
5. For a financial change: reconcile against a real printed statement, page by page, and record the page numbers.
6. Record the commands and results in the PR body.
