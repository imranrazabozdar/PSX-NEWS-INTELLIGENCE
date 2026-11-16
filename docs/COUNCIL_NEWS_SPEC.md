# Council on material news: proposed spec (one page, for owner approval)

Status: PROPOSAL. Nothing here is built. It reuses the existing council (`engines/analyst_council.py`,
`scripts/council_run.py`), which already builds an evidence pack in Python and runs three lenses on free-tier keys.
Nothing depends on Claude.

## Goal
When a news item that matters arrives, the council writes a dated, sourced reading of it for the companies, sectors and
the Pakistan market it touches, using what the brain already holds (facts, rollups, signals). No buy or sell wording; no
number comes from a model (the pack holds every figure, and an assessment citing no pack evidence is dropped).

## What counts as material (Python only, no model)
An event is made from a `news_item` headline that `news_facts` already matched. It is material when ONE of these holds:
1. a company row with topic `news.results` or `news.dividend` (a result or payout);
2. a `market.rates`, `market.fx`, `market.fiscal`, `market.inflation`, `market.energy` or `market.index` row;
3. a `news.signal` (an entity whose share of the news stands out against its own history);
4. a company named in 3 or more headlines on the same day.
One event per story (same headline from two outlets is one); the same event key is never run twice in 24 hours.

## Pack and run
`build_pack(event, companies, sectors)`: the headline and snippet, the named companies' facts (indexed reads), their
sectors, always `MACRO:PAKISTAN`, linked companies. Three lenses (news, financial, macro) then the deterministic
conflict check, as today. Result stored in `council_verdict` (the 0003 table is created on the first stored verdict,
which is why it does not exist yet; no verdict has been stored so far).

## Limits (cost and quota)
- At most 6 council runs a day and 2 per collector run; a run is about 4 model calls, so about 24 calls a day across the
  five free-tier accounts. Order: results and payouts first, then signals, then macro.
- Accounts already at their free-tier limit are skipped before any call (existing behaviour); if none answer, the event
  is logged as "not run" and retried next time, never invented.
- Rows are read by company through the new index, so the pack stays small.

## Proving it before it runs by itself ("prove before scaling")
1. Dry run on 10 real stored headlines across the material types: print verdicts, store nothing; owner reads them.
2. Seven days of automatic dry-run logging (events chosen, verdicts printed in the Actions log, not stored).
3. Only then `--store` on, still capped. Each stored verdict keeps its lens, model, prompt version and evidence ids.

## What it does NOT do
It does not feed verdicts back in as facts (no circular evidence); it does not advise buying or selling; it does not read
article bodies (headline and a 300-character snippet only); it does not run on non-material news.

## Decisions for the owner
1. Daily cap (proposed 6) and the four materiality rules above: right?
2. Start with the 10-headline dry run, then the 7-day automatic dry run, before storing anything: yes?
3. Run for all listed companies, or only a watchlist you name?
