# PR, branch and commit register

Last verified: 2026-11-10 (GitHub and `git ls-remote`). "Head" is the branch head at that time. CI is from the GitHub check runs read on 2026-11-10.
No PR was merged, closed or deleted by this package.

## 1. News repository — `imranrazabozdar/PSX-NEWS-INTELLIGENCE`

### 1.1 Open PRs
| PR | Title | Head branch | Head SHA | Base | CI (2026-11-10) | Purpose | Recommendation |
|---|---|---|---|---|---|---|---|
| 48 | OGDCL pilot finalisation: approved OGDC mappings, cash codes, structural audit | `fix/ogdcl-pilot-defects` | 40f378bd34f7 | main | not read | OGDC accounting pilot | Preserve; review; unique work |
| 49 | OGDC accounting validation: comparative balances, cash definition, cash-flow adjustments | `feature/ogdc-accounting-validation` | 9b4aea88e58b | `fix/ogdcl-pilot-defects` | not read | OGDC validation | Preserve; review after #48 |
| 50 | Sector applicability matrix, earnings-quality indicators, M5 gap analysis | `feature/sector-applicability-m3` | ae39afc8c231 | `feature/ogdc-accounting-validation` | not read | Sector applicability | Preserve; review after #49 |
| 51 | OGDC FY2026 annual report integrity and page-coverage register | `docs/ogdc-fy2026-annual-report-coverage` | 6c3ed6140f36 | main | not read | Coverage register | Preserve; review |
| 57 | Port LLM providers with fallback and quotas, and correct the status register | `feature/port-llm-providers-v2` | cd5c72daacb1 | main | all 5 checks green (test, secret-scan, CodeQL, Analyze ×2) [CI] | Provider port (disabled by default) | Merge-ready; owner approval needed |
| 58 | Database ownership: fail-closed production host, purpose-bound connections | `feature/database-ownership` | 9a71214e1997 | main | `secret-scan` FAILED; `test` passed [CI] | Ownership guard | Fix secret-scan (see §3); then review |
| 59 | Quarantine legacy extraction records at read time | `feature/candidate-quarantine` | 4a9d468bae77 | main | `secret-scan` FAILED; `test` passed [CI] | Quarantine | Fix secret-scan; then review |
| 60 | Port extraction-quality evaluation on synthetic labelled cases | `feature/evaluation-harness` | 1a5a10824221 | main | `secret-scan` FAILED; `test` passed [CI] | Evaluation harness | Fix secret-scan; then review |
| 61 | Earnings quality and audit signals | `feature/earnings-quality` | 6731258b824b | main | `secret-scan` FAILED; `test` passed [CI] | Earnings quality | Fix secret-scan; then review |
| 62 | Segment reconciliation and notes extraction | `feature/segments-and-notes` | fcc70f413e49 | main | `secret-scan` FAILED; `test` passed [CI] | Segments and notes | Fix secret-scan; then review |
| 63 | Architecture correction | `docs/architecture-correction-2026-11-10` | 746ff2083dd6 | main | `secret-scan` FAILED; `test` passed [CI] | Documentation | Fix secret-scan; then review |
| — | Handover package (this package) | `docs/handover-package-2026-11-10` | see §4 | main | not yet run | Documentation | Review |

**Why secret-scan fails on PRs 58–63:** the gitleaks ignore file `.gitleaksignore` exists only on the PR #57 branch. Those PRs branched from `main` before it existed. The scan uses full history (`--log-opts=--all`), so two historical fingerprints (commits `a4d4d58…` and `80f9c87…`, file `tests/test_llm_live.py` line 24, a dummy test key) still match [CI log, read 2026-11-10]. The fix is to merge #57 and then update each branch from `main`. Do not rewrite history.

