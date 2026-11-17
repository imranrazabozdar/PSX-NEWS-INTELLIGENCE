# PSX News Intelligence Council V1 (dry-run stage)

**Status: dry run only. No analytical result is written to any production table.** Production storage stays off until
the owner has reviewed the 10-headline test and the seven-day results and approves it in writing.

Files: `engines/news_importance.py` (rules, de-duplication, priority), `engines/council_ledger.py` (caps, queue, call
log), `engines/council_news.py` (runner, models, records, report), `scripts/council_news_dryrun.py` (CLI),
`.github/workflows/council_news_dryrun.yml` (automatic + on demand).

## Limits
- At most **6 council runs per Pakistan-local day** (UTC+5, no daylight saving) and **2 per collector execution**.
- One assessment per **event version**. The event id is stable as related headlines arrive; the version changes only
  when the story changes (a new figure, or a different set of rules applies).
- An important event over a cap **stays queued** (highest priority first, then oldest). A failed run is retried by a
  later execution and after 3 attempts is marked `needs_review`; it is never dropped. Every started run is charged to
  the caps, success or not, so an outage cannot burn quota in a loop.
- Individual LLM calls are logged (vendor, account, model, outcome, time, tokens) and each vendor account's quota is
  computed from those records (`engines/llm_quota` limits), separately from the run caps.
- Budget changes are atomic: each takes an exclusive file lock, re-reads the ledger and replaces it atomically.

## The seven rules (all deterministic; no model decides importance)
| # | Rule | How it is detected |
|---|---|---|
| 1 | Company results, earnings, payouts | a listed company named in the headline plus profit/earnings/EPS/results or dividend/payout words ("sales tax" is not results) |
| 2 | SBP rates, FX, fiscal policy, inflation, energy, major index moves | the library's macro topics (rates, fx, fiscal, inflation, energy, power) with a Pakistan context; fiscal needs a fiscal instrument (budget, FBR, levy...), a company in the headline needs a macro actor (SBP, govt, OGRA...), an index move counts only at 500+ points or 1%+ (size not stated = not flagged) |
| 3 | Unusual company news concentration | share of tracked news in the last 7 days at least 2x the company's own 28-day baseline (`news_rollup.signals`); baseline is **unknown** until 21 days of history |
| 4 | 3+ distinct headlines on one company in one day | counted after de-duplication, per Pakistan-local day |
| 5 | Policy, IMF, regulatory, geopolitical | policy/regulatory terms (IMF, budget, FBR, tariff, OGRA, NEPRA, SECP, cabinet, privatisation, bans...) with a Pakistan context; geopolitical terms (war, ceasefire, sanctions, Iran, Hormuz...) |
| 6 | Unusual sector-wide concentration | the same share test on `SECTOR:*` entities |
| 7 | Material adverse company development | litigation, court orders/fines, shutdowns, halts, defaults, delisting, fraud, cancelled contracts, force majeure, with a named company or sector |

Company names are removed from the headline before the macro and policy words are tested (so "Punjab Oil Mills" is
not oil news). Headlines are clustered by content words (cut/reduce unified, numbers kept) within 48 hours; two
different companies are never merged ("HBL profit rises 20%" vs "MCB profit rises 20%"); a bridging headline merges
two events.

## Priority, reliability and provenance
Base score by strongest rule (7: 100, 1: 90, 2: 80, 5: 70, 3: 60, 6: 55, 4: 50), plus a little for extra rules, the
most trusted outlet, corroboration by more outlets, and recency. Starting source reliability (owner-editable in
`SOURCE_RELIABILITY`): Dawn Business 0.90, Business Recorder 0.88, Express Tribune Business 0.85, Mettis 0.80, Profit
0.80. An outlet not in the table is **unknown (null)**. Every record lists each outlet's link, time and reliability.

