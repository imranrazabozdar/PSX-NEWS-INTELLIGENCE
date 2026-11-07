# PSX Fundamental & News Intelligence Engine

A personal, evidence-first research terminal for the Pakistan Stock Exchange (PSX). It turns
public and authorised information (news, disclosures, policy, macro, sector, commodity,
institutional and social/media sources) into company-specific intelligence. The goal is to
show what happened, which companies are actually exposed and how, what the financial effect
could be, and whether the market has already reacted.

> **Not investment advice.** The system ranks research priority. It never places trades,
> issues buy/sell instructions or guarantees price outcomes.

## Independence from the technical engine (permanent requirement)

This project is **completely separate** from the owner's existing technical intelligence engine
(`psx-intelligence-new-2026`). It doesn't access, modify, import, connect to, or reuse anything
from that project: no code, database, credentials, GitHub Actions, dependencies or deployment.
It has its own repository, its own Turso database, its own Streamlit deployment and its own
`PSXNI_`-prefixed secrets.

* Decision record: [`docs/adr/0001-independence-from-technical-engine.md`](docs/adr/0001-independence-from-technical-engine.md)
* Automated enforcement: [`scripts/check_independence.py`](scripts/check_independence.py), which runs in CI on every push and pull request.

Any future integration needs the owner's explicit authorisation and a new ADR.

## Current status

**Phase 0 (repository bootstrap) is implemented and awaiting review.** No database is connected
and no data is collected yet. See [`docs/STATUS.md`](docs/STATUS.md) for the status register
and traceability matrix.

## Architecture (target)

```
Sources → collectors (GitHub Actions, scheduled) → normalise / dedupe / relevance
       → event extraction → verification → company exposure mapping
       → economic transmission → calculations / scenarios → market reaction
       → research ranking → Streamlit dashboard → point-in-time backtesting
                      all persisted in a dedicated Turso database
```

* [`docs/adr/0002-technology-stack.md`](docs/adr/0002-technology-stack.md) covers the stack and runtime separation.
* Phases follow spec section 14. Each phase is built, tested and approved before the next one starts.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # never commit .env

python scripts/check_independence.py   # cross-project dependency guard
ruff check .                           # lint
pytest                                 # tests
streamlit run app.py                   # app skeleton
```

## Repository layout (Phase 0)

```
app.py                      Streamlit entry point (status only, no data)
config/settings.py          PSXNI_-prefixed settings, kill switch
scripts/check_independence.py
tests/                      independence + app skeleton tests
docs/adr/                   architecture decision records
docs/STATUS.md              status register and traceability
.github/workflows/          CI + scheduled-jobs skeleton (manual only)
```

Further directories (`collectors/`, `engines/`, `database/`, `pages/`, ...) are added only in
the phase that implements them.

## Security

* Secrets live only in GitHub Actions Secrets, Streamlit Secrets or a local `.env`, which is git-ignored.
* CI scans the full git history with gitleaks and audits dependencies with pip-audit.
* This repository is public. It must never contain database dumps, backups or private research notes.
