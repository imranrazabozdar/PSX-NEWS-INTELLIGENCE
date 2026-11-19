# PSX News Council: seven-day dry-run evaluation (19 Nov 2026)

**Status: evaluation only.** Production analytical storage is NOT activated. No scoring weight was changed. No paid API or paid fallback was introduced. The technical and financial databases were not touched. The dry run's audit records were copied read-only (`ledger.json`, `records.jsonl`, `review/` from the latest run's artifact) and are unchanged. The only addition to the repository is a read-only data script and workflow (`scripts/council_eval_data.py`, `.github/workflows/council_eval_data.yml`).

## 1. Recommendation

**C. Requires data-quality and rule remediation (then another dry run).** The machinery is reliable and its evidence trail is sound, but the council is not yet looking at the right events, one outlet's dates are wrong, and the three "analysts" are one model, so model disagreement cannot be measured. **Explicit owner approval is required before any activation; none is requested here.**

What passed: scheduling and limits, evidence traceability, free-tier-only operation, failure handling. What blocks approval: missed company-level events (rules), the Mettis timestamp offset, no independent second model, and only three active council days (not seven).

## 2. What was evaluated (and its limits)

- **Dry-run period actually covered.** The council ran on 17, 18 and 19 Nov (three weekdays, 114 executions, 18 council runs). It did not run on 12-16 Nov, and no weekend or holiday has been covered. "Seven days" below means the last seven days of news (1,137 headlines, 12-19 Nov) re-run through the same cluster-and-classify pipeline, plus the three days of council activity.
- **Human review.** Done by me (an AI) on samples: all 18 verdicts, 70 mapped headlines, the 30 highest-priority flagged events, and 43 unflagged headlines that look material. It is not a substitute for the owner's own spot check; the items worth checking are listed in section 6.
- **No ground truth for "what mattered".** Missed events are judged by headline wording, not by price reaction.

## 3. Daily statistics

| Pakistan day | headlines | events | flagged (rule 1 / 2 / 5) | multi-outlet events | executions | council runs (cap 6) | model calls (ok / transient / error) |
|---|---|---|---|---|---|---|---|
| 2026-11-12 | 11 | 11 | 4 (1 / 3 / 0) | 0 | none | 0 | 0 / 0 / 0 |
| 2026-11-13 | 56 | 52 | 16 (0 / 14 / 6) | 2 | none | 0 | 0 / 0 / 0 |
| 2026-11-14 | 33 | 31 | 15 (0 / 13 / 9) | 0 | none | 0 | 0 / 0 / 0 |
| 2026-11-15 | 18 | 18 | 2 (0 / 1 / 1) | 1 | none | 0 | 0 / 0 / 0 |
| 2026-11-16 | 131 | 110 | 22 (2 / 15 / 7) | 10 | none | 0 | 0 / 0 / 0 |
| 2026-11-17 | 237 | 197 | 34 (0 / 22 / 14) | 14 | 25 | 6 | 122 / 62 / 2 |
| 2026-11-18 | 408 | 195 | 41 (0 / 26 / 22) | 11 | 48 | 6 | 23 / 2 / 0 |
| 2026-11-19 | 243 | 165 | 31 (0 / 17 / 19) | 9 | 41 | 6 | 24 / 3 / 0 |
| **7-day total** | 1137 | 779 | 165 (3 / 111 / 78) | 47 | 114 | 18 | 169 / 67 / 2 |

Flag rules seen: rule 1 (company results) 3, rule 2 (SBP / FX / fiscal / energy / index) 111, rule 5 (policy, regulatory, geopolitical) 78. Rules 3, 4, 6 and 7 flagged nothing in the window (rules 3 and 6 need a news baseline that is not yet long enough; rule 8, the announcement gate, adds 3-6 events per scan and is counted separately).

## 4. Aggregate seven-day statistics

