# Phase 2 — macro factors (PLAN ONLY; not built)

Status: PLAN. No engine code, no table, no fetch resource is added by this document. Build starts only after the owner
approves this plan and clears the decisions in section 6.

## 1. What this plan does not assume
- **Investify is not a consented source for rates, commodities or sentiment.** The Investify consent records cover
  announcements, fundamentals, profile and competitors only (News is behind a disabled flag). Nothing consents to
  Investify USD interbank, petrol or diesel, Brent or WTI, gold or silver, or a Fear & Greed index. Phase 2 therefore
  does not use Investify for macro data. Using it would need a new consent record first.
- **Petrol, diesel, gold and silver are kept out of Investify's scope.** The owner has named public sources for them (OGRA; a public bullion source or SBP). They are not admissible until their access and terms are assessed.
- **No source is named for the Fear & Greed index** in any register in this repository. It is not admissible.

## 2. Sources, cadence and status
Series definitions come from `config/macro_series.json` (definitions only, no values). Values enter by owner-attested
manual import of official releases until the access decisions in section 6 are made.

| Factor | Source | Series | Cadence | Mechanism | Access status |
|---|---|---|---|---|---|
| Policy rate | SBP | `sbp_policy_rate` | irregular (MPS) | T3 | Automated access blocked (HTTP 403, R3); manual import only |
| KIBOR 6-month | SBP | `kibor_6m` | daily | T3 | Blocked (R3); manual import only |
| PKR per USD, interbank | SBP | `pkr_usd_interbank` | daily | T4 | Blocked (R3); manual import only |
| SBP FX reserves | SBP | `sbp_fx_reserves` | weekly | T4, T9 | Blocked (R3); manual import only |
| CPI (national, YoY) | PBS | `cpi_yoy_national` | monthly | T5 | Not yet assessed for access; manual import only |
| Brent crude spot | EIA | `brent_spot` | daily | T1, T7 | Automated access blocked pending U2; manual import only |
| Coal (world) | World Bank Pink Sheet | `coal_world_bank` | monthly | T7 | Blocked pending U2; manual import only |
| Urea (world) | World Bank Pink Sheet | `urea_world_bank` | monthly | T7 | Not relevant to HUBC; excluded |
| Petrol, diesel | OGRA (public; owner-named) | petrol and diesel pump prices | at each official price notice | T1 (fuel cost) | Access and terms not yet assessed; not in the source register |
| Gold, silver | public bullion source or SBP (owner-named; one to be chosen) | gold and silver prices | daily | context only; no HUBC mapping | Source and terms not yet chosen or assessed |
| Fear & Greed index | none identified | — | — | — | GAP: no source; no sentiment factor in Phase 2 |

Transmission definitions (`docs/PHASE_5_TRANSMISSION_FRAMEWORK.md`): T1 oil price, T3 interest rates, T4 PKR exchange rate,
T5 inflation, T7 global commodities (the specific grade and location), T9 reserves.

## 3. How each factor maps to HUBC
The reference is the HUBC macro brief (`docs/research/hubc/HUBC_research_brief_part2_macro.md`, Part 2, section 5).

- **Interest rates (T3) → finance costs.** Part 2 records the policy rate at 10.5% (Dec 2025), 11.5% (Apr 2026) and
  12.0% effective 27 Oct 2026, and states the rate tailwind has reversed for FY27. Finance costs fell from Rs 15.2bn
  (FY25) to Rs 9.1bn (FY26) per the audited accounts (`docs/research/hubc/hubc_financials_3yr.json`).
- **PKR per USD (T4) → associate economics.** Part 1 lists PKR/USD as a driver for dollar-indexed PPAs. The brief
  marks it "not separately sourced here", so this mapping is a hypothesis, not a sourced claim. Phase 2 must label it so.
- **Brent and coal (T1, T7) → CPHGC fuel cost.** CPHGC is an imported-coal plant that ran at 11% load in FY26 and
  earns mainly capacity payments (Part 3). Its direct fuel exposure is therefore limited. Thar coal is local
  (TEL and ThalNova at 69% load). The brief leaves fuel economics "TO RESEARCH + CITE", so this mapping is partly
  unsourced and is labelled as such.
- **Sentiment and fuel prices:** no mapping. There is no source, and the brief makes no claim for them.

## 4. Test plan
The HUBC output is checked against the brief's macro section, not against market data.

Passes only if all of these hold:
1. Every rate figure the brief states (10.5%, 11.5%, 12.0%, and their dates) is reproduced exactly from the imported
   SBP series.
2. The finance-cost direction matches the audited accounts (FY25 Rs 15.2bn to FY26 Rs 9.1bn) for the T3 mapping.
3. Every output that depends on an unsourced mapping (PKR/USD, fuel) carries the label "unsourced hypothesis".
4. No output states a commodity or sentiment value that has no imported source.
5. No value is produced without a source name and a source date (the rule already enforced by
   `engines/research_facts.py`).

Fails on any mismatch in 1 or 2, or on any missing label in 3 to 5.

## 5. Fetch budget
- Phase 2 adds **zero Investify requests**. Its data comes from manual import of official releases.
- Fetch budget for any future automated source: it must be recorded in its own policy entry and must not draw on the
  Investify daily ceiling (12) or weekly ceiling (60) in `config/investify_good_citizen.json`.
- Each approved automated source gets at most one request per series per day, subject to that source's own terms.
- Phase 2 touches no fetch resource in `engines/autonomous_tick.py`.

## 6. Decisions needed before any build
1. **R3:** SBP permission for automated access (currently blocked, HTTP 403).
2. **U2:** EIA API key and terms, and World Bank non-commercial terms for private research.
3. **Investify macro:** do you want Investify rates or commodities at all? If yes, a new consent record is needed first.
4. **Petrol, diesel, gold, silver:** the owner has named OGRA (petrol and diesel) and a public bullion source or SBP (gold and silver). Assess their access and terms, and choose the gold and silver source, before any build.
5. **Fear & Greed:** name a source and its terms, or drop the sentiment factor.
6. **CPI (PBS):** access assessment.

Approval of this plan does not approve any of the above.

## 7. Inputs by source, once categories are enabled (note added after the expanded consent)
The expanded Investify approval lists Rates & Commodities and Sentiment as consented categories, but enablement is
separate and stays off. Until an owner-approved step enables them, every macro input comes from the public sources in
section 2. Once enabled, the mapping would be:

- **From Investify (only after enablement):** the Rates & Commodities category for rates or commodity prices where Investify
  is the chosen source, and the Sentiment category. Market & Index, Sectors and Technicals are consented but are not macro
  inputs for this plan, so they are not used here.
- **From public sources (unchanged by enablement):** SBP policy rate, KIBOR, PKR/USD interbank and reserves; EIA Brent;
  World Bank coal; PBS CPI. Their access status is in section 2.
- **Commodities on public sources:** petrol and diesel prices (OGRA); gold and silver (a public bullion source or SBP).
  They stay out of Investify's scope: they are not added to the consent record, and no Investify request is made for them.
  Their access and terms are not yet assessed, so they are not yet admissible inputs.

Changing an input's source requires a plan revision and approval. This note approves nothing.
