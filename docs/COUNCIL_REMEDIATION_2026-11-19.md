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