| Measure | Value |
|---|---|
| Headlines collected | 1,137 (Business Recorder 697, Profit 212, Mettis 93, Express Tribune 73, Dawn 62) |
| Events after clustering | 779 (47 reported by more than one outlet) |
| Flagged for the council | 165 (21% of events) |
| Council runs | 18 (cap 6 a day, 2 an execution: never exceeded) |
| Runs assessed / failed | 18 / 0 |
| Lenses answering per run | 3 of 3 in 17 runs, 2 of 3 in 1 |
| Council runs as a share of flagged events | 17% (18 runs against 106 events flagged on 17-19 Nov; the daily counts overlap, so this is an upper bound on distinct events) |
| Queue now | 139 waiting, 0 needing review (before the 36-hour "covered" fix started to apply) |
| Model calls | 238: 169 ok, 67 transient, 2 errors |
| Tokens | 361,432 in, 117,616 out |
| Cost | $0: free-tier accounts only, no paid fallback (cost recorded as "not metered") |

## 5. Findings by area

### 5.1 News coverage and missed material events
- Outlets: Business Recorder (hourly-fresh, median lag 0.7 h), Dawn (median 3.3 h), Profit and Express Tribune (median 8-14 h, dominated by the one-month back-fill), Mettis (see 5.6).
- **Missed events (unflagged but material-looking), 43 in seven days.** Examples: Supreme Court ruling for Attock Refinery on a sales-tax dispute (ATRL); IGI Investments' proposed 60% stake in Nimir Resins (NRSL); Saudi investor's renewed bid for 84.51% of Samba Bank (SBL) and its earlier withdrawal; Mobilink Microfinance Bank acquiring 82.51% of Apna Microfinance Bank (AMBL, UNIC); Colony Textile's Rs11 billion loss; Gatron's scheme of arrangement; Supernet Technologies' Rs915 million rights issue; Pharma sector earnings; a fire at a food factory in Baldia.
- Cause: rule 1 only matches strict results wording and rule 5 does not match court rulings or corporate actions. There is no rule for mergers, stake sales, rights issues, large losses or court decisions in company news. The Investify announcement gate (rule 8) covers filings, not news.
- Of the 43, about 10 are genuinely company-material; the rest are global market wire stories ("Asian stocks...", "Copper extends losses") that contain the word "losses" or "profit" and are correctly not flagged.

### 5.2 Company identification and symbol mapping
- 74 of 1,137 headlines (6.5%) name a company the vocabulary recognises. In the 70-headline sample, **the symbol was correct in 70 of 70**. Four of the 70 were not company events: two "NBP issues foreign exchange rates" notices and two "Kohat Cement Company Limited" page-style titles. Two-company stories were handled correctly (Pakistan Services / Thatta Cement; IGI Holdings / Nimir Resins; Mobilink / Apna).
- Recognised names that do not map (21 headlines): Colony Textile, Gul Ahmed Textile, National Resources Limited (alias gap: the headline form omits "Mills"), plus names that are not listed (ABHI Microfinance Bank IPO, Delta Energy, World Bank, Asian Development Bank, Deutsche Bank), which should stay unmapped.
- Most mapped: HBL 10, SOYASUP 7, NBP 5, BOP 5, NESTLE 5. Several of these counts are the same title stored several times (section 5.7).

