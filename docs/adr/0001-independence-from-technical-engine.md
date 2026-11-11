# ADR-0001: Permanent independence from the existing technical engine

* **Status:** Accepted (permanent architectural requirement); amended 2026-11-08 to record one expired, one-time audit exception, and 2026-11-09 to record one scoped, time-limited porting exception
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

## Recorded exception: one-time read-only audit (2026-11-08, expired)

The rule above was not changed. This section records the only exception to it so far.

* **What:** a single read-only inspection of the technical engine's local checkout
  (`/home/user/PSX-INTELLIGENCE-NEW-2026`, repository `imranrazabozdar/psx-intelligence-new-2026`)
  at commit `850aef5`.
* **Authorised by:** the owner, explicitly and for this one inspection only, on 2026-11-08.
* **Purpose:** to find out how the technical engine obtains data without paid subscriptions,
  and whether any of those methods could be implemented **independently and lawfully** in this
  project. The findings were reported to the owner in that session; nothing was recorded in
  this repository.
* **Restrictions observed:**
  * no files were modified and no code was copied or adapted;
  * no scripts, collectors or workflows were run, and no network requests were made;
  * no credentials were accessed: only the names of the GitHub secrets were noted, never their values;
  * no runtime, build or data dependency between the projects was created.
* **Status: expired.** The exception covered that single inspection only. It grants no
  continuing access and is not a precedent. Any future inspection of the technical engine
  needs fresh, explicit, task-specific authorisation from the owner, recorded the same way
  here.
* **Unchanged:** every rule in the Decision table still applies in full. That includes no
  shared code, databases, credentials, workflows, deployments or data exchange; no copying or
  adapting of the technical engine's implementation; and no access to its repository or files
  without that fresh authorisation.

  The audit itself also ruled out reproducing the technical engine's methods that rely on
  scraping, undocumented endpoints, spoofed browser headers or bypassing access controls. No
  data source may be activated here without documented permission and the owner's approval.

## Recorded exception: scoped port of `fundamental_engine/` (2026-11-09, active until completion or 2026-12-09)

The rule above was not changed. This section records a second, narrow exception.

* **What:** reading and copying the files under `fundamental_engine/` in the technical engine's repository
  (`imranrazabozdar/psx-intelligence-new-2026`, local checkout, commit `b81c26c`, the head of its open pull request #66).
  That directory holds fundamental and news-intelligence work (LLM provider routing, relevance pre-filter, extraction
  with grounded quotes, review workflow, deduplication, extraction evaluation) that was built in the wrong repository.
* **Authorised by:** the owner, explicitly, on 2026-11-09 ("Go with option 1"), after the options and the conflict with this ADR
  were put to them.
* **Purpose:** to move that fundamental and news-intelligence work into this project, where it belongs, instead of rebuilding it.
* **Scope (everything else stays forbidden):**
  * only `fundamental_engine/` may be read or copied. Nothing else in that repository may be opened: no technical-analysis code,
    scripts, workflows, data, databases, credentials or secrets;
  * copied code is merged into this project's own modules and conventions, one reviewed pull request per piece, not as a
    second package. Its own copies of database, migration and configuration code are not ported: this project's
    `database/` and migration runner are used;
  * ported files must pass `scripts/check_independence.py` unchanged: no reference to the technical engine, no `sys.path`
    changes, no undeclared dependencies, secrets only with the `PSXNI_` prefix;
  * no runtime, build, data or credential dependency between the projects is created, and nothing is imported from it;
  * migrations for the ported work are written fresh in this project's numbering after `0014`. The technical engine's
    own `0011_extraction_reviews` and its baseline snapshot are not copied;
  * source governance is unchanged: sources stay `metadata_only` unless the owner records otherwise.
* **Status: active, and limited.** It ends when the last ported piece is merged or on 2026-12-09, whichever is first, and it
  is not a precedent. Any further access needs new explicit owner authorisation, recorded here.
* **Unchanged:** every rule in the Decision table still applies in full. No migration is applied to production, and no module is
  activated, without the owner's separate approval under `docs/OPERATIONS_RUNBOOK.md`.

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
  for this project's work. The exceptions so far are the expired one-time audit and the scoped port of
  `fundamental_engine/` recorded above; any further access needs new explicit owner authorisation. `CLAUDE.md` repeats this rule for Claude Code sessions.

## Addendum (2026-11-11): scoped name-only watchlist, owner-authorized

- **What was authorized:** a single read-only use of the company names (symbol, name, sector only) of the
  technical project, pulled externally by the owner and supplied to this repository as the file
  `psx_final_watchlist.csv` (sha256 `9ce6a97d26948ff6f47ff23695359d0dc15e710199eab8a6c0bc9b22e7126cdf`, 96 rows).
- **What was imported:** only that file's rows, merged with `database/seed/companies.json` and deduplicated by
  symbol, case-insensitively, into `config/coverage_watchlist.json`. No code, data other than the three fields,
  database, credential, dependency or workflow of the technical project was imported, and no runtime link exists.
  Nothing in this repository calls or depends on the technical project.
- **Read attempts disclosed:** before the owner supplied the file, this session attached the technical project
  read-only and made two metadata requests (a file read and a branch listing). Both returned nothing (the
  repository's default branch does not exist and it has no branches). No clone was made, no file was read, and
  the project's instructions were not loaded into the session. The attachment was not removed by this change.
- **Unverified entries:** `ECPL` (already unverified in the owner file) and `SNGPL` (requested by the owner, absent
  from the file; `SNGP` is in the file and may be the same company). Neither is merged or guessed; both await owner
  verification and are listed in `config/coverage_watchlist.json`.
- **Owner decisions outstanding:** FFBL is a delisted seed company included in the union; the scope of delisted
  companies is for the owner.
