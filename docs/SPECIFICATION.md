<!--
Sanitised technical specification (owner decision C1, 2026-11-07).
Source: "PSX Fundamental & News Intelligence Master Specification v2.2" (document text v2.0).
Converted from .docx to Markdown. Only the cover page was removed; no requirement was changed.
Checked before publishing: it contains no credentials, secrets, personal contact details,
portfolio positions or private investment information. The X/YouTube watchlists (section 4) are
public account identifiers the owner supplied, kept on purpose as requirements.
Requirement IDs used in docs/TRACEABILITY.md refer to the section numbers below.
-->

# PSX FUNDAMENTAL & NEWS INTELLIGENCE ENGINE

MASTER IMPLEMENTATION SPECIFICATION • VERSION 2.0 • 7 NOVEMBER 2026

A comprehensive build blueprint and Claude Code handoff for an
independent, free-first research platform using Python, GitHub, Turso
and Streamlit.

Core mission: turn public and authorised information into
evidence-backed, company-specific PSX intelligence; explain the economic
transmission; estimate financial consequences only where data supports
them; assess market pricing; and learn from historical outcomes.

## Document status and how Claude Code must use it

This is the controlling project specification. Claude Code must read it
before implementation, translate it into a traceable task plan, and
build in approved milestones. It must not attempt a one-shot
implementation. Requirements marked future-phase are part of the
intended product but should not be represented as implemented until code
and tests prove completion.

-   Build a separate project. Do not connect to, edit, migrate, or
    consume the existing PSX technical intelligence engine.

-   Use a new public GitHub repository, a separate Turso
    account/database, and a separate Streamlit deployment. Keep
    credentials and secrets separate.

-   Treat this document as a requirements baseline. If a technical
    detail is infeasible, explain the limitation and propose a compliant
    alternative before silently dropping it.

-   Do not invent data, source access, company exposures, API
    availability, transcript availability, analyst consensus, prices,
    financial inputs or impact estimates.

-   Keep an implementation status register: NOT STARTED, IN PROGRESS,
    BLOCKED, IMPLEMENTED, TESTED. A feature is not complete merely
    because a page or placeholder exists.

# 1. Executive overview and project boundaries

The platform is a personal PSX research terminal focused on fundamental,
news, policy, macroeconomic, sector, commodity, institutional,
geopolitical and social/media intelligence. It complements the user\'s
existing technical engine but is independent of it.

## 1.1 What the system must answer

-   What happened, when did it happen, and when did the system learn
    about it?

-   Is it a confirmed fact, an official proposal, an unverified report,
    an analyst opinion, or a rumour?

-   Which listed companies are actually exposed, directly or indirectly,
    and what evidence proves the exposure?

-   Through what pathway could the development affect revenue, selling
    prices, volume, input costs, FX, financing costs, working capital,
    tax, capex, cash flow or valuation?

-   Can the effect be quantified from sourced company-specific inputs?
    If not, what is missing and what qualitative scenarios are
    reasonable?

-   What is the likely time horizon, confidence, downside,
    counter-evidence and thesis invalidation condition?

-   Has the market already reacted? Is the stock liquid enough to act on
    the information? Is the apparent catalyst already priced in?

-   What did the system believe at the time, and how accurate was that
    assessment afterwards?

## 1.2 Explicit non-goals

-   No automatic buy/sell orders or guaranteed price predictions.

-   No assumption that positive news makes a stock attractive at any
    valuation.

-   No assumption that all companies in one sector have identical
    exposures.

-   No automatic trust in viral tweets, YouTube personalities, brokers,
    headlines or LLM output.

-   No merging with the existing technical engine or shared use of its
    database.

-   No circumvention of paywalls, login restrictions, API limits, robots
    rules, copyright or source terms.

## 1.3 Project separation and free-first architecture

  -----------------------------------------------------------------------
  **Component**                       **Requirement**
  ----------------------------------- -----------------------------------
  Development                         Claude Code implements and tests
                                      one milestone at a time.

  Source control                      New public GitHub repository; code
                                      and non-sensitive documentation
                                      only.

  Database                            New Turso account/database;
                                      independent schema, credentials,
                                      backups and quotas.

  Application                         New Streamlit deployment;
                                      read-oriented dashboard and user
                                      review workflows.

  Scheduled processing                GitHub Actions or another permitted
                                      scheduled worker runs collectors
                                      and writes to Turso.

  Language and analytics              Python for collection, parsing,
                                      exact calculations, scoring,
                                      validation and backtesting.

  LLM                                 Structured extraction, candidate
                                      mapping and evidence-grounded
                                      narrative analysis; never sole
                                      authority.

  Secrets                             GitHub Actions Secrets and
                                      Streamlit Secrets; local .env
                                      ignored by Git.

  Storage discipline                  Store compact structured records,
                                      source metadata, excerpts and
                                      links; avoid storing large
                                      video/audio/PDF blobs in Turso.
  -----------------------------------------------------------------------

Free-tier quotas, API prices, model costs, database limits and hosting
limits change. Claude Code must verify current limits before choosing
polling frequency or claiming that a component is free. The design
should remain useful with low collection frequency and strict cost
controls.

# 2. Overall system architecture and data flow

> Sources → source collectors → normalisation →
> canonicalisation/deduplication → relevance filter → event extraction →
> verification/corroboration → company exposure mapping → economic
> transmission → financial calculation/scenarios → valuation and market
> reaction → opportunity ranking → dashboard/alerts → point-in-time
> backtesting.

## 2.1 Processing layers

  ---------------------------------------------------------------------------
  **Layer**               **Responsibilities**    **Must persist**
  ----------------------- ----------------------- ---------------------------
  Collection              RSS/API/permitted       Source identity, canonical
                          pages, official         URL/ID, published time,
                          documents, reports,     collected time, content
                          video metadata,         hash, access method
                          authorised captions, X  
                          API posts               

  Relevance               Keyword rules,          Relevance score, matched
                          ticker/entity           terms, reason for
                          dictionary, language    inclusion/exclusion
                          and topic filters,      
                          duplicate checks        

  Event intelligence      Extract event, dates,   Event record, evidence
                          location, actors,       excerpts, confidence,
                          status, facts,          model/prompt version
                          interpretation and      
                          conflicting claims      

  Verification            Check primary sources   Verification state, source
                          and independent         quality, corroboration
                          corroboration; preserve count, contrary evidence
                          disagreement            

  Exposure mapping        Match event to company  Direct/indirect/uncertain
                          segment, inputs,        exposure, rationale,
                          customers, geography,   evidence and last verified
                          regulation and          date
                          financing               

  Economics               Trace volume, price,    Transmission chain,
                          cost, FX, energy,       formulas, inputs,
                          logistics, rates, tax,  assumptions and missing
                          capex and working       fields
                          capital                 

  Market context          Valuation,              Reference price/time,
                          price/volume,           market reaction, priced-in
                          liquidity, sector and   assessment
                          benchmark response      

  Decision support        Rank research priority, Dimension scores, risk,
                          alert and monitor       horizon, invalidation and
                          catalysts; no           status
                          auto-trade              

  Learning                Freeze thesis and       Point-in-time snapshots,
                          evaluate forward        return calculations and
                          outcomes                forecast accuracy
  ---------------------------------------------------------------------------

## 2.2 Separation of Streamlit and scheduled jobs

-   Streamlit should not run always-on polling or long-running
    collection loops. It should query Turso and provide filters, review,
    annotations and dashboard actions.

-   Collectors and analysis jobs should run on schedules, process
    incrementally, write idempotently, and expose run logs and failure
    status.

-   Use separate workflows for news, official disclosures/policy,
    commodities/sector data, social media and daily briefing. Avoid
    launching all collectors on every page load.

