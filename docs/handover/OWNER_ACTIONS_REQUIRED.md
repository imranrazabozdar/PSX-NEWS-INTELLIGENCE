# Owner actions required

Last verified: 2026-11-10. Only actions that need you personally. Never paste a credential into chat or Git. Use the secure credential form, or GitHub's secret screen.

## A. Database separation (blocks clean operation)
1. **Create a separate Turso database for the technical engine.** Give it a name that does not start with `psx-news-intelligence`. Create a token scoped to that database only.
2. **Repoint the technical repository's GitHub secrets** (`LIBSQL_URL`, `LIBSQL_AUTH_TOKEN`) to that database. Confirm the old values are gone.
3. **Confirm the current production state with a fresh read-only token** (create it with `turso db tokens create psx-news-intelligence-imranrazabozdar --read-only --expiration 1h`, and send it through the secure form). This lets the next agent verify the row counts.

## B. Credential hygiene
4. **Delete the saved Turso entries in the shared Default environment's network secrets**, for the production host and for each rehearsal host. Confirm when done.
5. **Confirm the rehearsal database `a2-rehearsal-1109` is destroyed** (`turso db destroy a2-rehearsal-1109`). Earlier rehearsal databases were destroyed [REPORTED].
6. **Decide on the LLM provider keys in the shared environment.** Rotate them if they were exposed outside your control, and move them to a repository-specific environment.
7. **Remove stale allowlist hosts** from the Default environment: `dps.psx.com.pk`, `chart.scstrade.com`, `investify.pk`, `www.investify.pk`.

## C. Historical production data (decision, then approved remediation)
8. **Decide the disposition of technical-origin rows in the news database:**
   - `market_bars` rows from the SCS pilot (collector run 38);
   - Investify rows (run 39) and the name backfill (run 40);
   - the 16 stub companies and 32 aliases (run 41);
   - the 15 `llm_calls` rows and 15 extraction candidates.
   Options: keep and quarantine (the agent proposes read-time exclusion), or remove. Removal requires a verified backup with SHA-256, a disposable rehearsal, pre-flight and post-flight checks, and your approval ID. The agent will not do this without that.

## D. Pull request approvals (no merge without you)
9. **PR #57** (news): provider port. Merge-ready; CI green on its head.
10. **PRs #58–#63** (news): fix the secret-scan first (merge #57, then update from `main`). Then review and approve each.
11. **PR #67** (technical): the database guard. Approve or ask for changes.
12. **PR #66** (technical): extraction quality. Decide whether its evaluation, dedup and entity-resolution work should be ported into the news repository under the exception. Do not merge it in the technical repository.
13. **PR #59** (technical): Patterns tab redesign. Keep open or merge, your decision.
14. **PRs #48–#51** (news): OGDC accounting and coverage work. Review and decide. These hold unique work.
15. **This handover PR** (news): review the 15 documents and approve.

## E. Provider approvals (only if you want live extraction)
16. **Terms review** for each provider you want to enable, for this project. Record the date in the config yourself (`terms_reviewed_utc`). The agent will not set it.
17. **Confirm model ids** you accept, after a test call that you approve.
18. **Approve any paid usage** in writing. No paid API is used without it.

## F. Source and document supply
19. **Supply an actual PSX annual report** for the first end-to-end demonstration, preferably OGDC (FY2026 or the latest). Use the owner document intake with the rights attestation. The agent will not fetch PSX documents itself.
20. **Source permissions:** any change to a source's retention mode (for example to allow full-text retrieval) is your decision and must be recorded in the permission log.
21. **X and YouTube:** confirm the account identities and access rules before any collection (spec Appendix A).

## G. Production change approvals (future)
22. Any migration against production: needs the runbook's backup, rehearsal and your approval ID.
23. Activation of any scheduled job or module against production: needs your approval.
24. Any change to shared secrets: needs your confirmation.

## H. Decisions with deadlines
25. **The scoped ADR-0001 port exception expires on 2026-12-09** or when the port completes. Extend, end or let it lapse.
26. **Thresholds (U9):** set the bands for fundamental dimensions and the valuation assumptions you accept.
