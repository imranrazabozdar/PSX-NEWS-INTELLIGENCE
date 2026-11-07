# ADR-0001: Permanent independence from the existing technical engine

* **Status:** Accepted (permanent architectural requirement)
* **Date:** 2026-11-07
* **Spec reference:** Master Implementation Specification v2.0, sections 1.2, 1.3, 3.18, 14 (Phase 0) and 20

## Context

The owner has an existing PSX technical intelligence engine in the GitHub repository
`imranrazabozdar/psx-intelligence-new-2026`. That project has its own code, database,
credentials, GitHub Actions and deployments.

This project, the PSX Fundamental & News Intelligence Engine (`psx-news-intelligence`),
does fundamental, news, policy, macro, sector, commodity, institutional and social/media
research. It is meant to complement the technical engine, but the specification requires
that it be built, run and deployed **completely independently** of it.

## Decision

This project must never access, modify, import, connect to, or reuse anything from the
technical engine. That covers:

| Area | Rule |
|---|---|
| Code | No imports, vendored copies, submodules, symlinks, `sys.path`/`PYTHONPATH` tricks, or copy-pasted modules from the technical engine. |
| Dependencies | Third-party packages come only from PyPI and are declared in `pyproject.toml` / `requirements*.txt`. No VCS, URL, local-path or custom-index installs. |
| Database | A separate Turso account and database. The technical engine's database, tables, files, exports and connection strings are never read or written. |
| Credentials | All secrets for this project use the `PSXNI_` prefix and are created fresh for this project. No credential, token or API key from the technical engine is reused, even if it would work. |
| GitHub Actions | Workflows check out only this repository, use only allowlisted action owners, never call or trigger the other repository's workflows, and read only `PSXNI_*` secrets (plus the automatic `GITHUB_TOKEN`). |
| Deployment | A separate Streamlit deployment with its own secrets. No shared app, domain, tunnel, container or server. |
| Data exchange | None. No API calls, file drops, webhooks or shared storage between the projects. |
| Technical context (spec section 3.18) | Any technical indicators used here are computed independently or entered manually. |

**Integration is out of scope by default.** It may be considered only if the owner
explicitly authorises a specific integration later. That would require a new ADR that
supersedes the relevant parts of this one.

## Enforcement

`scripts/check_independence.py` runs in CI on every push and pull request (`.github/workflows/ci.yml`),
and as a test (`tests/test_independence.py`). The build fails if any of these are found:

1. The technical engine's repository name, in any spelling, in a file outside the small
   allowlist of documents that describe this separation.
2. Imports of the technical engine's top-level modules (`fire_engine`, `backend`, `analysis`,
   `android`, `streamlit_app`, `wyckoff2_ui`, `vol_engine_ui`), or of any module that isn't the
   standard library, a local package, or a reviewed declared dependency.
3. `sys.path` manipulation, or `PYTHONPATH` set in a workflow.
4. Dependencies installed from a URL, VCS, local path or extra package index.
5. Workflows that check out another repository, use a non-allowlisted action owner, or read
   a secret without the `PSXNI_` prefix.
6. Git submodules.
7. Dynamic imports (`importlib.import_module`, `__import__`) of non-allowed modules, or with
   non-literal names; loading code from file paths (`runpy.run_path`, `spec_from_file_location`,
   `SourceFileLoader`, `site.addsitedir`); cloning or fetching code from other repositories
   (`git clone`, `gh repo clone`, other repos' GitHub URLs) in code, scripts or workflows; and
   workflow `pip install` commands that don't install from `requirements*.txt`.

### Protection against weakening the guard

* **Base-branch guard:** on every pull request, CI also runs the copy of
  `scripts/check_independence.py` from the target (base) branch against the PR's files. A PR
  that edits the rules to let a violation through still fails under the unmodified rules.
* **Policy floor test:** `tests/test_independence.py::test_policy_floor_cannot_be_silently_weakened`
  pins the minimum forbidden tokens, modules, allowed action owners, secret prefix and allowlist.
* **CODEOWNERS:** the guard, CI, ADRs and dependency files belong to the owner. To make this
  binding, enable branch protection on `main` with "Require status checks (CI)" and
  "Require review from Code Owners". That's a repository setting only the owner can turn on.
* **Installed environment check:** `scripts/check_installed_sources.py` fails CI if any installed
  package came from a VCS, URL, local directory or editable checkout, or if a declared dependency
  is missing. `pip-audit` audits the installed environment as well as `requirements.txt`.

Adding a new third-party dependency requires adding it to `THIRD_PARTY_IMPORTS` in the
check script. That forces a deliberate review of each one.

## Consequences

* Some utility code may be written again here rather than reused. That's accepted.
* Credentials and quotas (Turso, LLM, YouTube, X) are paid for and tracked separately.
* A failure, outage or schema change in either project can't affect the other.
* Contributors, including AI coding agents, must not open the technical engine's repository
  for this project's work. `CLAUDE.md` repeats this rule for Claude Code sessions.