-   Support manual backfill jobs with explicit date range, rate limits
    and a dry-run option.

# 3. Full intelligence module catalogue

The following 23 modules are capabilities of one shared event-centred
platform, not 23 disconnected applications. Each module must reuse the
company master, source registry, evidence model, event records and
exposure graph.

## 1. News Intelligence

Monitor Dawn, Business Recorder, Profit, Mettis Global, Nukta, Reuters,
Investify, SCS Trade and other permitted sources. Detect, deduplicate
and classify material news; retain source URL and
publication/event/collection timestamps. Extract affected entities,
sector, direction, magnitude, novelty, confidence and horizon.

## 2. Corporate Intelligence

PSX disclosures, financial results, board meetings, dividends,
bonus/right issues, contracts, projects, acquisitions, management
changes, litigation, tax cases, defaults, restructuring, plant
shutdowns, capacity additions, production and operational disruptions.
Parse financial statements and compare periods.

## 3. Policy & Regulatory Intelligence

Monitor SBP, SECP, FBR, OGRA, NEPRA, ministries, ECC, Cabinet, IMF and
other relevant bodies. Track proposals, consultation, draft, approval,
notification, effective date, implementation, enforcement, delay,
amendment and reversal. Topics include petroleum/refinery, gas/LNG/LPG,
electricity tariffs, circular debt, taxation, EV policy,
imports/exports, subsidies, banking, privatisation and digital payments.

## 4. Government Decision Tracker

Track agenda items, meetings, summaries, decisions, approvals,
deadlines, responsible institution, next step, implementation status,
postponement, reversal and actual effective date. Never equate a meeting
or reported intention with an approved policy.

## 5. Domestic Stability & Geopolitical Risk

Monitor road/motorway closures, protests, curfews, security operations,
ports, rail, airports, utilities, internet/undersea cable disruptions,
floods, heatwaves, drought, border closures and regional conflict.
Include KPK/local disruptions, Torkham/Chaman, Pakistan-Iran/Taftan and
other relevant routes. Map geography, severity, duration, verification
and company-specific logistical exposure; do not extrapolate a local
event to all Pakistan.

## 6. International Contagion

Monitor US markets/Nasdaq, Fed, Treasury yields, dollar, China, emerging
markets, global risk appetite, oil, commodities, shipping, sanctions,
wars and supply chains. Trace transmission to Pakistan through PKR,
inflation, imports, SBP rates, trade, capital flows, energy and
sentiment.

## 7. Sector & Industry Intelligence

Maintain operating indicators and peer comparisons for cement,
fertilizer, banks, oil/gas, refineries, OMCs, power, steel, textiles,
autos, technology, chemicals, pharma, food, insurance, logistics and
engineering. Store monthly/quarterly history where available; identify
seasonality, capacity, market share and company-vs-industry trends.

## 8. Commodity & Input-Cost Intelligence

Monitor Brent/WTI, coal, petcoke, LNG, natural gas, LPG, furnace oil,
iron ore, coking coal, scrap, rebar/HRC, urea, DAP, ammonia, phosphate,
sulphur, cotton, wheat, edible oils, naphtha, ethylene/propylene,
metals, freight, insurance, electricity and USD/PKR. Store grade,
benchmark, currency, unit, location, date and source. Map inventory and
pass-through lags.

## 9. Dedicated LPG Intelligence

Track Saudi Aramco CP, propane/butane, premiums, USD/PKR, freight,
insurance, handling, taxes, domestic production, imports, Iranian supply
where verifiable, port/logistics, OGRA and deregulation/auction rules.
Provide landed-cost calculator and company exposure only from verified
operating data.

## 10. Mutual Fund & Institutional Intelligence

Monitor MUFAP, SECP and AMC fact sheets/monthly reports for UBL Funds,
Al Meezan, NBP Funds, MCB Investment Management, HBL AMC, AKD and other
relevant managers. Capture AUM, fund type, equity/cash/debt allocation,
sector weights, holdings, shares/weight/value where disclosed, flows if
available, returns, benchmark and manager commentary. Do not infer net
buying from weight increases alone.

## 11. Broker Research Intelligence

Ingest public/authorised reports from Arif Habib, Topline, AKD, JS
Global, Taurus, Intermarket, Foundation, Ismail Iqbal, Insight, BMA and
others. Capture forecasts, target price, recommendation, assumptions,
valuation method, risks, revisions, report date and eventual forecast
accuracy. Do not bypass restricted research access.

## 12. Market Event Investigator

Investigate configurable large moves, upper/lower circuits, unusual
turnover, volume spikes, bid/offer imbalance, price move without news,
weakness despite good results and resilience during broad market
selling. Search disclosures, news, sector, commodity and benchmark
context. Label cause confirmed, probable or unexplained.

## 13. Company Relationship & Exposure Map

Represent products, business segments, disclosed suppliers/customers,
geographies, imports/exports, raw materials, energy, FX, debt,
regulation, logistics and customer concentration. Each exposure must
have source evidence, scope, confidence and last-verified date.

## 14. Valuation & Fair Value

Calculate sector-appropriate P/E, P/B, dividend yield, EV/EBITDA where
relevant, peer and historical comparisons, EPS growth, cash-flow
quality, debt and scenario-based fair-value ranges. Do not invent
consensus. Explain methodology and stale/missing inputs.

## 15. Investment Opportunity Radar

Combine catalysts, corporate results, policy, industry, commodities,
funds, broker views, fundamentals, valuation, technical confirmation,
liquidity and risk. Classify early catalyst, fundamental improvement,
policy beneficiary, commodity beneficiary, institutional activity,
technical breakout, recovery, speculative and high-risk. Show evidence,
counter-evidence, priced-in status, horizon, confidence and thesis
invalidation.

## 16. Early Warning & Catalyst Tracker

Track draft proposals, consultations, meetings, approvals,
notifications, implementation milestones, board dates, negotiations,
deadlines, tariff resets, policy reviews and expected triggers. Alert on
stage changes and missed deadlines.

## 17. Scenario Simulator

Run oil ±10%, LPG ±15%, SBP rates ±100 bps, FX ±5%, border
reopening/closure, electricity/gas tariff changes, coal changes, cement
dispatch changes and other company-specific sensitivities. Quantify only
when company inputs and units are sourced; otherwise show qualitative
scenarios and missing data.

## 18. Market Behaviour & Technical Confirmation

Optional manual/imported technical context: price/volume,
RSI/divergence, MACD, moving averages, Ichimoku, pivots, candles, OBV,
ADL, CMF, MFI, VIX Fix, order book, unusual volume and
breakout/breakdown. This module is independent; no API/database
connection to the existing technical engine unless the user explicitly
authorises a later integration. Technicals confirm/challenge a thesis,
not auto-buy/sell.

## 19. Historical Event & Prediction Backtesting

Freeze information available at alert time; measure 1/3/5/20/60-session
returns, KSE-100 and sector-relative returns, dividends, costs,
liquidity, circuit constraints, false positives, missed catalysts and
forecast calibration. Avoid look-ahead and survivorship bias.

## 20. Daily Briefing & Alerts

Pre-market Pakistan/international context, commodities, policies,
corporate events, sector winners/losers, unusual stocks, catalysts, risk
changes and upcoming decisions. Configurable alerts for breaking news,
approvals, disclosures, price/volume/circuit, commodity thresholds, fund
holdings, broker research, geopolitics and thesis changes.

## 21. Company Financial Statement Intelligence

Standardise annual/quarterly statements: revenue, gross/operating/net
profit, EPS, margins, finance cost, tax, cash flow, receivables,
inventory, payables, debt, capex, dividends, one-offs, related-party
balances and contingent liabilities. Compare QoQ/YoY and identify
earnings quality, cash conversion and unusual movements.

