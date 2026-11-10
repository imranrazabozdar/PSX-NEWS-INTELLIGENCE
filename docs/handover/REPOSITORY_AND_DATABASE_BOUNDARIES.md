# Repository and database boundaries

Last verified: 2026-11-10. Labels: see README.md.

## 1. Rule (ADR-0001, news repo `docs/adr/0001-independence-from-technical-engine.md`) [SRC]
The projects must not share:
- a runtime database, database credentials or production tables;
- database migrations;
- runtime imports or application modules;
- secrets, write workflows or production data pipelines.
No project imports code from the other. A reusable idea may be re-implemented and tested in the destination repository. Nothing is copied wholesale.

## 2. Approved exception (scoped, time-limited) [SRC news ADR-0001]
The owner approved, on 2026-11-09, reading and copying **only** `fundamental_engine/` from the technical repository, to port fundamental and news-intelligence work into the news repository. It expires on completion or on 2026-12-09. It does not allow any other file, database or credential. Ported code passes the independence check and uses the news repository's migration numbering.

## 3. Database ownership
| Database | Owner | Status | Evidence |
|---|---|---|---|
| `psx-news-intelligence-imranrazabozdar` (Turso) | news project only | In use by both projects until separation. Technical writes into it are recorded (see incident register). | [PROD-RO] ledger check 2026-11-10; [REPORTED] PR bodies |
| Technical engine database | technical project only | NOT created. The technical engine still needs a separate database. | [UNKNOWN] whether the owner created one since 2026-11-10 |

### Enforced in code
- News `database/connection.py` on branch `feature/database-ownership` (PR #58): `TursoHTTPDatabase` refuses any host other than the owned production host unless `purpose` is `disposable` (host must start `psxni-migration-rehearsal-`) or `test` (host must start `psxni-test-`). Userinfo, query and fragment are refused. Status: branch, not merged. [TEST on branch, 948 passed].
- Technical `fundamental_engine/core/db_guard.py` and `backend/turso_db.py` on branch `feature/refuse-shared-news-database` (PR #67): refuse the news host at construction and at import. Status: branch, open. [TEST: `fundamental_engine` 242 passed, 4 skipped]

### On main, before those branches merge
`database/connection.py` on `main` does not yet enforce purpose. Merge PR #58 first.

## 4. Environment variable names (names only, no values)
News repo [SRC grep, names only]:
- Database: `PSXNI_TURSO_DATABASE_URL`, `PSXNI_TURSO_AUTH_TOKEN`, `PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL`, `PSXNI_DB_MAX_ROWS_READ`, `PSXNI_DB_MAX_ROWS_WRITTEN`, `PSXNI_DB_MAX_REQUESTS`.
- Disposable rehearsal only: `PSXNI_TURSO_DISPOSABLE_DATABASE_URL`, `PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN`, `PSXNI_A2_REHEARSAL_HOST_OVERRIDE` (exact host; never production).
- Tests: `PSXNI_TEST_TURSO_DATABASE_URL`, `PSXNI_TEST_TURSO_AUTH_TOKEN`, `PSXNI_TEST_TURSO_ALLOW_COMMITS`, `PSXNI_LIVE_SOURCE_TESTS`.
- LLM: `PSXNI_KILL_SWITCH`, `PSXNI_LLM_DAILY_COST_USD`, `PSXNI_LLM_*` limits; provider keys `PSXNI_GROQ_API_KEY`, `PSXNI_GEMINI_API_KEY`, `PSXNI_OPENROUTER_API_KEY` (branch only); `PSXNI_ANTHROPIC_API_KEY` (not connected).
- Sources and operations: `PSXNI_EIA_API_KEY`, `PSXNI_DISPATCH_TOKEN`, `PSXNI_TRIGGER`, `PSXNI_MARKET_*`, `PSXNI_DOCUMENT_VAULT`, `PSXNI_ENV`.
- Portfolio: `PSXNI_PORTFOLIO_DATABASE_URL`, `PSXNI_PORTFOLIO_AUTH_TOKEN` [SRC; their use not verified in this review].

Technical repo [SRC]: `LIBSQL_URL`, `LIBSQL_AUTH_TOKEN` (its Turso path); `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` appear in one diagnostic script that scrubs them. The technical repo's secrets were historically set to the news database. Their current value is [UNKNOWN].

## 5. Where credentials live
- GitHub Actions secrets in each repository (names only are visible in the UI).
- Claude environment network secrets ("Default" environment) used by sessions. Entries for the production host and rehearsal hosts were added during the 2026-11-09 work. Their deletion is [UNKNOWN] and is an owner action.
- Local `.env` files are ignored by Git (`.gitignore`) [SRC].
Never place a credential in chat, Git, a PR, a file in the repository or a database.

## 6. Owner actions for separation
See `OWNER_ACTIONS_REQUIRED.md`, items 1–4.
