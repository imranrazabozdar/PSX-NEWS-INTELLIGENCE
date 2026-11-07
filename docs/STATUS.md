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
| README | `README.md` | Owner review | IMPLEMENTED |
| Independence ADR (permanent) | `docs/adr/0001-independence-from-technical-engine.md` | | IMPLEMENTED |
| Stack ADR | `docs/adr/0002-technology-stack.md` | | IMPLEMENTED |
| Cross-project dependency checks | `scripts/check_independence.py` (+ base-branch copy run on PRs), `.github/CODEOWNERS` | `tests/test_independence.py` (17 tests), CI step | TESTED |
| Installed-dependency source check | `scripts/check_installed_sources.py`, `pip check`, `pip-audit` on installed env + requirements | `tests/test_installed_sources.py`, CI step | TESTED |
| Sanitised specification (C1) | `docs/SPECIFICATION.md` | | IMPLEMENTED |
| Full traceability matrix | `docs/TRACEABILITY.md` | `tests/test_traceability.py` (every spec section traced) | TESTED |
| Owner decisions for future phases (guidance only) | `docs/adr/0003-owner-decisions-future-phases.md` | | IMPLEMENTED |
| Project instructions for Claude Code | `CLAUDE.md` | | IMPLEMENTED |
| `.gitignore` (secrets, DBs, dumps, media) | `.gitignore` | `tests/test_app_skeleton.py::test_no_secrets_files_committed` | TESTED |
| Config example (`PSXNI_` prefix only) | `.env.example`, `config/settings.py` | `test_settings_*`, `test_kill_switch` | TESTED |
| requirements / pyproject | `requirements*.txt`, `pyproject.toml` | Dependency rules in independence check | TESTED |
| Lint / test setup | `pyproject.toml` (ruff, pytest) | `ruff check .`, `pytest` | TESTED |
| CI workflow | `.github/workflows/ci.yml` | Runs on push / PR | IMPLEMENTED (verify first run on GitHub) |
| Scheduled-jobs workflow skeleton | `.github/workflows/scheduled-jobs.yml` | Manual-only; collects nothing | IMPLEMENTED |
| App skeleton starts | `app.py` | `test_app_starts_without_errors` (Streamlit AppTest) | TESTED |
| Secrets absent | Repo + full history | `gitleaks` full-history scan + planted-secret canary in CI | IMPLEMENTED (verify first run on GitHub) |
| No link to existing project | Whole repo | Independence check | TESTED |

## Requirements traceability

The full matrix, covering every section of the specification, is in [`TRACEABILITY.md`](TRACEABILITY.md).