## 22. YouTube & Financial Media Intelligence

Monitor the user\'s supplied channels. Detect new uploads, obtain
metadata, use accessible/authorised captions/transcripts, filter
irrelevant videos, extract only PSX-relevant stocks, catalysts, policy,
sector, commodity, market outlook, forecasts, targets, risks and
horizon. Cluster repeated themes, disagreements and predictions. Do not
summarise every video indiscriminately.

## 23. X (Twitter) Intelligence

Monitor the user\'s supplied public X accounts and keyword/ticker
searches through compliant official API access or authorised providers.
Detect breaking geopolitical, policy, Pakistan, company and market
developments; measure mention velocity and engagement; identify rumour,
promotional hype, source diversity, conflicting claims and
market-sentiment divergence. Social posts are leads, not proof.

# 4. User-supplied social and media watchlists

These exact URLs/handles were supplied by the user. Store them as
watchlist identifiers. Before enabling collection, resolve profile
metadata and confirm identity where ambiguous. A handle or supplied URL
is not itself proof of identity, authority or reliability. Do not
silently substitute similarly named accounts.

## 4.1 X account watchlist

  -------------------------------------------------------------------------------
  **Handle**              **User-supplied profile URL**   **Initial monitoring
                                                          purpose**
  ----------------------- ------------------------------- -----------------------
  \@MarioNawfal           https://x.com/MarioNawfal       Geopolitics / breaking
                                                          developments

  \@AJEnglish             https://x.com/AJEnglish         International news

  \@imemon15              https://x.com/imemon15          Pakistan / current
                                                          affairs; validate
                                                          identity

  \@clashreport           https://x.com/clashreport       Conflict and
                                                          geopolitical
                                                          developments

  \@AlphaWireHQ           https://x.com/AlphaWireHQ       Breaking news /
                                                          markets; validate
                                                          source profile

  \@Conflict_Matrix       https://x.com/Conflict_Matrix   Conflict / security
                                                          monitoring

  \@AlArabiya_Eng         https://x.com/AlArabiya_Eng     Middle East / oil /
                                                          regional news

  \@CENTCOM               https://x.com/CENTCOM           US military / regional
                                                          official statements

  \@MeherJazibAli         https://x.com/MeherJazibAli     Pakistan commentary;
                                                          validate identity

  \@Asad_Ashah            https://x.com/Asad_Ashah        Business / financial
                                                          commentary; validate
                                                          identity

  \@AsadAToor             https://x.com/AsadAToor         Pakistan politics /
                                                          current affairs

  \@CNN                   https://x.com/CNN               International news

  \@TehranTimes79         https://x.com/TehranTimes79     Iran / regional
                                                          developments

  \@ARNOfficiall          https://x.com/ARNOfficiall      Possible Abdul Rehman
                                                          Najam X identity;
                                                          confirm before linking

  \@trtworld              https://x.com/trtworld          International /
                                                          geopolitical news

  \@LodhiMaleeha          https://x.com/LodhiMaleeha      Diplomacy / foreign
                                                          policy

  \@Portfolio360App       https://x.com/Portfolio360App   Investment / market
                                                          analysis

  \@RT_com                https://x.com/RT_com            International /
                                                          geopolitical news

  \@BullTheoryio          https://x.com/BullTheoryio      Financial markets /
                                                          investment commentary

  \@iihtishamm            https://x.com/iihtishamm        Pakistan politics /
                                                          current affairs
  -------------------------------------------------------------------------------

Also requested by name earlier: Donald Trump and Reuters. Their exact
profile URLs/handles were not supplied in the confirmed URL list. Keep
them in a pending_accounts registry; do not guess handles or activate a
similarly named profile without confirmation.

## 4.2 YouTube channel watchlist

  -----------------------------------------------------------------------------------------------
  **Channel**             **User-supplied URL**                           **Initial monitoring
                                                                          purpose**
  ----------------------- ----------------------------------------------- -----------------------
  Stockify Ltd            https://youtube.com/@stockifyyltd               Stock-specific
                                                                          analysis, sector
                                                                          themes, market
                                                                          opportunities

  Nukta Business          https://youtube.com/@nuktabusiness              Economic policy,
                                                                          business developments,
                                                                          market outlook

  Nukta Pakistan          https://youtube.com/@nuktapakistan              National/political
                                                                          developments only when
                                                                          economically material

  Abdul Rehman Najam      https://youtube.com/@abdulrehmannajamofficial   PSX analysis, stock
  Official                                                                ideas, market sentiment

  Sarmaaya Pakistan       https://youtube.com/@sarmaayapk                 Stock analysis,
                                                                          valuation, financial
                                                                          and market trends

  Standard Capital        https://youtube.com/@scstradepk                 Brokerage research,
  Securities                                                              market outlook,
                                                                          stock/sector analysis

  Young\'s Capital        https://youtube.com/@youngscapital              Investment commentary,
                                                                          stock ideas and market
                                                                          developments
  -----------------------------------------------------------------------------------------------

## 4.3 Social-media relevance filter

The user explicitly wants only information useful to PSX research. The
system must not archive or send every post/video to an LLM. Apply a
staged relevance filter.

  --------------------------------------------------------------------------
  **Priority**            **Capture criteria**      **Examples**
  ----------------------- ------------------------- ------------------------
  High --- process        Specific PSX              A refinery policy
                          tickers/companies;        notification; an analyst
                          results; corporate        explains a bank\'s
                          actions; contracts;       earnings revision; a
                          shutdowns;                confirmed border closure
                          policy/tariff/tax         affecting trade.
                          decisions;                
                          IMF/SBP/FBR/OGRA/NEPRA;   
                          oil/LPG/LNG/coal;         
                          PKR/rates; trade routes;  
                          sanctions; shipping;      
                          security incidents        
                          affecting Pakistan;       
                          market-wide catalysts.    

  Conditional --- process Politics, diplomacy,      Iran escalation that
  if linked               global conflict,          changes
                          technical analysis,       oil/freight/insurance;
                          interviews and broad      US rates that change
                          economic commentary only  global flows or PKR
                          when a plausible          pressure; a chart setup
                          Pakistan/PSX transmission tied to a named PSX
                          pathway exists.           stock.

  Low --- discard or      Motivational posts,       Generic personal finance
  metadata-only           generic tutorials,        lesson with no PSX or
                          entertainment, unrelated  macro relevance.
                          politics, promotional     
                          material without          
                          analysis, repeated        
                          commentary without new    
                          facts, unrelated          
                          international news.       
  --------------------------------------------------------------------------

## 4.4 What to extract from X and YouTube

-   Platform, channel/account ID, handle, display name, canonical
    post/video URL, external ID, publication time, collection time,
    language and content hash.

-   Transcript/post text or relevant excerpts only where access and
    storage are permitted; retain a pointer to original content.

-   Named tickers, company aliases, sectors, commodities, institutions,
    countries, locations, policy topics and event candidates.

-   Claim type: verified fact, official statement, news report, analyst
    interpretation, personal opinion, prediction, rumour, advertisement
    or unclear.

-   Direction and context: positive, negative, mixed, neutral; what the
    speaker actually says and what they do not claim.

-   Forecast details where explicit: company, direction, target,
    horizon, date, assumptions, confidence if stated and invalidation
    condition if stated.

-   Engagement snapshot when available: views, likes, reposts, replies,
    quotes; record observation time because metrics change.

-   Cross-channel repetition, independent source count, disagreement,
    original source attribution and possible syndicated copying.

-   Relevance reason and rejection reason. Keep low-relevance content
    out of expensive LLM processing.

## 4.5 Cross-platform identity and consensus