### 5.3 Event classification and importance ranking
- Of the 30 highest-priority flagged events I judged about 8 low-materiality (several more are global market wires of doubtful relevance to Pakistani equities): routine daily pages ("Gold price in Pakistan for today", "Foreign exchange rates", "Rupee records gain"), a marginal index move ("KSE-100 settles marginally higher"), and FBR procedural notices (faceless-appeal rules, sesame-seed customs values, declaration filing).
- Company-specific events rank at the top where flagged (NBP results x2, POML, Nestle Pakistan's water business transfer, HUBCO smelter study, HUM Network and Unity Foods regulatory actions). The company bonus merged on 19 Nov applies from the next executions.
- 21% of events flagged is too many for a council that can run 6 a day.

### 5.4 Direct and indirect sector-impact mapping
- Of 10 company or market entities assessed in the 18 runs, 2 were company-level (NBP, POML) and 8 were market-wide (MACRO:PAKISTAN). No sector-level entity was assessed in any run, and `sector_impact` was empty in the sample read. The sector mapping exists (for example SECTOR:OIL_GAS on LNG and FBR oil-and-gas stories) but the council did not produce indirect-impact output in these 18 runs. **This area could not be evaluated for quality; it was effectively unexercised.**

### 5.5 Evidence quality, traceability and unsupported claims
- Every assessment cited evidence ids: **33 of 33 exist in the run's evidence pack.** Each event record carries its outlets, URLs, publication times and reliability weights.
- The validators discarded **110 assessments** the models proposed without support (macro lens 94, news lens 13, financial lens 3). That is the guard working, but it shows the macro lens often invents effects, and it wastes tokens.
- Reasoning beyond the headline: the NBP macro reading cites a macro inflation fact and a rupee-devaluation item; the ids exist, but I did not verify the underlying facts. "Things to monitor" lists are generic ("company ticker", "financial statements", "receivables" repeat across runs).
- Verdict: traceable and mostly well-grounded; not free of speculation; no fabricated ids found.

### 5.6 Event-date versus collection-date accuracy
- **Defect: every Mettis item is dated about 5 hours in the future** (median "published minus collected" is -4.7 h, all 98 rows negative). Mettis' local Pakistan time is being stored as UTC. This shifts event dates, recency scoring and any item near midnight Pakistan time.
- Other outlets are consistent (published before collected). Median time from the newest member to the council's processing was 7.8 h (max 29 h): processing is capped by the 6-a-day limit, not by collection.

### 5.7 Duplicate detection and event-version handling
- Clustering is effective: 1,137 headlines became 779 events; 6 pairs of flagged events look like repeats (petrol-price cuts on different days, daily gold and FX pages, a repeated rupee headline). The repeats seen in the 18 verdicts came from the repeated petrol-price decisions; the 36-hour "covered" rule merged on 19 Nov addresses that.
- **Stored duplicates:** the same title appears 4-5 times in `news_item` for some stories (for example HBL trade-links, Nestle water business, Soya Supreme, ABHI subscription), probably URL variants. This inflates member counts and mapped-headline counts. Not yet confirmed which URL forms differ.
- Versions: 9 of 136 event ids have two or more versions (an event that grew new members is re-keyed). The policy for re-assessing a grown event is not defined.

### 5.8 LLM agreement and disagreement
- **One distinct model answered every lens** (openai/gpt-oss-120b on three Groq accounts), in all 18 runs. Disagreement was found in 0 of 18, which carries no information: one model cannot disagree with itself in a meaningful way. Of 10 assessed entities, 8 were put forward by a single lens only and 2 by several lenses (both agreed).
- There was no material disagreement between models to report. **Model agreement as a quality signal is unproven.**

### 5.9 Runtime reliability, concurrency and daily limits
- 114 executions in three days; the longest gap between executions was 31-38 minutes; none over 45. Executions follow each news-collector run.
- Caps held exactly: 6 runs a day, never more than 2 in an execution. The ledger uses a file lock; no duplicate execution ids; no run failed. Run time: median 13 s, max 19 s. Database reads: at most 1,972 rows per execution, zero writes.
- The daily cap is the binding limit: it is used up each day and the queue grew to 139 waiting.

### 5.10 Provider quotas, costs and failure handling
- Groq (three accounts): 55 rate-limit responses (HTTP 429) and 2 "request too large" (HTTP 413); all retried or recovered. Gemini: 4 HTTP 503 and 2 timeouts (4 of 10 calls succeeded). OpenRouter: all 6 calls returned an empty answer, so that fallback adds nothing at present.
- 17 Nov used 57 calls on each Groq account; 159 of the 238 calls belong to the separate 10-headline review (10 further verdicts, in review/ten_headline_review.jsonl, which I did not rate); 18 and 19 Nov used 8-10 per account. No account ran out. Cost is zero by design (no paid fallback exists).

## 6. Human-review findings and items for the owner to check
1. The two ATRL and NRSL stories (court win, stake acquisition) were never flagged: confirm you consider them material.
2. The company-level verdicts (NBP, POML) read correctly against their headlines; please read the NBP macro reasoning and say whether the inflation and rupee comments are acceptable.
3. Confirm Mettis publication times against the site for two or three stories to confirm the 5-hour offset.
4. Review the list of 43 unflagged and 21 unmapped headlines in the attached data file.

## 7. Material model disagreements
None observable (single model). See 5.8.

## 8. Correctly classified events (sample)
NBP profit falls 29% (rule 1); Punjab Oil Mills cuts costs, taxes ate the profit (rule 1); NBP 9-month profit PKR 48.9 bn (rule 1); Govt cuts petrol and diesel by Rs2 (rules 2 and 5, five outlets); SBP projects 3.5-4.5% GDP growth (rule 2); Nestle Pakistan water business transfer ahead of Platinum Equity deal (rule 5); HUBCO subsidiary aluminium smelter study (rule 5); SECP asks HUM Network about Rs5.739 bn receivables (rule 5); SHC freezes Unity Foods assets (rule 5); Pakistan current account surplus of $39 mn (rule 2).

## 9. False positives and missed events
**False positives (flagged, low materiality):** "Gold price in Pakistan for today" and "Foreign exchange rates" daily pages; "Rupee records gain against US dollar" (twice); "KSE-100 settles marginally higher amid late profit-taking"; FBR procedural notices (faceless appeals, sesame-seed export values, officials' declarations); "NBP issues foreign exchange rates" mapped to NBP as a company event.
**Missed (unflagged, material):** see 5.1.

## 10. Recommended improvements, ranked by severity

### High
1. **Add a corporate-action and legal rule for company news** (merger, stake sale or acquisition, rights issue, large loss, court ruling, scheme of arrangement, capital raise), deterministic, requiring a named listed company. Re-run the 43 missed headlines to measure recall.
2. **Fix the Mettis timestamp** (Pakistan local time stored as UTC). Going forward it is a parser change. Correcting the stored history changes production `news_item` rows and needs your approval.
3. **Give the council at least two genuinely different free models** so disagreement can be measured, for example by rotating the lenses across Groq and Gemini models. No paid API.

### Medium
4. **Cut the flag rate** from 21% toward 5-8%: exclude routine price pages, require a minimum magnitude for index moves, treat FBR procedural notices as low priority.
5. **De-duplicate stored news rows** (same title several times) at collection, after confirming the URL variants.
6. **Name coverage:** add confirmed aliases for Colony Textile, Gul Ahmed Textile and National Resources Limited; keep unlisted names unmapped; stop treating "NBP issues foreign exchange rates" as a company event.
7. **Reduce macro-lens waste:** it proposed 94 unsupported assessments; skip it for company events or tighten its instruction.
8. **Daily cap and backlog:** the cap fills each day; the 36-hour covered rule and company-first priority now reduce repeats. Re-measure before considering a higher cap within free-tier quotas.

### Low
9. Define whether a grown event (new version) is re-assessed.
10. Replace boilerplate "things to monitor" with items tied to the evidence.
11. Remove or replace the OpenRouter fallback (empty answers); treat Gemini 503s as transient.
12. Cover a full weekend and one recorded holiday before any approval.

## 11. Before any activation (not requested now)
At least seven consecutive days including a weekend; recall on the corporate-action rule measured; Mettis dates fixed; two distinct models answering; your review of a fresh sample of verdicts. **No activation will be made without your explicit approval.**