## Models (existing architecture, free tier only)
The three lenses (news, financial, macro) and the synthesis are the existing council (`engines/analyst_council`),
each on its own preferred free-tier account (Groq, then Gemini, then OpenRouter), quota-guarded from the ledger.
There is **no paid fallback**: with no key the council is not connected and the record says so (the Claude stub is
never used); OpenRouter is used only with a `:free` model. A record reports what was **configured** and what
actually **answered**, and states "n of 3 lenses answered, on k distinct verified model(s)". Three lenses on one model
are reported as one model.

## The record (one JSON line per council run, `COUNCIL_DRYRUN_RECORD` in the Actions log)
Event (key, id, version, headline, outlets with provenance), classification (rules with detail, priority, companies,
sectors), time tags (Pakistan day/time, weekend, recorded holiday, after hours), pack size and evidence ids, models
(configured, answered, per-lens provider/model/prompt, claim), assessment (per company and sector: each lens's
direction benefit/suffer/neutral/unclear, magnitude, timing, confidence, reason, evidence ids, and a consensus; a
sector no lens addressed is `unknown`), model disagreement (computed conflicts, differing views, failed lenses,
dropped assessments), cost (calls by outcome and account, tokens, model time; tokens are null when the vendor sent no
usage figure and USD is null: not metered, free tier), errors, start and end time. Missing values are null/"unknown".

## Safety and database separation
- Work is confined to this repository; only psx-library is opened, through `library_db` (its target guard refuses any
  other host), and only if it has `news_item`, `news_progress` and `research_fact` and **none** of the price-archive
  tables. Anything else stops the run (fail closed).
- The connection is `ReadOnlyDB`: any statement that is not SELECT/WITH, and every batch, raises. No DDL, no writes,
  no migrations, no secret changes. A test scans the dry-run code for write statements.
- State (budget, queue, call log) lives in a JSON ledger carried between runs by the Actions cache.

## Running it
- Automatic: after every "News collector" run (every 30 minutes, around the clock: weekends, holidays, after hours
  included). Log markers: `COUNCIL_DRYRUN_RECORD {...}` and `COUNCIL_DRYRUN_EXECUTION {...}`; a summary table is added
  to the run page; `.council_dryrun/` (ledger, `records.jsonl`) is uploaded as an artifact for 30 days.
- The 10-real-headline review: Actions, "Council news dry run", Run workflow, mode `ten`. Output:
  `ten_headline_review.md` and `.jsonl` (in the run summary and the artifact). It picks the best flagged event for each
  rule that fired, then the next highest priority, then up to 3 unflagged **controls** that name a company.
- The seven-day report: mode `report`, or the last step of every automatic run
  (`python -m scripts.council_news_dryrun --mode report`).

## Known limits and unresolved risks
1. Rules 3 and 6 need 21 days of history; until then their baseline is reported unknown and they cannot fire.
2. De-duplication is lexical, not semantic: a paraphrase with few shared words (for example "State Bank forecasts" vs
   "SBP projects") stays two events, which can double a run on one story.
3. Rule 5's geopolitical words are broad (it will flag world news that moves markets); review the 10 headlines.
4. The source reliability numbers are starting values chosen by the build, not measured.
5. The ledger lives in the Actions cache. If GitHub evicts it (7 days unused, or its size limit), the day's counts
   restart and the 6-a-day cap could be exceeded once. Production activation would move this state into the database,
   which needs the owner's approval of a migration.
6. Free-tier quota limits in `engines/llm_quota` are placeholders to confirm in each vendor's dashboard.
7. Holidays: only those recorded in `config/psx_calendar.json` are known; others show as normal weekdays.
8. GitHub starts some runs late (seen on 16 Nov); a late run simply processes more headlines, within the same caps.
9. The council's evidence pack reads all rows of the named companies, which is heavy for the largest entities.
10. Nothing here verifies that three different model vendors are reachable until the first run records answers.

## To activate production storage (not done)
Needs the owner's explicit approval after reviewing the ten-headline review and the seven-day report: a migration for
the verdict table (the existing `council_verdict`), switching the connection from read-only to a write path for that
one table, and moving the ledger into the database.