-   Create one person/organisation identity record with multiple
    platform accounts only after identity is verified. Abdul Rehman
    Najam\'s YouTube channel is supplied; the proposed X match
    \@ARNOfficiall must remain unlinked until confirmed.

-   Do not count reposts, copied headlines or syndicated clips as
    independent corroboration.

-   Cluster posts/videos around one underlying event. A single event
    mentioned by ten accounts remains one event with ten source
    references.

-   Detect disagreement between accounts and preserve the exact claim,
    time and source instead of forcing a single narrative.

-   Track predictions by author and evaluate outcomes over stated
    horizons. Separate a forecast from a general opinion.

## 4.6 X API and YouTube access constraints

X monitoring should use the official X API or an authorised data
provider. Access, search windows, post-read pricing, endpoint limits and
permitted storage/redistribution depend on the current plan and policy.
Do not assume X API is free. Do not scrape around authentication or
access controls. Implement quota-aware polling, per-account budgets,
keyword search budgets, caching and backfill limits.

YouTube metadata may be collected through the official Data API within
current quotas. Caption/transcript access is not guaranteed for every
public video; official caption download can require owner-authorised
access. Use accessible captions, authorised transcript providers,
user-supplied transcripts or manual review. Never represent an
unavailable transcript as analysed.

If transcript is unavailable, retain metadata and mark
transcript_status=unavailable; optionally present it for manual review.
Do not fetch/store full video or audio unless access and rights permit.

# 5. Company master and PSX coverage

-   Start with 30--50 liquid or strategically important PSX companies;
    expand only after mapping quality is demonstrated.

-   Seed ticker, legal name, aliases, sector/subsector, listed status,
    website, business summary, segments, financial-year end, share class
    and source references.

-   Use a canonical company ID. Maintain ticker changes, name changes,
    mergers, delistings and corporate actions as history rather than
    overwriting identity.

-   Include a company alias dictionary to detect tickers, legal names,
    brands, abbreviations and common misspellings. Validate candidate
    tickers against the active company master.

-   Do not infer a company\'s exact input mix, market share, contract,
    geography or revenue exposure from sector membership.

# 6. Sector and industry data requirements

  -----------------------------------------------------------------------
  **Sector**                          **Indicators to capture where
                                      publicly available**
  ----------------------------------- -----------------------------------
  Cement                              Monthly dispatches (local/export),
                                      capacity utilisation, capacity
                                      additions, cement prices,
                                      coal/petcoke, freight, power/fuel,
                                      gypsum/clinker, exports, regional
                                      demand and company market share.

  Fertilizer                          Urea/DAP production, sales,
                                      inventory, imports, gas
                                      supply/tariffs, feedstock and fuel
                                      gas, ammonia/phosphate/sulphur,
                                      subsidy, circular debt, pricing and
                                      seasonal demand. Natural gas is
                                      central to nitrogen fertilizer
                                      costs; crude alone is not a
                                      sufficient proxy.

  Banks                               Deposits, advances, ADR, CASA,
                                      NPLs, provisioning, capital
                                      adequacy, investments, government
                                      securities, policy rate, spreads,
                                      fee income, taxes, dividend
                                      capacity and asset quality.

  Oil & gas / E&P                     Production, reserves, discoveries,
                                      well flows, realised prices,
                                      circular debt, receivables,
                                      exploration capex, gas allocation,
                                      pipeline constraints, import
                                      dependence and FX.

  Refineries                          Throughput, utilisation, product
                                      mix, crack spreads, crude grades,
                                      product prices, inventory
                                      gains/losses, refinery upgrade
                                      projects, pricing policy, duties,
                                      working capital and circular debt.

  OMCs                                Product sales/volumes, market
                                      share, inventory, margins, imports,
                                      retail network, storage,
                                      receivables, freight, FX,
                                      regulatory pricing and supply
                                      disruptions.

  Power / IPPs / utilities            Generation, dispatch, fuel mix,
                                      capacity payments, tariffs,
                                      circular debt, receivables, fuel
                                      costs, hydrology, demand,
                                      transmission/distribution losses,
                                      regulatory determinations and
                                      contract terms.

  Steel                               Scrap, billet, rebar/HRC, iron ore,
                                      coking coal, electricity/gas,
                                      imports, duties, construction
                                      demand, capacity utilisation, FX
                                      and working capital.

  Textiles                            Cotton, yarn, fabric, energy
                                      tariffs, gas availability, exports,
                                      orders, utilisation, labour,
                                      freight, FX, tax refunds and trade
                                      preferences.

  Technology                          IT exports, client geography,
                                      recurring revenue, contracts, staff
                                      costs, FX, receivables, retention,
                                      product mix and
                                      regulatory/data-centre/internet
                                      dependencies.

  Autos                               Sales, bookings, production,
                                      localisation, imported parts, FX,
                                      duties/taxes, financing rates,
                                      consumer credit and model launches.

  Chemicals / pharma / food           Feedstock, API/ingredient prices,
                                      regulation, price controls,
                                      imports, FX, distribution,
                                      capacity, demand, export exposure
                                      and inventory.

  Insurance / asset managers /        Premiums, claims, investment
  logistics / engineering             income, AUM/flows, freight volumes,
                                      contracts, backlog, utilisation,
                                      receivables and regulatory capital.
  -----------------------------------------------------------------------

# 7. Commodity, macro and transmission library

Each benchmark record must include commodity/contract/grade, location,
currency, unit, observation date, publication time, source, methodology
and whether spot, futures, official administered price or assessed
price.

-   Energy: Brent, WTI, Saudi Aramco CP propane/butane, LNG
    spot/contract benchmarks, natural gas, furnace oil, coal grades,
    petcoke, electricity and fuel oil.

-   Industrial inputs: iron ore, coking coal, scrap, billet, rebar, HRC,
    copper, aluminium, zinc and other metals.

-   Fertilizer/agri: urea, DAP, ammonia, phosphate rock, sulphur,
    cotton, wheat and edible oils.

-   Petrochemicals: naphtha, ethylene, propylene and relevant
    polymer/feedstock prices.

-   Cross-cutting: USD/PKR, freight, shipping, insurance, port charges,
    interest rates, inflation, taxes, tariffs and working-capital rates.

## 7.1 Mandatory economic transmission logic

-   Input cost change → inventory replacement cost → cost of goods sold
    with lag → gross margin, subject to selling-price pass-through and
    FX.

-   Commodity price change → company exposure only if the company is a
    buyer, seller, producer or inventory holder of that benchmark/grade.

-   Currency depreciation → import costs, foreign-currency debt, export
    translation, receivables, pricing power and working capital; effects
    differ by company.

-   Interest-rate change → finance cost, investment income, deposit
    repricing, loan yields, demand and valuation; timing depends on
    repricing structure.

-   Tariff or tax change → regulated revenue, pass-through, demand, cost
    and compliance; distinguish notification from implementation.

-   Border/road/port disruption → specific routes, inventory, delivery
    time, freight, export fulfilment and lost production;
    location-specific exposure is required.

-   Oil price change has mixed impacts across refineries, OMCs, E&Ps,
    fertilizer, power, cement, transport and consumers. Do not apply one
    market-wide sign.

# 8. Policy, government and event lifecycle

  -----------------------------------------------------------------------
  **Stage**                           **Definition / evidence required**
  ----------------------------------- -----------------------------------
  Rumour / unverified report          Claim exists but no adequate
                                      corroboration; label clearly and do
                                      not present as fact.

  Discussion / intention              Public statement or meeting
                                      discussion; no formal decision
                                      established.

  Proposal / draft                    A draft or formal proposal exists;
                                      capture issuer, version,
                                      consultation deadline and proposed
                                      terms.

  Consultation                        Stakeholders invited to comment;
                                      record submissions/deadline and
                                      unresolved issues.

  Committee / ECC recommendation      Recommendation or summary has been
                                      made; do not treat as final
                                      approval unless authority confirms.

  Cabinet / regulator approval        Competent authority approved;
                                      capture exact approved text and
                                      conditions.

  Notification / gazette              Formal notification issued; capture
                                      reference number,
                                      publication/effective date and
                                      affected parties.

  Implementation / enforcement        Actual effective date,
                                      implementation evidence, compliance
                                      and enforcement.

  Amendment / delay / suspension /    Preserve previous versions and
  reversal                            explain what changed, when and by
                                      whom.
  -----------------------------------------------------------------------

