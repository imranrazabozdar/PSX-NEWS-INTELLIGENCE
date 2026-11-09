# Project instructions (PSX Fundamental & News Intelligence)

## Permanent rule: independence (ADR-0001)
This project is completely independent of the owner's existing technical engine. Never access,
open, clone, read, modify, import, connect to, or reuse anything from that project. That includes
its code, database, credentials, GitHub Actions, dependencies and deployment. All secrets use
the `PSXNI_` prefix. `python scripts/check_independence.py` must pass before every commit.
See `docs/adr/0001-independence-from-technical-engine.md`. The only active exception is the owner-approved, scoped port of
`fundamental_engine/` recorded there (expires on completion or 2026-12-09); nothing else in that project may be touched.

## How to work
- Build one approved phase at a time (spec section 14). Stop at each acceptance gate and wait for the
  owner's approval before starting the next phase.
- Keep `docs/STATUS.md` up to date: NOT STARTED / IN PROGRESS / BLOCKED / IMPLEMENTED / TESTED.
  Never mark something complete without code and passing tests.
- Never invent data, source access, exposures, prices, consensus or estimates. No buy/sell instructions.
- Only build dashboard pages for modules that are actually implemented. No fake placeholder numbers.
- Before committing, run: `python scripts/check_independence.py && ruff check . && pytest`.
