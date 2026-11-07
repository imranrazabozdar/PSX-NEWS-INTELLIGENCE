# Roadmap: Phases 4–14 (dependency-aware, PSX-independent first)

Prepared 2026-11-07. This is a planning document only; Phase 4 implementation has not started and
needs owner approval. The strategic rule (owner directive) is to build the whole intelligence
platform without depending on PSX website data, then plug a licensed provider (for example Capital
Stake or Mettis, under written agreement) into provider adapters when available.

**Legend:**
- **Data:**
  - **Free** = works on lawful public/official sources and owner-entered data;
  - **Provider** = needs licensed PSX market or disclosure data;
  - **Partial** = core works without PSX; specific features wait for a provider.
- **Status of inputs:** Phase 2 (PR #5) and Phase 3 (PR #11) are unmerged; the live LLM is NOT
  CONNECTED; no source is ACTIVE. Every phase below inherits these blockers until they are resolved.

## 1. Scope preservation: 24 modules and 15 pages
The master specification lists 23 modules (§3) and 14 dashboard pages (§12). Owner instruction adds
**Module 24, Global Energy & Oil Shock Monitor**, and a **15th page** for it. *Decision D1:
record both in `docs/SPECIFICATION.md` / ADR-0003 so traceability tests cover them.*

| # | Module | Phase(s) | Data |
|---|---|---|---|
| 1 | News Intelligence | 2–3 (done, unmerged), 6 | Free |
| 2 | Corporate Intelligence | 8 | **Provider** (PSX disclosures); Partial via company websites/SECP where permitted |
| 3 | Policy & Regulatory Intelligence | 8 | Free (official sources; several BLOCKED need channels) |
| 4 | Government Decision Tracker | 8 | Free |
| 5 | Domestic Stability & Geopolitical Risk | 9 | Free |
| 6 | International Contagion | 9 | Free (global indices/FX from permitted APIs) |
| 7 | Sector & Industry Intelligence | 9 | Free (PBS, industry bodies, company reports) |
| 8 | Commodity & Input-Cost Intelligence | 9 | Free (EIA API, World Bank Pink Sheet, owner-entered) |
| 9 | Dedicated LPG Intelligence | 9 | Free (OGRA notifications, Saudi CP via permitted source) |
| 10 | Mutual Fund & Institutional Intelligence | 10 | Free (MUFAP/AMC fund manager reports, terms permitting) |
| 11 | Broker Research Intelligence | 10 | Partial (authorised broker reports only) |
| 12 | Market Event Investigator | 13 | **Provider** (price/volume) |
| 13 | Company Relationship & Exposure Map | 4 | Free |
| 14 | Valuation & Fair Value | 12 | Partial (fundamentals from annual reports; market price needs provider or owner entry) |
| 15 | Investment Opportunity Radar | 12 | Partial (research ranking without price; liquidity needs provider) |
| 16 | Early Warning & Catalyst Tracker | 8 | Free |
| 17 | Scenario Simulator | 5, 12 | Free |
| 18 | Market Behaviour & Technical Confirmation | 13 | **Provider**; technical engine stays separate (ADR-0001) |
| 19 | Historical Event & Prediction Backtesting | 14 | Partial (event replay free; forward returns need provider prices) |
| 20 | Daily Briefing & Alerts | 7, 14 | Free (market section Partial) |
| 21 | Company Financial Statement Intelligence | 8 | Partial (annual/quarterly reports from company websites where permitted; PSX filings need provider) |
| 22 | YouTube & Financial Media Intelligence | 11 | Free within YouTube API quota (key needed) |
| 23 | X (Twitter) Intelligence | 11 | Paid API or authorised provider (owner purchase decision) |
| 24 | Global Energy & Oil Shock Monitor | 9 | Free (EIA API, OPEC/IEA where permitted, Phase 3 geopolitical events) |

| # | Page | Phase | Data |
|---|---|---|---|
| 1 | Market Intelligence Home | 6 (events), 7, 12 | Partial (KSE-100 context needs provider) |
| 2 | News & Events | 6 | Free |
| 3 | Opportunity Radar | 12 | Partial |
| 4 | Company Research | 6, 8, 12 | Partial |
| 5 | Sector Intelligence | 9 | Free |
| 6 | Commodities & Global Markets | 9 | Free |
| 7 | Institutional Intelligence | 10 | Free/Partial |
| 8 | Policy & Government Tracker | 8 | Free |
| 9 | Domestic & Geopolitical Risk | 9 | Free |
| 10 | Market Event Investigator | 13 | **Provider** |
| 11 | Scenario & Valuation Lab | 12 | Partial |
| 12 | Social & Media Intelligence | 11 | Free (YouTube) / paid (X) |
| 13 | Alerts & Backtesting | 14 | Partial |
| 14 | Data Quality & Operations | 6–7 | Free |
| 15 | Global Energy & Oil Shock Monitor | 9 | Free |

Rule for every page (CLAUDE.md, spec §12): a page is built only when its module is implemented;
empty states, never placeholder numbers.

## 2. Dependency graph
```
P2 collectors ─┬─> P3 extraction ─┬─> P4 exposure graph ─> P5 impact & calculators ─┬─> P12 valuation/scenario/radar
               │                  │                                                 │
               │                  └─> P6 Streamlit MVP <─ P4/P5 views               ├─> P13 investigator (Provider)
               └─> P7 scheduling/ops (needs ACTIVE sources + Turso secrets)          │
P3 ─> P8 corporate/policy/government ─┐                                             │
P3 ─> P9 commodities/sectors/risk/energy ┼─> P5 inputs (sector & commodity metrics) ─┘
P3 ─> P10 institutional/broker ────────┘
P3 ─> P11 YouTube/X (keys/purchase)
P5+P8–P12 ─> P14 backtesting, alerts, production audit (forward returns need Provider)
Provider adapter (any phase, once licensed) ─> P2 adapters, P8 disclosures, P12 prices, P13, P14 returns
```
Phases 8, 9, 10 and 11 can run in parallel after Phase 4, because each adds sources and metrics
through the same collector and extraction framework. Phase 5 consumes their metrics but is
designed with explicit "missing input" handling, so it does not wait for them.

## 3. Phase detail

### Phase 4 — Company exposure graph (Free)
- **Objective:** evidence-backed links from companies to segments, inputs, outputs, geographies,
  policies and counterparties. Each link is direct or indirect, and unrelated companies are excluded with a reason.
- **Database:** use the existing `company_segments`, `company_exposures` and `event_companies`. New
  additive migration: `exposure_candidates` (proposed links with evidence and a review state) and
  `exposure_reviews` (append-only owner decisions).
- **Engine:** an exposure taxonomy (commodity, FX, rates, tax, tariff, customer and supplier
  concentration, geography). The candidate generator takes Phase 3 entities plus annual-report excerpts and
  proposes links; the LLM proposes and Python verifies evidence quotes and alias resolution. An
  event-to-company matcher produces direct, indirect and excluded results, each with a reason. There is a human review queue.
- **Sources:** company annual reports and websites, where permitted. The company-master licensing
  question (Phase 1, PSX profile pages) remains open (D4).
- **LLM:** a new versioned prompt `exposure_candidate_v1` with a strict schema and quotes required.
- **Tests and acceptance (spec):** correct direct and indirect links; unrelated companies excluded with
  reasons; exposures differ by company within a sector; evidence freshness is tracked.

### Phase 5 — Impact analysis and Python calculations (Free)
- **Objective:** the 10-step event-to-company impact engine (§9). It covers transmission chains, a qualitative
  fallback, and calculators that only run on sourced inputs.
- **Database:** `analyses` (exists) plus additive `calculation_runs` (formula version, inputs with
  provenance, units, outputs, missing inputs).
- **Engine:** the transmission library (§7.1); unit- and currency-aware calculators (margin, cost pass-through,
  tax, tariff, FX, interest cost); sensitivity tables; a §9.1 report builder. It labels each result
  qualitative or quantitative and never estimates without sourced inputs.
- **LLM:** narrative only, from computed outputs; numbers are copied from Python results and checked.
- **Tests and acceptance:** formulas tested with units and fiscal periods; the §9.2 coal-price example reproduced;
  no unsupported quantitative estimate.

### Phase 6 — Streamlit MVP (Free)
- **Pages:** Home (events section), News & Events, event detail, Company Research (profile, exposures,
  events), Data Quality & Operations, and a review queue for Phase 3 and 4 human-review flags.
- **Requirements:** private and authenticated (owner decision C3), never public. Facts are visually distinct
  from AI interpretation. Every page has empty, loading and error states.
- **Database:** read-only views, with paginated, indexed queries inside the Turso budget.
- **Tests and acceptance:** Streamlit AppTest for every page; filters; empty and error states; Turso integration test.
- **Decision D5:** the authentication and hosting method, for example Streamlit Community Cloud private
  app or self-hosting. This affects cost.

### Phase 7 — Scheduling and operations (Free)
- **Scope:** scheduled collection, extraction and briefing jobs; concurrency; retries; failure
  alerts; usage tracking (Actions minutes, Turso, LLM spend); manual backfill with permission checks.
- **Blockers:** ACTIVE sources, GitHub Turso secrets and LLM connection.
- **Tests and acceptance:** within quotas; reruns are safe; failures are visible on the Operations page.

### Phase 8 — Corporate, policy and government modules (Partial)
- **Modules:** 2, 3, 4, 16 and 21.
- **Lifecycle tracker** (§8 stages): rumour → proposal → … → implementation, with deadlines and missed-deadline alerts.
- **Statement intelligence:**
  - structured financial statements from reports (`financial_metrics` exists);
  - period and restatement handling;
  - quarter-on-quarter and year-on-year comparisons.
- **Sources:**
  - Official sources: needs permitted channels for SBP, SECP and Commerce (currently BLOCKED).
  - PSX disclosures: only via a licensed provider (Capital Stake `pucars`/announcements API, Mettis MG Link) or written PSX permission.
  - Company IR pages: only where the terms permit.
- **Tests and acceptance:** lifecycle stages and statement comparisons.

### Phase 9 — Commodities, sectors, domestic/geopolitical risk, energy (Free)
- **Modules:** 5, 6, 7, 8, 9 and 24, with pages 5, 6, 9 and 15.
- **Scope:**
  - benchmark schema with unit, currency and lag metadata (`commodity_prices` and `sector_metrics` exist);
  - sector indicator collectors;
  - incident tracking with location, severity and duration;
  - LPG calculator;
  - oil-shock monitor (Brent/WTI via the EIA API, supply-disruption events from Phase 3, pass-through to petroleum prices and OGRA notifications).
- **Inputs:** an EIA API key (D3).
- **Tests and acceptance:** units, locations, lags and provenance.

### Phase 10 — Institutional and broker research (Free/Partial)
- **Modules:** 10 and 11, with page 7.
- **Scope:** MUFAP and AMC fund-manager-report parsing (PDF) with weight-versus-flow caveats; authorised broker reports only; forecast tracking in `research_views`.
- **Tests and acceptance:** report-period reconciliation; access rules documented per AMC and broker.

### Phase 11 — YouTube and X (keys/purchase)
- **Modules:** 22 and 23, with page 12.
- **Scope:** the supplied watchlists with exact handles; account validation; official API only; quota controls; transcript availability states (never analyse a missing transcript); cross-platform clustering with Phase 3.
- **Decisions:** a YouTube API key (free quota) and an X API purchase (D6). No scraping.
- **Tests and acceptance:** irrelevant content is filtered and handles are preserved exactly.

### Phase 12 — Valuation, scenario and opportunity radar (Partial)
- **Modules:** 14, 15 and 17, with pages 3, 11 and the Company Research valuation tab.
- **Scope:** sector-appropriate valuation (DCF, DDM, P/B for banks, EV/EBITDA); editable scenarios with provenance; separate score dimensions (§10.1); counter-evidence and invalidation.
- **Market price input:** licensed provider, or owner-entered with a timestamp and a clear label.
- **Constraints:** no buy or sell instructions.
- **Tests and acceptance:** formulas, sensitivities, and stale or missing data warnings.

### Phase 13 — Market event investigator, optional technical confirmation (Provider)
- **Modules:** 12 and 18, with page 10.
- **Scope:** abnormal price and volume queue, joined to disclosures and news, with explainable cause labels.
- **Inputs:** technical inputs are manual or independent only. There is no link to the existing technical engine (ADR-0001) and no auto-trading.
- **Blocker:** a licensed PSX price and volume feed. Until then only an owner-entered or uploaded file path can be built and tested.

### Phase 14 — Backtesting, alerts and production audit (Partial)
- **Modules:** 19 and 20, with page 13.
- **Scope:** point-in-time snapshots; replay of events and predictions; forward returns (needs provider prices); bias checks; alert controls; backup and restore test; security and cost audit.
- **Tests and acceptance:** reproducible replay and documented limitations.

## 4. What proceeds without PSX data
- **Fully:** Phases 4, 5, 6, 7, 9, 11 (YouTube) and 10 (MUFAP/AMC, subject to terms).
- **Mostly:** Phases 8, 12 and 14.
- **Provider required:**
  - Phase 13;
  - PSX disclosures (Module 2);
  - live prices and the KSE-100 context;
  - liquidity in the radar;
  - forward returns in backtesting;
  - Module 18.

Every provider-dependent feature uses a `MarketDataProvider` / `DisclosureProvider` adapter
interface with an offline fixture implementation. A licensed provider is a new adapter, not a redesign.

## 5. Owner decisions needed
| ID | Decision | Needed by |
|---|---|---|
| D1 | Record Module 24 and page 15 in the specification | Before Phase 9 (recommended now) |
| D2 | LLM go-live: `anthropic` SDK dependency, `PSXNI_ANTHROPIC_API_KEY`, daily budget | Before live Phase 3 runs, and Phases 4–5 LLM use |
| D3 | EIA Open Data API key (free) | Phase 9 |
| D4 | Company-master licensing question (PSX profile pages read once in Phase 1) | Before production use |
| D5 | Dashboard authentication and hosting | Phase 6 |
| D6 | X API purchase or authorised provider; YouTube API key | Phase 11 |
| D7 | Licensed PSX provider agreement (Capital Stake / Mettis): scope, cost, redistribution terms | Phases 8, 12–14 provider features |
| D8 | Publisher terms approvals or permission requests, so sources can become ACTIVE | Phase 7 onward |