# 9. Central event-to-company impact engine

This is the core intellectual property of the application. It must not
reduce company impact to headline sentiment or a keyword-to-ticker
mapping.

  -----------------------------------------------------------------------
  **Step**                            **Required process and output**
  ----------------------------------- -----------------------------------
  1\. Detect                          Store source item, original URL/ID,
                                      source, event date, published time,
                                      collected time and text hash.

  2\. Verify                          Rate source quality; seek
                                      primary/independent corroboration;
                                      preserve conflict and uncertainty.

  3\. Extract                         Create structured event: type,
                                      summary, actors, locations,
                                      affected policy/market, status,
                                      direction, magnitude, horizon,
                                      novelty and evidence excerpts.

  4\. Map                             Identify direct/indirect/uncertain
                                      exposure using company segments and
                                      evidence. Explain why each company
                                      is included or excluded.

  5\. Trace                           Describe exact transmission through
                                      volume, price, input, FX, energy,
                                      freight, financing, tax,
                                      regulation, capex or working
                                      capital.

  6\. Quantify                        Python calculations only when
                                      sourced company-specific inputs
                                      exist. Include formula, units,
                                      period, assumptions, input
                                      references and sensitivity.

  7\. Counter-check                   List counter-evidence, offsetting
                                      effects, timing lags, policy
                                      uncertainty and thesis
                                      invalidation.

  8\. Market check                    Compare reference price, volume,
                                      liquidity, sector and KSE-100
                                      response; assess priced-in status
                                      as uncertain unless evidence
                                      supports it.

  9\. Prioritise                      Rank research attention using
                                      transparent dimensions, not opaque
                                      single AI score.

  10\. Learn                          Freeze thesis at alert time;
                                      evaluate outcomes later without
                                      look-ahead bias.
  -----------------------------------------------------------------------

## 9.1 Required company impact report fields

-   Event title, event date, publication date, last update and status
    stage.

-   Confirmed facts separated from AI interpretation and analyst
    opinion.

-   Source links and exact supporting excerpts; contrary or conflicting
    evidence.

-   Company and ticker; business segment; direct/indirect/uncertain
    exposure; evidence for exposure.

-   Transmission path and expected affected financial statement lines.

-   Impact direction (positive/negative/mixed/neutral/unknown),
    magnitude range if supportable, confidence and horizon.

-   Quantitative/qualitative label; formula and sourced inputs; missing
    inputs and assumptions.

-   Risks, offsets, counterarguments, invalidation conditions and next
    trigger.

-   Market reaction, benchmark/sector comparison, liquidity and
    priced-in assessment.

-   LLM/model/prompt version, calculation version and reviewer notes.

## 9.2 Example: coal price falls

The system verifies the relevant coal benchmark, grade, date and
magnitude; maps only cement companies with documented coal exposure;
considers local/imported fuel mix, inventory, freight, FX, consumption,
energy mix and cement selling prices; calculates savings only when
required inputs are available; otherwise produces a qualitative scenario
and explicit missing-input list. It then checks stock price/volume and
sector response.

# 10. Valuation, opportunity scoring and risk

## 10.1 Separate score dimensions

  -----------------------------------------------------------------------
  **Dimension**                       **Meaning**
  ----------------------------------- -----------------------------------
  Direction                           Positive, negative, mixed, neutral
                                      or unknown for the company.

  Magnitude                           Estimated financial/operating
                                      significance, not merely headline
                                      size.

  Confidence                          Evidence quality, corroboration and
                                      mapping certainty.

  Novelty                             Whether the event is new versus
                                      already known or repeated.

  Horizon                             Immediate, days/weeks, quarterly,
                                      annual or long-term.

  Transmission strength               How directly and materially the
                                      event reaches company financials.

  Market pricing status               Potentially priced in, not
                                      obviously priced in or uncertain;
                                      state evidence.

  Risk/uncertainty                    Policy reversibility, operational
                                      execution, data gaps,
                                      counter-effects and liquidity.
  -----------------------------------------------------------------------

A high research-priority score means investigate, not buy. Store score
formula and version. Do not hide dimensions inside one composite number.

## 10.2 Opportunity categories

-   Early catalyst

-   Fundamental improvement

-   Policy beneficiary

-   Commodity beneficiary

-   Institutional activity

-   Valuation re-rating candidate

-   Technical confirmation

-   Recovery candidate

-   Speculative/high-risk

-   Negative catalyst / avoid or monitor

## 10.3 Valuation rules

-   Use P/E, P/B, dividend yield, EV/EBITDA and cash-flow methods only
    where suitable for the business model.

-   Compare with the company\'s own history and relevant peers; adjust
    for one-offs, cyclicality, capital structure and accounting periods.

-   Show conservative/base/optimistic scenarios and key assumptions;
    never manufacture a consensus target.

-   Use fully diluted shares and adjust for bonus/right issues,
    corporate actions, non-recurring gains/losses and reporting-period
    changes.

-   Flag stale prices, missing market cap, inconsistent fiscal periods
    and non-comparable peers.

# 11. Database architecture and data model

Use an event-centred relational schema with stable IDs, foreign keys,
migrations, indexes, idempotent writes and point-in-time records. A
source is stored once; an event can link to many companies; a media item
can mention many tickers/events.

  ------------------------------------------------------------------------
  **Table**                           **Purpose / representative fields**
  ----------------------------------- ------------------------------------
  companies                           Canonical PSX issuer master: ticker,
                                      legal name, aliases, sector,
                                      subsector, website, listing status,
                                      fiscal year end.

  company_aliases                     Ticker/name/brand/abbreviation
                                      aliases, language, validity dates,
                                      confidence and evidence.

  company_segments                    Business segments, products,
                                      geography, revenue share if
                                      disclosed and source evidence.

  sources                             Source name/type/domain/platform,
                                      reliability tier, access method,
                                      terms notes, update cadence and
                                      enabled status.

  source_items                        Canonical URL/external ID, source,
                                      title, published_at, event_date,
                                      collected_at, content hash,
                                      permitted text/location, language
                                      and access status.

  events                              Event type, headline, summary, event
                                      date, geography, status stage,
                                      direction, magnitude, novelty,
                                      horizon, confidence and lifecycle.

  event_revisions                     Versioned changes in event facts,
                                      status, interpretation and source
                                      updates.

  event_evidence                      Event/source link, excerpt, evidence
                                      type, verification state and
                                      supports/contradicts relation.

  event_companies                     Event/company link, exposure type,
                                      impact direction, channel,
                                      rationale, confidence and reviewer
                                      status.

  company_exposures                   Company, segment,
                                      input/market/geography/dependency,
                                      evidence source, validity period and
                                      last verified date.

  financial_metrics                   Company, period, metric, value,
                                      unit, currency, reported/estimated,
                                      source and calculation method.

  sector_metrics                      Sector/company, metric, period,
                                      value, unit, source and geography.

  commodity_prices                    Commodity, grade/contract, location,
                                      date, price, currency, unit, source
                                      and price type.

  funds                               Fund, AMC, category, benchmark,
                                      report period and AUM.

  fund_holdings                       Fund/company, report date, shares,
                                      weight, reported value, sector
                                      allocation and source.

  research_views                      Broker/analyst/channel, company,
                                      date, direction, target, horizon,
                                      assumptions, recommendation and
                                      source.

  analyses                            Event/company, analysis version,
                                      transmission, financial impact,
                                      confidence, risk, missing inputs,
                                      prompt/model/calculation version.

  alerts_predictions                  Alert, company/event, created_at,
                                      reference price/time, direction,
                                      horizon, confidence, thesis,
                                      invalidation and point-in-time
                                      snapshot.

  market_outcomes                     Prediction, evaluation date, stock
                                      return, benchmark/sector return,
                                      dividend-adjusted return, costs and
                                      outcome.

  media_accounts                      Platform, handle/channel ID, URL,
                                      display name, account type, identity
                                      verification, reliability tier,
                                      monitoring status and notes.

  media_items                         Platform, external ID, account, URL,
                                      published_at, collected_at,
                                      text/transcript pointer, language,
                                      content hash, transcript status and
                                      engagement snapshot.

  media_mentions                      Media item, company/ticker/entity,
                                      mention type, sentiment, claim type,
                                      context excerpt and relevance score.

  media_event_links                   Media item/event relation, evidence
                                      role, same-event/independent-source
                                      classification and confidence.

  media_predictions                   Author/account, company, direction,
                                      target, horizon, prediction date,
                                      assumptions, source item and
                                      eventual result.

  media_metrics_history               Media item/account, observation
                                      time,
                                      views/likes/reposts/replies/quotes
                                      where available.

  collector_runs                      Source/job, started/finished,
                                      status, items
                                      fetched/accepted/rejected, errors,
                                      quota usage and log reference.

  user_watchlist                      User-defined accounts, tickers,
                                      keywords, alert preferences and
                                      enabled status.

  schema_migrations                   Migration version, checksum, applied
                                      timestamp and result.
  ------------------------------------------------------------------------

