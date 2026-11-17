# ADR-0008: Read-only link from the technical engine's signals to this project

* **Status:** PROPOSED. Not in force until the owner signs the block at the end. Until then ADR-0001 applies in full.
* **Date proposed:** 2026-11-17
* **Supersedes (in part, once signed):** the "Data exchange: none" and "Database" rows of ADR-0001, for the single interface below only.

## Context
The owner's technical engine (separate repository, database and app) already computes technical modules: Wyckoff
accumulation, volatility intelligence, chart and candlestick patterns, the FIRE engine, market regime and more.
This project holds news, results, announcements and (planned) prices. The owner wants the technical engine to keep
running exactly as it is, and this project to read its outputs so a company's news, price move and technical state
can be shown together and so "why did it move" can use technical evidence.

## Decision (applies only once signed)
One read-only, one-way link: this project may READ a small allowlist of the technical engine's output tables or views.
Nothing flows the other way.

| Area | Rule |
|---|---|
| Direction | Read only. This project never writes to, alters, or triggers anything in the technical engine (no DDL, no inserts, no workflow dispatch, no commits). |
| Credential | A NEW read-only database token the owner creates for this purpose (scoped to read, ideally to named tables or views). Stored here only as `PSXNI_TECH_LINK_URL` and `PSXNI_TECH_LINK_TOKEN`. No existing technical-engine secret is ever reused. The owner can revoke it at any time. |
| Allowlist | Only the tables or views the owner names in the Schedule below. Anything else is refused in code. The list is part of this ADR and changes only by amendment. |
| Access code | One module, `engines/technical_link.py`, using the same read-only wrapper as the council dry run (only SELECT/WITH pass). It fails closed if the database identity is not the one recorded in the Schedule or an allowlisted object is missing. |
| No code reuse | Nothing is imported, copied, vendored or executed from the technical engine's repository. This project reads its data only and does not open its repository. Indicator maths is not reimplemented from it. |
| Load limits | Per-run caps on rows read and requests, small daily cadence, off-peak. A failure here never affects the technical engine, and the technical engine's availability never blocks this project's other jobs. |
| What is stored | Dated facts in this project's own `research_fact`: symbol, scan date, module, signal or class, score, direction, stated components, plus the source name "Technical engine (read-only link)". Every row keeps the technical engine's own scan date so stale scans (for example a scan two weeks old) are never shown as current. |
| Language | Pattern, class and score only. Action words such as BUY, SELL or WAIT are never stored or displayed here. Scores are heuristics, not probabilities, and are labelled so. |
| Gaps | A symbol or module the engine does not cover stays unknown, never neutral or zero. |
| Rule check | `scripts/check_independence.py` gets exactly two narrow allowances, added in the same pull request that implements the link: the two secret names above and the single module name. Its other rules, and the base-branch guard, stay unchanged. |
| Review and expiry | Reviewed on 2027-02-17 or after any schema change in the technical engine. Ends on revocation of the token. |

## Schedule A: allowlisted objects (owner to complete before signing)
The author of this ADR has not opened the technical engine and does not know its schema. The owner lists here, for each
object: name, one-line meaning, key columns (symbol, date), and how often it refreshes.

| Object (table or view) | Module / meaning | Key columns | Refresh | Allowed |
|---|---|---|---|---|
| (owner to fill) | e.g. Wyckoff accumulation scan | symbol, scan_date, class, score | daily | |
| (owner to fill) | e.g. volatility intelligence | symbol, session_date, stage, score | daily | |
| (owner to fill) | e.g. chart and candlestick patterns | symbol, signal_date, pattern, direction | daily | |
| (owner to fill) | e.g. FIRE engine setups | symbol, scan_date, score | daily | |
| (owner to fill) | OHLCV daily bars, if it is to be read here | symbol, date, o/h/l/c/volume | daily | |

Database identity (host name only, no secrets): (owner to fill).

## Consequences
* The two systems become coupled by one schema: a column rename in the technical engine breaks the link here. The link must fail visibly, and does.
* Reads cost the technical engine's Turso read quota. The caps above keep that small and the owner may lower them.
* The technical engine runs unchanged. The owner remains its only operator.
* If the owner prefers no live link, the file-export route (owner exports tables, a converter here loads them) needs no ADR and remains available.

## Implementation (after signing, one phase, one pull request)
1. Owner completes Schedule A and creates the read-only token and secrets.
2. Dry run: read-only identity check, row counts and sample rows printed, nothing stored.
3. Owner reviews, then the converter loads dated facts with source provenance.
4. Tests: allowlist enforcement, read-only enforcement, identity mismatch fails closed, stale-scan labelling, no action words, caps.

## Owner sign-off
- [ ] I have read this ADR and authorise exactly the read-only link described, limited to Schedule A.

Owner: ______________________  Date: ____________
