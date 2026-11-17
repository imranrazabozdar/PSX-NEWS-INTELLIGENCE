# Progress against the Consolidated Blueprint (blueprint dated 11 Nov 2026; this note 17 Nov 2026)

Read of `PSX_Institutional_Intelligence_Platform_Consolidated_Blueprint_and_History.docx`. The blueprint's own caveat
holds: its commit numbers and results are "as reported". "Verified live" below means checked in this session against
GitHub Actions and the psx-library Turso database; "per STATUS.md" means recorded in this repo and not re-run now.

## Where each blueprint layer stands
| Layer (blueprint section 2) | State on 17 Nov 2026 |
|---|---|
| Operational news intelligence | **Running** (verified live). Headline collector for Mettis, Express Tribune, Dawn, Business Recorder and Profit every 30 minutes around the clock, robots.txt checked, headline + date + link + short snippet only; one-month back-fill for Profit and Tribune; headlines to dated facts, daily rollup and signals run automatically with no model. Entity mapping to PSX tickers (alias file, 590 entities after the folds). Official PSX announcement feed and the PUCAR parser: offline-tested only, not deployed (per STATUS.md). |
| Financial archive and statement intelligence | **Built offline, not live** (per STATUS.md): PDF intake, statement reconciliation, KAM and note extraction, ratio layer, UBL/OGDC/LUCK validated; extraction coverage 3 of 108 watchlist companies at the 12 Nov measurement. Separate from this: the library now holds Investify's **derived** metrics (13k metrics, 417 companies); those are a third party's ratios, not reconciled filings, and must not be mixed with the archive's reconciled facts. |
| Technical intelligence | **Separate repository, not touched** (ADR-0001). The only access was a read-only look at the owner's request. Price and volume from Investify were deliberately not stored. |
| Macro and sector transmission | **Partial.** MACRO:PAKISTAN and 24 SECTOR entities hold dated facts from videos and news; sector for 562 companies now known (Investify profile). No transmission maps or sensitivities yet. The company exposure graph (phase 4) is tested on synthetic data and not operational (per STATUS.md). |
| Forecasting and valuation | Valuation and fundamentals modules exist offline (per STATUS.md); not fed with real data; phases 5 and 12 not started. |
| Research and decision support | **Dry-run council built** (17 Nov): importance rules, queue, caps, three lenses on free-tier models, read-only, no production storage. No theses or reports yet. |
| Streamlit | Offline pages exist (per STATUS.md); nothing yet for the library data (needs the owner's gate). |

## The brain (psx-library), verified live 17 Nov
46,376 dated facts across 914 entities: Nukta Business 13,977, Standard Capital 7,161, ARN videos 3,897+, Investify export
20,613 (fundamentals, announcements, profile), plus news-derived company, sector and macro facts; 537+ headlines; company
index applied; read/write economy pass done (an automatic news run reads about 6,100 rows, was 25,000).

## Governance rules (blueprint section 3): still held
No technical or financial-archive database touched; no paid model call (the council has no paid fallback); production writes
only after the owner's approval each time; no force-push or history rewrite; secrets never printed. PRs were merged by this
session under the owner's standing instruction, each only after all checks including CodeQL passed.

## Blueprint's open items (section 16), updated
| Item | Now |
|---|---|
| Live database identity and credential isolation for all three systems | Re-verified for psx-library only (guards refuse any other host; the council adds a table-signature check). The other two databases were not opened, by design. **Still open.** |
| Collision incident closure | STATUS.md records the A2 rehearsal as passed on 9 Nov. Not re-verified in production here. **Open.** |
| Financial archive disposable rehearsal | Not run (needs disposable credentials). **Open.** |
| UBL KAM extraction | Per STATUS.md addressed in the archive branch; not re-verified. |
| Real PDF acquisition and PSX feed, Termux end to end | Not done live. **Open.** |
| Three-model orchestration | Council wired to Groq, Gemini and OpenRouter free accounts; **connection unverified until the 10-headline run answers.** Role benchmarking not done. |
| Wyckoff edge | Not applicable here (technical repo). |
| Coverage measurement | Brain coverage is measurable by entity; archive coverage still 3 of 108. |

## What the blueprint does not know about (added since 11 Nov)
The library database as the working "brain" run entirely by GitHub Actions without Claude; the dated-fact model with source and
date on every row; the headline collector and its rules; the entity registry and folds; the council dry run; the read/write
budget design (`docs/ops/DB_BUDGET.md`).

## Recommended next steps (blueprint section 17 order)
1. Finish the council review: the 10-headline test (running) and the seven days of automatic dry runs; then decide on storage.
2. Read-only identity and schema inventory of psx-library, and a disposable-database rehearsal of the library migrations.
3. Bring the official PSX announcement feed in (the blueprint's most timely primary source), then PUCAR results as reconciled facts.
4. Feed reconciled annual-report facts for the priority companies into the brain, kept distinct from Investify's derived metrics.
5. Build the first sector transmission maps (oil, rates, FX, cement, power) on the stored facts.
6. Only then benchmark the three model roles, then forecasting and valuation.