## 11.1 Database engineering requirements

-   Use UTC internally and preserve source timezone/offset and original
    timestamp strings where supplied.

-   Use canonical URL and platform external IDs plus content hashes for
    deduplication; retain revisions instead of overwriting changed event
    stages.

-   Index ticker, event_date, published_at, collected_at, source_id,
    canonical_url, platform/external_id and status fields.

-   Use migrations, schema versioning, foreign keys, constraints and
    transactional writes where supported by Turso/SQLite.

-   Implement retention policies and compact storage; do not store full
    video/audio or large PDFs in the database.

-   Record provenance for every AI-generated claim and every numeric
    calculation.

-   Provide backup/export and tested restore process; never run
    destructive migrations without backup and approval.

# 12. Dashboard information architecture

  -----------------------------------------------------------------------
  **Page**                            **Core contents**
  ----------------------------------- -----------------------------------
  1\. Market Intelligence Home        Daily briefing, market regime,
                                      KSE-100 context, top verified
                                      events, sector pulse, commodity
                                      moves, major risks, catalysts and
                                      upcoming decisions.

  2\. News & Events                   Chronological deduplicated event
                                      feed, source evidence, event
                                      lifecycle, company mapping, filters
                                      and conflict display.

  3\. Opportunity Radar               Research-ranked candidates with
                                      catalyst, transmission, horizon,
                                      confidence, valuation,
                                      counter-evidence, liquidity and
                                      invalidation.

  4\. Company Research                Profile, segments, exposure map,
                                      financial statements, results,
                                      events, valuation, broker/media
                                      views and predictions.

  5\. Sector Intelligence             Operating indicators, peer
                                      comparisons, company-vs-industry
                                      trends, capacity, market share and
                                      drivers.

  6\. Commodities & Global Markets    Commodity/FX/rates/freight
                                      dashboards, benchmark metadata and
                                      company-specific exposure.

  7\. Institutional Intelligence      MUFAP/AMC holdings, fund
                                      allocation, AUM, flow caveats,
                                      broker research and report history.

  8\. Policy & Government Tracker     Institution, policy stage,
                                      timeline, source documents, next
                                      milestone, deadline and affected
                                      companies.

  9\. Domestic & Geopolitical Risk    Map/list of incidents, locations,
                                      severity, duration, verification
                                      and specific economic/company
                                      transmission.

  10\. Market Event Investigator      Unusual move queue, price/volume,
                                      disclosures, news, sector/benchmark
                                      comparison and likely explanation.

  11\. Scenario & Valuation Lab       Editable assumptions,
                                      sensitivities, fair value ranges,
                                      input provenance and missing-data
                                      warnings.

  12\. Social & Media Intelligence    Combined X and YouTube view with
                                      platform filters, account
                                      watchlists, relevant posts/videos,
                                      themes, mentions, predictions,
                                      disagreement and verification.

  13\. Alerts & Backtesting           Saved alerts, thesis snapshots,
                                      forward returns, false positives,
                                      missed catalysts and model/source
                                      performance.

  14\. Data Quality & Operations      Collector health, source freshness,
                                      failed jobs, quota use, database
                                      size, duplicate rates, LLM spend,
                                      unresolved review queue.
  -----------------------------------------------------------------------

UI standard: professional research-terminal presentation; calm
hierarchy; concise cards; consistent units; restrained colours; no
clutter; facts visually distinct from AI interpretations and estimates;
source links accessible; clear empty/loading/error states; mobile
usability; no placeholder numbers that resemble real data.

# 13. Repository structure

> psx-fundamental-intelligence/\
> ├── app.py\
> ├── pages/\
> │ ├── 1_Market_Home.py\
> │ ├── 2_News_Events.py\
> │ ├── 3_Opportunity_Radar.py\
> │ ├── 4_Company_Research.py\
> │ ├── 5_Sector_Intelligence.py\
> │ ├── 6_Commodities_Global.py\
> │ ├── 7_Institutional_Intelligence.py\
> │ ├── 8_Policy_Government.py\
> │ ├── 9_Geopolitical_Risk.py\
> │ ├── 10_Event_Investigator.py\
> │ ├── 11_Scenario_Valuation.py\
> │ ├── 12_Social_Media_Intelligence.py\
> │ ├── 13_Alerts_Backtesting.py\
> │ └── 14_Data_Quality.py\
> ├── collectors/\
> │ ├── base.py\
> │ ├── news/ psx/ policy/ commodities/ sector/\
> │ ├── mufap/ brokers/ youtube/ x/\
> ├── engines/\
> │ ├── deduplication.py relevance.py event_extraction.py\
> │ ├── verification.py company_mapping.py impact_analysis.py\
> │ ├── financial_calculations.py valuation.py\
> │ ├── opportunity_ranking.py social_trend_detection.py\
> │ └── backtesting.py\
> ├── database/\
> │ ├── connection.py schema/ migrations/ repositories/\
> ├── models/ prompts/ tests/ scripts/\
> ├── .github/workflows/\
> ├── requirements.txt pyproject.toml README.md .gitignore

