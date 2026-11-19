# Council remediation after the seven-day dry-run evaluation (19 Nov 2026)

Owner direction: adopt the important recommendations, skip the rest. Council production storage, the Council dashboard, scoring weights, paid APIs, the technical and financial databases and any historical rewrite of stored data all stay untouched. Everything below is dry-run or read-only.

## Adopted and implemented
| Item | What was done | Evidence |
|---|---|---|
| Corporate-event rule | New rule 9 (weight 88): company named plus merger, stake sale, bid, rights issue, capital raise, restructuring, court or tribunal ruling, large loss, impairment, sale of a plant or business. The hit records the stage (proposed or reported versus announced or done) and why it fired. | `engines/news_importance.py`; benchmark test |
| 43-headline regression and recall benchmark | `tests/fixtures/council/material_event_benchmark.json`: 10 material events (all caught, symbols checked), 26 should-not-flag headlines (global wires, daily price pages, procedural notices), 5 documented known gaps with reasons. Reviewed by the assistant; the owner is asked to extend it. | `tests/test_council_benchmark.py` |
| Flag precision | Daily price pages, FX/gold "for today" pages and FBR procedural notices no longer become flags; a headline naming a listed company gets +10 priority and a market-wide-only one -5. | `news_importance.py`, benchmark test |
| Mettis timestamps (forward only) | Mettis article times are read as Pakistan time whatever label they carry, then converted to UTC. Stored rows are NOT rewritten. A read-only impact report script and workflow produce the evidence for a separate decision on history. | `engines/news_collector.py`, `scripts/mettis_timestamp_impact.py` |
| Independent models (free tier only) | Each analyst is pinned to a different model family: news on Groq gpt-oss-120b (OpenAI), financial on Groq qwen3.8-27b (Alibaba), macro on Gemini flash (Google). No cross-family fallback: if the pinned model cannot answer, the analyst is recorded as unavailable. Switch back with PSXNI_COUNCIL_INDEPENDENT_MODELS=off. | `engines/council_news.py`; model list verified on the owner's keys |
| Headline versus event de-duplication | An article stored under several URL forms counts once per outlet in its event. | `news_importance.py`, test |
| Reporting separation | The seven-day report now shows collection executions, events seen, flagged, council runs, assessed, failed, the queue by state (pending, covered, needs review) and how often an analyst was unavailable. | `engines/council_news.py` |
| Sector-transmission layer | A structured, deterministic list of the sectors usually exposed to a named driver (crude, domestic fuel, gas and LNG, interest rates, rupee, cement and coal, power payments, tax measures, fertiliser) with the mechanism. It never asserts a direction: effects depend on each company's exposure. Candidates ride in the queue payload. | `engines/sector_transmission.py` |
| Never drop an event | Already true: items stay in the queue with original timestamps; the 36-hour "covered" state is marked, not deleted. | ledger tests |
| Dashboard: radar | Seven-day window kept; 30-day context added (material items in the last 7 and 30 days, latest material item). | `engines/market_dashboard.py` |
| Dashboard: move explanations | Plain labels: PLAUSIBLE_CATALYST, MULTIPLE_POSSIBLE_CATALYSTS, PLAUSIBLE_CATALYST (sector or market), NO_IDENTIFIED_CAUSE. CONFIRMED_EVENT and CONTRADICTORY_EVIDENCE are never produced: a stored fact cannot confirm a cause, and direction conflicts are not yet tested. | `engines/dashboard_html.py` |
| Tracker storage (option a) | The daily tracker now validates its snapshots and publishes a small versioned `results.json` plus the snapshots to a dedicated data branch `data/setups-forward` (the workflow's own token, results files only, no credentials). Checkpoints recorded in the file: 20 snapshots, 30 days, 60-90 days, 6 months. | `engines/setups_forward.py`, `setups_forward.yml` |

## Adopted in part or corrected
- **URL de-duplication at collection** is not changed yet: the URL variants that produce the repeated stored titles have not been seen. The council-data workflow now lists them; the collector will be changed once the forms are known, so existing rows are not re-inserted under new keys.
- **Tracker reader.** Reading a file from a private data branch needs a credential. The earlier suggestion that option (a) avoids giving the app a token does not hold for a private repository: the Streamlit app would need a fine-grained, read-only token for this one repository. That token and the tracker screen are for the owner to decide; the writer is done.
- **Cost-tiered analysts** (one model for routine news, two for important company events, three for macro) is sensible but is not built: the current priority is to measure whether three independent families work at all on the free tier.

## Deferred (not useful yet, or needs approval)
- Historical Mettis timestamp correction and a raw-timestamp column (production change; separate approval).
- Macro-claim schema and prompt tightening (to be done after the independent-model run shows what the macro analyst now produces).
- Positive/negative/mixed direction on the radar (direction cannot be asserted from evidence on file).
- A fresh seven-consecutive-day dry run including a weekend and a holiday: time-gated; it runs from now.

## Not done and why it stays off
Production analytical storage, the Council dashboard and contradiction flag, any trade instruction, any weight change, any paid API. No activation without explicit owner approval.

## Live verification and follow-up (same day)
- 10-headline dry run on the new chain: news (OpenAI gpt-oss-120b) and financial (Alibaba qwen3.8-27b) answered 10 of 10 each; disagreement between the two families was found in 7 of 10 verdicts (it was 0 of 18 when one model answered everything). The macro analyst on Gemini failed 10 of 10 (HTTP 503 overloaded 15 times, quota 429 eight times, timeouts four) and was recorded as unavailable, as designed.
- Fix: the macro analyst now tries Gemini (flash-latest), then the free Gemma model on OpenRouter (a third family, still not shared with the other two analysts).
- Rule 9 on the same seven days: 15 company events flagged, among them every one of the missed material examples that name a listed company (ATRL court win, Nimir/IGI, Samba x2, Mobilink/Apna, Colony Textile loss, Supernet rights issue); the top-priority list now starts with them. Overall flag rate is unchanged at about 22% because macro rules 2 and 5 dominate (175 hits): the daily cap and the ordering decide what the council sees, and the macro flag rate remains an open calibration item.
- Mettis impact report: 399 stored Mettis rows; 99 are dated after they were collected (the live ones); the other 300 are older back-fill rows that look consistent but may carry the same offset. Nothing was changed.
- Stored duplicate titles: 114. Two causes: tracking variants of one article (Business Recorder `?v=` links; fixed at collection by `canonical_url`) and recurring daily pages that reuse a title on different days (weather, morning breeze, FX rates, gold price), which are separate articles and are handled by the routine filter, not merged.
- Third live check (after the macro fallback fix): news and financial answered 10 of 10 each on two different families; disagreement found in 4 of 10 verdicts. The macro analyst answered 1 of 10: Gemini returned quota-exceeded (429) 23 times and overload (503) twice, and the free Gemma model was rate-limited (429) 24 times. One verdict therefore had all three families answering ("3 of 3 lenses answered, on 3 distinct verified model(s)"), which shows the design works, but the free third family has little capacity, partly used up by these repeated test runs the same day. Normal operation needs about 6 macro calls a day. Re-measure after a quiet day before drawing conclusions.

## Second round (owner's review of the remediation, 19 Nov)
Accepted and implemented; items that repeated earlier work or were not worth the effort were skipped.

| Review point | Done |
|---|---|
| Gemini and Gemma are both Google: macro needs a real third family | Gemma removed. Macro is now NVIDIA (nemotron-3-ultra, free on OpenRouter) first, Gemini only as its fallback. `FAMILIES` maps every model to its lab; an unknown model counts as unknown, never as independent; a test fails if two analysts share a family. |
| Model-availability report | The seven-day report now has a per-analyst table: provider, exact model, family, primary or fallback, ok, rate-limited (429), other failed. |
| Do not count disagreement when an analyst is missing | Each record carries `coverage`: `full` (three analysts on three families) or `INSUFFICIENT_ANALYST_COVERAGE`. In the latter `disagreement_found` is `null` ("not assessed"); no consensus is claimed. |
| Rule 9 should not treat every mention as material | The stage is recorded: proposed or reported, announced or done, or "withdrawn, denied or called off". Company chatter with no corporate action is a tested negative. "sell plant and machinery" wording added. |
| Extend the benchmark, keep a holdout | Baseline left unchanged except Gatron moving from "gap" to "caught". New `benchmark_extended.json` (10 positives, 10 company-chatter negatives, difficult cases). New `benchmark_holdout.json`: empty by design, to be filled from headlines collected after 19 Nov and labelled before the system's flags are looked at; a test refuses overlap with the tuning sets. The reviewer's targets (50 reviewed positives, 100 negatives or ambiguous) are NOT met: today 21 positives and 36 negatives. |
| Gatron / GATI with context | Bare "Gatron" maps to GATI only when the headline also carries a corporate-context word (merger, scheme of arrangement, book closure, shares, board, results...); "Gatron Industries" maps always; "A Gatron truck overturned" does not. Data lives in `contextual_aliases` of the alias file. |
| Mettis: keep history, add a read-only correction layer | No stored row changed. `scripts/mettis_timestamp_impact.py` now writes a versioned file (`mettis-tz-correction-v1`) for every Mettis row: original, corrected, collected, zone, method, validation status (valid, check, unverifiable), calendar-day change. Midnight cases are tested. |
| Tracker screen with a read-only token | New "Performance tracker" page, shown only where `PSXNI_TRACKER_READ_TOKEN` is set in the app's secrets. It reads `results.json` from the data branch, validates its schema, days and duplicates, shows "too few snapshots to say" until 20, never shows or logs the token, and fails closed. Needs a fine-grained read-only Contents token for this repository; such a token reads the whole repository, not only the branch. |

Not repeated or deferred (as before): raw-timestamp column and parser-version column (production schema change), cost-tiered analysts, macro prompt tightening, raising the daily cap, more dashboard charts, radar direction.

### What the next evaluation has to show (acceptance list)
Three analysts reliably on three families (macro: at least 10 checks answered); the original missed events detected; no excessive false positives on the extended and holdout sets; Mettis times correct for new rows; separate events kept separate; sector candidates without direction; important events still queued at the cap; a weekend and a holiday; every conclusion traceable to source evidence.

### Live check of round 2 (10-headline dry run, NVIDIA macro analyst)
- News (OpenAI gpt-oss) and financial (Alibaba Qwen) answered 10 of 10 each. Macro on NVIDIA nemotron-3-ultra produced a usable answer in 5 of 10 verdicts (3 unparsable, 1 error, 1 refused by the quota guard); of 15 NVIDIA calls, 7 came back as an empty answer and 8 answered; the Gemini fallback then failed 7 times (429 quota five times, 503 twice).
- Result: 5 of 10 verdicts had full coverage (three analysts on three different families: OpenAI, Alibaba Qwen, NVIDIA) and in all 5 the models disagreed; the other 5 are recorded `INSUFFICIENT_ANALYST_COVERAGE` with `disagreement_found` null, as designed.
- **Not yet met:** the macro analyst is not operational (the review asked for at least 10 answered checks). Likely cause: the NVIDIA model is a reasoning model whose answer is cut off or empty at the lens output limit; not yet confirmed. Next step: test a larger output limit for that model, or another free non-Google family, before the fresh seven-day dry run.
- Mettis correction layer on 400 stored rows: 99 `valid` (stored later than collected, so the five-hour offset is visible and the corrected time is consistent), 301 `unverifiable` (collected long after publication), 1 row would change calendar day. Nothing was changed.

### Macro analyst fixed (third live check of round 2)
- Cause of the earlier failures: the NVIDIA reasoning model used its output allowance on thinking (empty answers) and some answers were wrapped in a markdown fence (unparsable). Fixes: a strict-but-tolerant JSON reader (fenced or chatty answers are read; garbage is still refused), low reasoning effort and a 4,000-token output floor for OpenRouter requests.
- Result: macro answered 8 of 8 attempted verdicts (before: 5 of 10); news and financial 10 of 10 each. The 2 remaining misses were our own input guard (the macro evidence pack is 8,400-9,000 tokens against a default guard of 8,000). The macro analyst now gets a 14,000-token input allowance (only when it is not served by Groq, whose free tier rejects oversized requests); news and financial keep 8,000.
- Of the 8 verdicts with three analysts on three families, models disagreed in 5 and agreed in 3. The next ten-headline run should show 10 of 10.