### 1.2 Closed PRs of note
| PR | Title | State | Note |
|---|---|---|---|
| 52 | Migration version-11 collision: A2 remediation | merged | Production remediation verified [REPORTED] |
| 53 | Docs: refresh STATUS after migration recovery | closed (superseded by #56, then #57) | Not merged |
| 54 | ADR-0001 scoped exception for porting `fundamental_engine` | merged | Owner-approved exception |
| 55 | Port relevance pre-filter | merged | On main |
| 56 | Port LLM providers (first attempt) | closed (conflict; superseded by #57) | Not merged |
| 34–47 | Phases 2–5 and M2–M10 work (Stage 2 batches, collection engine, financial import, PDF interface, owner document intake) | merged | [GIT]; detail in `docs/STATUS.md` |
| 1–33 | Phase 0–1 and early work | [REPORTED] in STATUS | Not rechecked |

### 1.3 News `main`
Head `f2af9ed73da21737a6e81fda5970e4246cb10506` (Merge PR #55) [GIT].

### 1.4 News branches with unmerged work (not PRs, or PR closed)
`feature/port-llm-providers` (7a1b2b99afa4, of closed #56), `feature/port-relevance-prefilter`, `chore/status-refresh-after-migration-recovery` (a8d51227047e, of closed #53), `feature/a2-migration-collision-remediation` (95b0b0e48270, merged in #52), `docs/adr-0008-fundamental-engine-port` (merged in #54), `ci-isolate-turso-tests`, `data-acquisition-*`, `phase-*`, `stage2-*`, `stage4-external-dispatch`, `stage5-quality-operations`, `spec-module-24`, `provider-assessment`, `psx-*-assessment`, `pypsx-capitalstake-assessment`, `calendar-official-psx-2026`, `adeerkhan-psx-data-assessment`, `docs-phase-1-merged`, `docs/collector-run-investigation`, `docs/psx-company-coverage`, `docs/record-credential-attempts`, `docs/source-access-scs-permission`, `fix-market-bookkeeping`, `guard-local-packages`, `migration-0009-*`, `migration-0010-market-ohlcv`. These are historical. Each must be checked for unique commits before deletion. Do not delete any in this handover.

## 2. Technical repository — `imranrazabozdar/PSX-INTELLIGENCE-NEW-2026`

### 2.1 PRs
| PR | Title | Head | Head SHA | State | Recommendation |
|---|---|---|---|---|---|
| 67 | Refuse the PSX-NEWS-INTELLIGENCE database in the technical engine | `feature/refuse-shared-news-database` | e5efbac03044 | open | Merge after review |
| 66 | Extraction quality: cross-source dedup, PSX entity resolution, gated content acquisition, evaluation (DO NOT MERGE YET) | `claude/ohlcv-data-fetch-pilot-xdxm94` | b81c26c93d62 | open | Preserve. Review and port the relevant pieces into news. Do not merge here |
| 65 | Candidate review workflow (migration 0011, review queue, confirmed apply) | `claude/ohlcv-data-fetch-pilot-xdxm94` | cd7540906190 | merged 2026-11-09 | Its migration 0011 must never reach the news DB |
| 64 | Relevance prefilter, Gemini and OpenRouter, full fallback cascade | same | 0779a6cae386 | merged 2026-11-09 | Ported (news PR #55 for the pre-filter) |
| 63 | Fundamental engine: baseline schema, LLM routing layer (Groq enabled), extraction paths, watchlist | same | 6c02b342c3e8 | merged 2026-11-09 | Keep in technical repo |
| 62 | Company master expansion: verified-only stub loader, Investify company-name capture | same | ce55b12d025b | merged 2026-11-09 | Historical writes to the news DB (incident) |
| 61 | Investify announcements pilot: parser, ingester, manual PDF vault | same | 7565398265ec | merged 2026-11-09 | Restricted source |
| 60 | OHLCV micro-batch pilot: SCS chart feed into market_bars | same | c956b2d484af | merged 2026-11-09 | Historical writes to the news DB (incident) |
| 59 | Patterns tab: presentation-only redesign for phone and desktop | `claude/11-stocks-forensics-report-3w23o7` | 07ed74dc4f7c | open | Preserve; owner review |
| 58 | Run Original Wyckoff 1.0 independently of suspended FIRE 1.0 | same branch | a71bb5982c15 | merged 2026-11-03 | Keep |
| 57 | Wyckoff 2.0 research section: timestamp, outdated warning, sector filter | same branch | 3fd80a157bd1 | merged 2026-11-03 | Keep |
| 56 | RESEARCH support-break study: methodological safeguards | same branch | 1c7da0f12a04 | merged 2026-11-03 | Keep |
| 34–55 | Earlier technical work | — | — | not read in this review | [UNKNOWN] detail |

Technical `main` head: `47e70e39baa1aaf2ab8013ec3496b281b2be25c3` (Merge PR #65).

### 2.2 Technical branches with unmerged work
`add-fire-engine-daily-batch-workflow-dispatch` (dacfd480cab0), `add-flat-base-phase1b-workflow-dispatch` (1c3ba36be25e), `add-scstrade-probe-workflow-dispatch` (4a9f37ba1f25), `add-vcp-phase1a-workflow-dispatch` (636e11497aaf), `ccr-7ad34b4c-1evx3e` (9169c9fceb8b), `claude/streamlit-tabs-data-refresh-wvk74c` (a6fc2d1d08e2). Their content was not reviewed in this package.

## 3. Rules for the next agent
- Do not merge any PR without owner approval.
- Do not close, delete or force-push any PR or branch to "clean up".
- Before any PR, run `python scripts/check_independence.py`, `ruff check .` and the test suite.
- Each PR must cite its branch, head SHA and CI result.

## 4. Handover package
Branch `docs/handover-package-2026-11-10`, based on news `main` `f2af9ed`. Commit and PR are recorded in the final report of this session.