# 14. Claude Code phased implementation plan

  -----------------------------------------------------------------------
  **Phase**                           **Scope and acceptance gate**
  ----------------------------------- -----------------------------------
  Phase 0 --- Specification and       Create new repository, README,
  repository bootstrap                architecture decision record,
                                      .gitignore, config example,
                                      requirements/pyproject, lint/test
                                      setup and workflow skeleton.
                                      Confirm no link to existing
                                      project. Acceptance: app skeleton
                                      starts; secrets absent; CI runs.

  Phase 1 --- Data foundation         Turso connection, migrations,
                                      repositories, source registry,
                                      company master for 30--50 tickers,
                                      aliases, event/evidence schema and
                                      tests. Acceptance: migrations
                                      repeat safely; CRUD, foreign keys,
                                      indexes and duplicate tests pass.

  Phase 2 --- First source collectors Implement 3--5 permitted high-value
                                      sources, preferably RSS/official
                                      feeds/API. Add canonicalisation,
                                      timestamps, hashes, rate limits,
                                      retries, run logs and fixtures.
                                      Acceptance: two runs are
                                      idempotent; URLs and dates
                                      traceable.

  Phase 3 --- Event extraction and    Strict structured LLM schema,
  verification                        evidence excerpts, source
                                      confidence, status stages,
                                      conflicting claims and model/prompt
                                      versioning. Acceptance: malformed
                                      JSON rejected; every claim cites
                                      source item; unknown stays unknown.

  Phase 4 --- Company exposure graph  Seed business segments and
                                      evidence-backed exposures; build
                                      candidate mapping and human review.
                                      Acceptance: correct direct/indirect
                                      links; unrelated companies excluded
                                      with reasons.

  Phase 5 --- Impact analysis and     Build transmission chains,
  Python calculations                 qualitative fallback, sourced-input
                                      financial calculators, sensitivity
                                      and missing-input handling.
                                      Acceptance: formulas tested with
                                      units; no unsupported quantitative
                                      estimates.

  Phase 6 --- Streamlit MVP           Home, news feed, event detail,
                                      company research and
                                      source/evidence display.
                                      Acceptance: responsive pages,
                                      filters, empty/error states and
                                      Turso integration.

  Phase 7 --- Scheduling and          GitHub Actions scheduled jobs,
  operations                          concurrency controls, logs,
                                      retries, alerts on failure, usage
                                      tracking and manual backfill.
                                      Acceptance: within quotas; reruns
                                      safe; failures visible.

  Phase 8 --- Corporate, policy and   PSX disclosures/results, official
  government modules                  policy sources, decision tracker
                                      and company financial statement
                                      intelligence. Acceptance: lifecycle
                                      stages and statement comparisons
                                      tested.

  Phase 9 --- Commodities, sectors    Build benchmark schema, sector
  and domestic/geopolitical risk      indicator collectors, geographic
                                      incident tracking, LPG calculator
                                      and company-specific transmission.
                                      Acceptance: units, locations, lags
                                      and source provenance tested.

  Phase 10 --- Institutional and      MUFAP/AMC holdings, reports and
  broker research                     authorised broker research. Include
                                      weight-vs-flow caveats and forecast
                                      tracking. Acceptance: report-period
                                      reconciliation and source access
                                      rules documented.

  Phase 11 --- YouTube and X          Add supplied watchlists, account
  collectors                          validation, official/authorised
                                      access, relevance filtering,
                                      transcript availability states, API
                                      quota controls, social schema and
                                      cross-platform clustering.
                                      Acceptance: irrelevant content
                                      filtered; exact handles preserved;
                                      unavailable transcript not falsely
                                      analysed.

  Phase 12 --- Valuation, scenario    Implement sector-appropriate
  and opportunity radar               valuation, sensitivities,
                                      transparent score dimensions, risk
                                      and thesis invalidation.
                                      Acceptance: calculation tests and
                                      stale/missing-data warnings.

  Phase 13 --- Market event           Investigate abnormal price/volume
  investigator and optional technical and allow independent/manual
  confirmation                        technical inputs. No integration to
                                      existing technical engine by
                                      default. Acceptance: explainable
                                      cause labels and no auto-trading.

  Phase 14 --- Backtesting, alerts    Point-in-time snapshots, forward
  and production audit                returns, bias checks, alert
                                      controls, backups, restore test,
                                      security and cost audit.
                                      Acceptance: reproducible replay and
                                      documented limitations.
  -----------------------------------------------------------------------

# 15. Claude Code operating prompts

## Prompt 1 --- Architect and specification audit

> You are the lead engineer for a new independent PSX Fundamental & News
> Intelligence Engine. Read the complete MASTER IMPLEMENTATION
> SPECIFICATION v2.0 before editing. This is separate from my existing
> technical engine: do not connect to or modify it. First inspect the
> repository and report the architecture, requirement traceability
> matrix, source-access risks, free-tier constraints, database plan,
> security model and phased implementation plan. Identify
> contradictions, missing decisions and items requiring my confirmation.
> Do not implement the entire platform. Wait for approval before
> changing files.

## Prompt 2 --- Build database foundation only

> Implement only the approved database-foundation phase. Use
> Turso-compatible SQLite SQL, migrations, stable IDs, foreign keys,
> indexes, repositories and tests. Include companies, aliases, segments,
> sources, source_items, events, revisions, evidence, event_companies,
> exposures, metrics, commodities, funds/holdings, research views,
> analyses, alerts/predictions, outcomes, media_accounts, media_items,
> media_mentions, media_event_links, media_predictions,
> media_metrics_history, collector_runs, user_watchlist and
> schema_migrations as specified. Do not add collectors or AI yet. Run
> tests and report exact files changed, migration output, test results
> and unresolved issues.

## Prompt 3 --- Implement one collector

> Implement one source collector only: \[SOURCE\]. Before coding, verify
> official API/RSS/permitted access and document terms, attribution,
> rate limits and retention constraints. Add fixture-based tests. Store
> source metadata, canonical URL/external ID, published_at, event_date
> if known, collected_at, content hash, access status and permitted
> text/excerpts. Make it idempotent with retry/backoff and collector
> logs. Do not scrape login/paywalled content or invent missing fields.
> Stop after this collector and report acceptance results.

## Prompt 4 --- Event extraction and evidence

> Implement structured event extraction for stored source items. Use a
> strict validated schema for event type, headline, summary, event date,
> publication date, geography, actors, institutions, candidate
> companies/tickers, sector, status stage, direction, magnitude,
> horizon, novelty, confidence, supporting excerpts, contrary evidence
> and missing information. Every factual assertion must point to a
> source item and excerpt. Separate facts from interpretation. Preserve
> conflicting reports and version model/prompt. Reject unsupported
> tickers. Do not issue buy/sell instructions.

## Prompt 5 --- Company mapping and impact

> Implement evidence-backed company exposure mapping and
> company-specific impact analysis. Never map by sector label alone. For
> each event/company pair show direct/indirect/uncertain exposure,
> segment, evidence, transmission through volume/price/input
> cost/FX/energy/logistics/regulation/financing/tax/capex/working
> capital, financial statement lines affected, horizon, confidence,
> counter-evidence, invalidation and missing inputs. Python calculates
> only with sourced inputs and explicit units; otherwise label
> qualitative. Add positive and negative test cases.

## Prompt 6 --- Social media intelligence

> Implement the Social & Media Intelligence module using the exact X and
> YouTube watchlists in the specification. Do not guess account
> identity. Validate profile metadata; keep ambiguous identity
> unconfirmed. Use official X API or authorised providers and permitted
> YouTube metadata/caption sources; do not bypass access controls. Add
> staged relevance filtering before LLM calls. Capture only PSX-relevant
> content, source IDs, timestamps, claims, tickers, themes, sentiment,
> predictions, engagement snapshots and event links. Distinguish fact,
> official statement, reporting, analysis, opinion, prediction, rumour
> and promotion. Deduplicate copied/syndicated content and do not count
> reposts as independent corroboration. Track unavailable transcripts
> honestly. Implement quotas, caching, budgets, tests and a manual
> review queue.

## Prompt 7 --- Dashboard quality

> Build only the Streamlit pages for modules actually implemented. Use a
> professional, consistent research-terminal layout. Separate facts,
> interpretations and estimates; show source links, timestamps,
> evidence, missing data and status. Avoid clutter, unexplained
> composite scores, duplicate metrics and fake placeholder values.
> Include filters, mobile layout, useful empty/loading/error states and
> query efficiency. Do not create decorative controls that do nothing.

