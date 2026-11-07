# ADR-0002: Technology stack and runtime separation

* **Status:** Accepted for Phase 0. The database parts take effect in Phase 1, after approval.
* **Date:** 2026-11-07
* **Spec reference:** sections 1.3, 2.2, 11, 13, 17

## Decision

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Dashboard | Streamlit, read-oriented. It never polls sources or runs collection loops. |
| Scheduled processing | GitHub Actions workflows, one per source family. Incremental, idempotent, logged, with a `dry_run` option. |
| Database | Turso (libSQL, SQLite-compatible) in production. A local SQLite file or `:memory:` for development and tests. **Not connected in Phase 0.** |
| Configuration | Only `PSXNI_*` environment variables (`config/settings.py`). Local `.env` is git-ignored. Production uses GitHub Actions Secrets and Streamlit Secrets. |
| Calculations | Deterministic Python only. LLM output is schema-validated and never the sole source of a number, ticker or verification (spec section 18). |
| Quality gates | `ruff` lint, `pytest`, the independence check (ADR-0001), `pip-audit`, and a `gitleaks` scan of the full git history. |
| Cost control | A global kill switch (`PSXNI_KILL_SWITCH`), plus per-source enable flags and budgets from Phase 2. |

## Repository layout

The repository follows spec section 13. Directories (`collectors/`, `engines/`, `database/`,
`models/`, `prompts/`, `pages/`) are only created when their phase is implemented, so the
tree never suggests unfinished functionality exists.
