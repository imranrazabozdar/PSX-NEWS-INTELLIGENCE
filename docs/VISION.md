# PSX Fundamental & News Intelligence — the owner's vision

Recorded 14 Nov 2026 from the owner's own statement. Every phase is checked against this document.

## 1. The core idea
See an event — a policy change, a court ruling, an oil spike, a political shift, a sudden rule change, a
sector-specific development, a global crash — and know straight away which PSX stocks it affects, how strongly,
and why. Examples: a high-profile political release, a refinery policy, LPG prices, housing-loan rules, a global
crash. Each case gives the affected stocks ranked by how hard they would be hit, with the reasoning shown. The
system should notice what others miss, through careful, spotless analysis.

## 2. Understanding every company, at two depths
- **Baseline for all ~108 companies**, built automatically from Investify data: fundamentals, announcements,
  insider activity, profile and peers.
- **Deep dive for priority names**, built from annual reports and research (the HUBC dossier is the pattern):
  statements, macro, analysts, credit and consensus, all cross-checked.
- Over time the system learns each company's exposures from the news, so baseline names get more detailed too.

## 3. A brain, not a pile of PDFs
Turso is not clogged with documents. The system keeps distilled knowledge: sourced, dated facts, exposures,
baselines and story threads. It reasons over these and gets sharper as data arrives. `research_fact` is the
first piece.

## 4. The layers of analysis
- **Macro:** rates, FX reserves, oil, budgets, commodities, sentiment — each mapped to the companies it affects.
- **Market flow:** FIPI/LIPI — what foreign and local money is doing; a reality check against the story.
- **Event transmission:** event → exposure → affected stocks, ranked by intensity.
- **Composite scoring:** e.g. bad results + weak sector + foreign selling + global pressure; flags divergences
  where fundamentals and the market disagree.
- **Scenarios:** honest ranges of outcomes. Never point predictions. Never buy or sell instructions.

## 5. What the owner sees
A private dashboard of ranked lists — hot stocks, names to research, names to be careful with — every entry with
its reasoning, so the owner judges for themself.

## 6. How it must behave
- **Good citizen toward Investify:** one request at a time, trading hours only, stop on any pushback. A one-time
  weekend run for testing or backfill only with Investify's explicit permission.
- **Independent** of the owner's technical engine, and separate from production databases (ADR-0001).
- **Honest:** no invented data, no fake numbers, nothing marked done without passing tests.
- **Runs by itself:** fills in the data over weeks without the owner or the assistant stepping in.

## Status against the vision (14 Nov 2026)
| Piece | State |
|---|---|
| Baseline: fundamentals, announcements (incl. insider items), profile, peers | Running: autonomous tick, 432 resources (108 × 4) at up to 12/day, about 36 trading days |
| Deep dive | Pattern proven on HUBC (23 rows) |
| Brain (`research_fact`) | Live: HUBC research + MEBL fundamentals |
| Exposures | Engines built and tested offline; not yet fed by live data |
| Event transmission (T1–T9) | Built and tested offline; not yet connected to live events |
| Story threads | `engines/notable_events.py` exists |
| Macro | Planned (`docs/plans/phase2_macro.md`); waiting on owner source decisions |
| Market flow (FIPI/LIPI) | Gap: no source or terms recorded |
| Composite scoring, divergences, scenarios | Not built |
| Ranked dashboard | Only for modules that are implemented and tested |

## Build order
1. Baseline complete (announcements added to the tick). 2. Exposures fed by live data. 3. Event transmission end
to end (HUBC first). 4. Macro layer. 5. FIPI/LIPI after a source and terms assessment. 6. Composite scoring,
divergences, scenarios. 7. Ranked dashboard lists, each after its module is real.