## Prompt 8 --- Release and completeness audit

> Perform a requirements-based production audit against every section of
> the MASTER IMPLEMENTATION SPECIFICATION v2.0. Produce a traceability
> matrix with requirement, code location, test, status and evidence.
> Audit secrets, public repo history, source terms, API quotas,
> idempotency, event deduplication, timezone handling, logging, retries,
> LLM schema validation, unsupported claims, units, calculations, data
> freshness, Streamlit responsiveness, GitHub Actions quotas, Turso
> usage, backup/restore and backtesting bias. Classify issues
> critical/high/medium/low. Do not claim completion without passing
> tests. Fix only approved issues.

# 16. Testing and acceptance framework

-   Collector tests: reachable source, permitted access, canonical URL,
    timestamps, language, pagination, rate-limit handling, retry,
    deduplication and repeat-run behaviour.

-   Event tests: date extraction, stage distinction, geography, actors,
    direction, conflicting claims, source excerpts and unsupported
    ticker rejection.

-   Exposure tests: documented direct/indirect mapping, evidence
    freshness, unrelated-company exclusion and company-specific
    variation within sectors.

-   Calculation tests: currency, units, fiscal periods, tax, inventory
    lags, share count/corporate actions, finance costs, formula
    reproducibility and missing-input handling.

-   Social tests: exact handle/channel ID, identity validation,
    transcript unavailable state, relevance filtering, duplicate/repost
    handling, engagement snapshot time, author attribution, rumor
    labelling and prediction extraction.

-   Dashboard tests: source links, filters, page load, no fake values,
    empty/error states, access control and mobile layout.

-   Security tests: no secrets in Git history, least-privilege tokens,
    dependency audit, environment separation and no private research in
    public repo.

-   Operations tests: retries, timeouts, failed-job alerts, concurrency,
    idempotency, quotas, database size, backup and restore.

-   Backtest tests: point-in-time information, no look-ahead, adjusted
    prices/dividends, benchmark/sector comparisons, costs, liquidity and
    delisted-company survivorship.

# 17. Free-first cost and reliability controls

-   Start with 30--50 companies, 3--5 reliable news sources, a curated
    official-policy list and the supplied social accounts; expand after
    quality is proven.

-   Use RSS/official feeds where possible. Fetch incrementally using
    ETags/Last-Modified or provider cursors where supported.

-   Do not send every article, tweet or video transcript to an LLM.
    Apply source filters, keyword/ticker relevance, deduplication and
    event clustering first.

-   Cache extraction by content hash and prompt/model version. Reprocess
    only when content or schema materially changes.

-   Use cheaper deterministic rules for obvious exclusions and exact
    calculations; reserve LLM calls for ambiguity and synthesis.

-   Track X post reads/API spend, YouTube quota, LLM tokens/cost, GitHub
    Actions minutes, Turso rows/storage and collector failure rates.

-   Configure per-source polling intervals and daily budgets. Provide a
    kill switch and source-level enable/disable.

-   Keep large documents in permitted external storage; database stores
    metadata, excerpts, parsed values and references.

-   Do not assume a free tier will support continuous real-time
    monitoring. Prioritise high-value sources and sensible polling.

# 18. Governance, source quality and model safeguards

-   Every source has a registry entry: source type, owner,
    domain/platform, access method, terms, reliability tier, update
    cadence, last success and enabled state.

-   Every conclusion shows whether it is primary-source fact,
    independent reporting, expert opinion, social-media claim or model
    inference.

-   Use source reliability as a contextual factor, not an absolute truth
    score. Official accounts can be incomplete; media outlets can
    correct stories; commentators can be wrong.

-   Preserve original source URL and excerpt. Do not reproduce long
    copyrighted passages; store only permitted text and concise evidence
    snippets.

-   Do not treat virality, follower count, likes or repeated mentions as
    truth or investment quality.

-   Detect promotional language, undisclosed conflicts, coordinated
    amplification and influencer concentration where evidence supports
    it; label as signals, not accusations.

-   LLM output must be schema-validated; include uncertainty, evidence
    references, missing inputs, counter-evidence and prompt/model
    version.

-   Never use the LLM as the sole calculator, source verifier, ticker
    master or final investment authority.

# 19. First delivery milestone and definition of done

  -----------------------------------------------------------------------
  **Deliverable**                     **Definition of done**
  ----------------------------------- -----------------------------------
  Independent repository              New GitHub repo, README/spec,
                                      project instructions, CI and no
                                      connection to existing engine.

  Independent database                New Turso database, migrations,
                                      secrets and connection tests;
                                      backup plan documented.

  Company seed                        30--50 companies with validated
                                      ticker/name/sector and
                                      source-backed business summary.

  News MVP                            3--5 permitted sources, scheduled,
                                      deduplicated, timestamped and
                                      traceable.

  Event MVP                           Structured extraction with
                                      evidence, verification state,
                                      lifecycle and schema validation.

  Impact MVP                          At least selected company/event
                                      pairs show exposure, transmission,
                                      missing inputs and
                                      qualitative/quantitative label.

  Dashboard MVP                       Home, news/events, event detail and
                                      company research work on
                                      desktop/mobile.

  Operations                          Collector logs, failure visibility,
                                      quota tracking, repeat-run
                                      idempotency and backup/restore
                                      plan.
  -----------------------------------------------------------------------

Only after the MVP works reliably should the project expand into the
full 23-module scope. The YouTube/X account lists are included in the
requirements baseline now, but collectors should be activated only after
access, terms, identity and quota checks.

# 20. Final implementation rules

-   Evidence before opinion.

-   Company-specific exposure before sector labels.

-   Proposal is not approval; approval is not notification; notification
    is not implementation.

-   Quantify only when inputs, units, formulas and source provenance are
    available.

-   Separate event impact from stock attractiveness and valuation.

-   Treat social media as an early-warning and idea-discovery layer, not
    proof.

-   Use technical context as confirmation, not as a substitute for
    fundamental analysis.

-   Keep the existing technical engine untouched and credentials
    completely separate.

-   Build one dependable event-to-company pipeline before expanding
    source breadth.

-   Maintain a requirements traceability matrix and never claim a module
    is complete until implemented and tested.

# Appendix A --- unresolved identity/access checks

-   Donald Trump and Reuters were requested by name for X monitoring,
    but exact profile URLs/handles were not supplied in the confirmed
    list. Keep pending; do not guess.

-   \@ARNOfficiall may be the intended X profile for Abdul Rehman Najam;
    verify identity before linking it to the supplied YouTube channel.

-   Validate the identities of \@imemon15, \@AlphaWireHQ,
    \@Conflict_Matrix, \@MeherJazibAli and \@Asad_Ashah before assigning
    source reliability.

-   Confirm current X API plan, permitted endpoints, search coverage,
    post-read cost, rate limits and retention rules before activating
    collection.

-   Confirm YouTube API quota and transcript availability/access rules;
    a public video does not guarantee an accessible transcript.

# Appendix B --- build sequence at a glance

1.  Architecture and requirements traceability

2.  Independent GitHub/Turso/Streamlit scaffold

3.  Company master and event-centred schema

4.  First permitted news collectors

5.  Structured event extraction and verification

6.  Company exposure mapping

7.  Financial transmission and calculations

8.  Streamlit MVP

9.  Policy/corporate/sector/commodity/geopolitical sources

10. MUFAP and broker research

11. YouTube and X intelligence

12. Valuation, scenarios and opportunity radar

13. Market event investigation and optional technical confirmation

14. Alerts, backtesting, QA, backups and production audit

End of Master Implementation Specification v2.0. This document is the
project\'s controlling Claude Code handoff; update its version and
traceability matrix whenever scope or architecture changes.
