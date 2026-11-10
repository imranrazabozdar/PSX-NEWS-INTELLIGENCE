# PSX handover package (2026-11-10)

Fourteen documents for a coding agent or developer who has never seen the earlier conversations.
Start with `MASTER_PROJECT_HANDOVER.md`, then `MASTER_PROMPT_FOR_NEXT_CODING_AGENT.md`.

| File | Use it for |
|---|---|
| MASTER_PROJECT_HANDOVER.md | Identity, boundaries, architecture, history, current state |
| CURRENT_IMPLEMENTATION_INVENTORY.md | Every module, its path, repo, branch status and tests |
| REPOSITORY_AND_DATABASE_BOUNDARIES.md | ADR-0001, database ownership, variable names, owner actions |
| MIGRATION_AND_DATABASE_RUNBOOK.md | Migration history, the version-11 collision, A2, approval gates |
| PR_BRANCH_AND_COMMIT_REGISTER.md | Open and merged PRs in both repositories, heads, CI |
| FINANCIAL_ENGINE_SPECIFICATION.md | Institutional fundamental analysis: what exists, what is missing |
| NEWS_MACRO_AND_EVENT_SPECIFICATION.md | Sources, events, exposure, evidence rules |
| LLM_AND_PROVIDER_RUNBOOK.md | Providers, enablement, budgets, kill switch |
| TESTING_AND_VALIDATION_REGISTER.md | What is tested, on what data, and what is not |
| SECURITY_AND_INCIDENT_REGISTER.md | Credentials, incidents, quarantine, corrective controls |
| OWNER_ACTIONS_REQUIRED.md | Only the decisions and actions that need the owner |
| NEXT_30_IMPLEMENTATION_TASKS.md | Ranked engineering tasks with acceptance criteria |
| MASTER_PROMPT_FOR_NEXT_CODING_AGENT.md | A self-contained prompt for another coding agent |
| HANDOVER_EXECUTIVE_SUMMARY.md | A short overview for a human developer |

## Verification labels used throughout
- **[SRC]** verified from source code at the stated commit.
- **[GIT]** verified from Git history or branch heads.
- **[CI]** verified from GitHub check runs at the time stated.
- **[TEST]** verified by running tests in this environment.
- **[PROD-RO]** verified by a read-only production query. Only one such check was made, on 2026-11-10, with the then-valid read token.
- **[REPORTED]** stated in an earlier PR body or conversation and not rechecked.
- **[UNKNOWN]** could not be verified. The reason is given.

Last verified: 2026-11-10. Snapshot commits: news `main` f2af9ed; technical `main` 47e70e3.
Credentials are named, never shown. The package contains no secret values, tokens or full connection strings.
