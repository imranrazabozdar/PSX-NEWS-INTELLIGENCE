# Implementation status register

Statuses: NOT STARTED · IN PROGRESS · BLOCKED · IMPLEMENTED · TESTED (spec "Document status").
A feature is complete only when code **and** tests prove it. A page or placeholder doesn't count.

## Phases

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Specification and repository bootstrap | IMPLEMENTED, awaiting owner review | See Phase 0 checklist below |
| 1 | Data foundation (Turso, migrations, company master) | NOT STARTED (gated on Phase 0 approval) | |
| 2 | First source collectors | NOT STARTED | |
| 3 | Event extraction and verification | NOT STARTED | |
| 4 | Company exposure graph | NOT STARTED | |
| 5 | Impact analysis and Python calculations | NOT STARTED | |
| 6 | Streamlit MVP | NOT STARTED | |
| 7 | Scheduling and operations | NOT STARTED | |
| 8 | Corporate, policy and government modules | NOT STARTED | |
| 9 | Commodities, sectors, domestic/geopolitical risk | NOT STARTED | |
| 10 | Institutional and broker research | NOT STARTED | |
| 11 | YouTube and X collectors | NOT STARTED | |
| 12 | Valuation, scenario and opportunity radar | NOT STARTED | |
| 13 | Market event investigator, optional technical confirmation | NOT STARTED | |
| 14 | Backtesting, alerts and production audit | NOT STARTED | |

## Phase 0 checklist

| Deliverable | Location | Test / evidence | Status |
|---|---|---|---|
| README | `README.md` | | TESTED (reviewed) |
| Independence ADR (permanent) | `docs/adr/0001-independence-from-technical-engine.md` | | IMPLEMENTED |
| Stack ADR | `docs/adr/0002-technology-stack.md` | | IMPLEMENTED |
| Cross-project dependency checks | `scripts/check_independence.py` | `tests/test_independence.py` (11 tests), CI step | TESTED |
| Project instructions for Claude Code | `CLAUDE.md` | | IMPLEMENTED |
| `.gitignore` (secrets, DBs, dumps, media) | `.gitignore` | `tests/test_app_skeleton.py::test_no_secrets_files_committed` | TESTED |
| Config example (`PSXNI_` prefix only) | `.env.example`, `config/settings.py` | `test_settings_*`, `test_kill_switch` | TESTED |
| requirements / pyproject | `requirements*.txt`, `pyproject.toml` | Dependency rules in independence check | TESTED |
| Lint / test setup | `pyproject.toml` (ruff, pytest) | `ruff check .`, `pytest` | TESTED |
| CI workflow | `.github/workflows/ci.yml` | Runs on push / PR | IMPLEMENTED (verify first run on GitHub) |
| Scheduled-jobs workflow skeleton | `.github/workflows/scheduled-jobs.yml` | Manual-only; collects nothing | IMPLEMENTED |
| App skeleton starts | `app.py` | `test_app_starts_without_errors` (Streamlit AppTest) | TESTED |
| Secrets absent | Repo + full history | `gitleaks` job in CI | IMPLEMENTED (verify first run on GitHub) |
| No link to existing project | Whole repo | Independence check | TESTED |

## Requirements traceability (summary)

| Spec section | Requirement | Phase | Status |
|---|---|---|---|
| 1.3 | Separate repo / DB / Streamlit / secrets | 0–1 | Repo + secrets policy: TESTED. DB / Streamlit: NOT STARTED |
| 2.2 | Streamlit read-only; scheduled idempotent jobs; backfill + dry-run | 6–7 | NOT STARTED (workflow skeleton only) |
| 3.1–3.23 | 23 intelligence modules | 2–14 | NOT STARTED |
| 4 | X / YouTube watchlists, identity checks, relevance filter | 11 | NOT STARTED |
| 5 | Company master 30–50, aliases, history | 1 | NOT STARTED |
| 8 | Policy lifecycle stages | 1, 8 | NOT STARTED |
| 9 | Event-to-company impact engine | 3–5 | NOT STARTED |
| 10 | Score dimensions, valuation rules | 12 | NOT STARTED |
| 11 | 28-table schema and engineering rules | 1 | NOT STARTED |
| 12 | Dashboard pages (only for implemented modules) | 6+ | NOT STARTED |
| 16 | Testing framework | all | Phase 0 tests: TESTED |
| 17 | Cost controls, kill switch | 0, 2, 7 | Kill-switch setting: TESTED. Budgets: NOT STARTED |
| 18 | Governance and LLM safeguards | 3+ | NOT STARTED |
