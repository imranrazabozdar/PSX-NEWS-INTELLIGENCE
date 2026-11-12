# PSX Intelligence: architecture blueprint

Status: DESIGN RECORD. Documentation only. No runtime behavior is defined by this file. Each build phase needs
separate owner approval before it starts. Current state of every item is in `docs/STATUS.md`.

## Purpose

A private, local, legitimately sourced research terminal. For every watchlist company it maintains a living
understanding, and it reasons about events the way a disciplined analyst would: without missing a filing or a
flow, without bias, and with every claim grounded and traceable.

It does not predict prices. It never issues buy or sell instructions. Its edge is completeness, consistency,
memory, and honesty.

## Layered architecture (data to intelligence)

### 1. Data layer (legitimately sourced, private, attributed)

- **Investify (consented):** fundamentals, company profile, competitors, announcements (including insider,
  material, corporate actions, meetings, briefings), and news (pending owner confirmation of scope).
- **Macro factors (free primary sources):** oil prices, SBP policy rate and FX reserves, IMF, budget, and power
  and other policy items.
- **Market flows (public, legitimately sourced):** FIPI and LIPI, traded volume, end-of-day settlements.
- **Technicals:** OHLCV price and volume bars.
- **Sources policy:** free and legitimately accessible sources only. No paid X API. No disallowed scraping.
- **Manual paste intake (macro and analyst takes):** the owner pastes an analyst take or commentary. The system logs
  the paste with its date and source, classifies it, and stores it as UNVERIFIED signal. It is never promoted to fact.
- **Deep reports (owner uploads):** audited statements, stored in the financial archive as verified facts.

### 2. Exposure map (per company)

Built from deep reports and profiles. It is the vulnerability profile that drives transmission reasoning:

- geographic footprint (plants, ports, cities; for example, north or KPK);
- supply chain and trade routes (imports and exports, and which borders);
- commodity exposure (oil, LPG, coal);
- rate and FX sensitivity;
- customer concentration;
- sector.

Every attribute is traced to a source. Where a magnitude is an estimate, it is labelled as an estimate.

### 3. Dossier (per company)

Static facts, financial time series, baselines and norms, narrative threads, and expectations. A new item is
interpreted against this context: beat or miss, deviation from expectation, or update to a thread.

### 4. Macro-factor layer

Each factor is a dated series or event with its source. Factors link to stocks through the driver model, and
the weights differ from stock to stock.

### 5. Market-flow layer

FIPI, LIPI, volume, and settlements. This is the reality check: what is actually happening in the market.

### 6. Event-transmission engine

Given an event (political, security, natural, monetary, fiscal, sector policy, commodity, or global market):

1. trace the channels the event travels through;
2. find the companies whose exposure matches each channel;
3. rank them by exposure intensity ("who is most affected, and why");
4. give the direction, capturing both positive and negative effects and any offsets;
5. state the confidence and "what would make this wrong".

The output is a reasoned hypothesis, never a certainty.

### 7. Composite and divergence engine

Combines company, sector, macro, flows, and technicals. The combination is driver-weighted and
interaction-aware, not a naive sum. The core output is divergence detection: where the narrative
(fundamentals and events) and the money (FIPI, LIPI, accumulation or distribution) disagree.

The transmission engine proposes a hypothesis, and the flow layer tests it. The system reasons first, then
verifies against real flows.

### 8. Scenario and forecast engine

Bull, base, and bear scenarios per stock. Each combines the driver-based earnings path, a valuation range, the
catalyst calendar, technical positioning, and macro state. Each scenario has named swing factors and rough
probabilities.

### 9. Dashboard (private local app only)

A watchlist ranked by composite weight of evidence, presented as a ranked screen with its reasoning. For each
name it shows the score breakdown, the scenario, divergence flags, and the transmission chain.

It is framed as descriptive evidence: "screens strongest or weakest on X, Y, and Z; here is why, and what would
flip it." It is not an order. The human decides.

## Cross-cutting guardrails (non-negotiable, every layer)

- **Legitimacy:** consent-respecting; robots and rate caps honored; no disallowed scraping; private retention;
  attribution on every Investify-sourced figure.
- **Separation:** three databases (operational and news, financial archive, technical) never cross. Nothing is
  written to production or Turso without explicit approval.
- **Grounding:** every figure traces to a source or a stored number. Verified facts (disclosures, statements) are
  kept separate from unverified signal (news, commentary).
- **No buy or sell** anywhere. Forecasts are probabilistic scenarios with stated conditions, never point
  predictions.
- **Estimates:** every estimate is labelled with its assumptions. Observation is separated from inference.
  Confidence and "what would break this" are always stated.
- **Phased and gated:** build one layer, prove it on HUBC, then stop for owner approval. No scaling without
  approval.

## Build sequence (each step needs separate owner approval before it starts)

| Phase | Scope | State |
|---|---|---|
| 1 | Investify ingestion: insider, material, corporate actions, and meetings; notable-events routing; News behind its consent flag. Closes with the HUBC filter-count and insider checks (scheduled, trading window). OCR is a separate small task. | In progress; closes Friday |
| 2 | Free macro-factor feed | Approved-pending |
| 2b | Market-flow layer: FIPI, LIPI, settlements | Approved-pending |
| 3 | Dossier, exposure map, baselines, threads, screening signals (HUBC is the reference) | Approved-pending |
| 4 | Scale across the validated watchlist (background, cap-gated) | Approved-pending |
| 5a | Event-transmission engine | Approved-pending |
| 5b | Composite and divergence engine | Approved-pending |
| 5c | Scenario and forecast engine | Approved-pending |
| 5d | Ranked, reasoned dashboard | Approved-pending |

## Recorded owner decisions

- **OCR:** recommended as a small dedicated phase. It is free, and it is needed for image disclosures and for
  scanned or vector-outline filings. Until it is approved, an image disclosure is stored as
  `image_disclosure` with `machine_readable: false`, and no field is guessed from it.
- **News:** off until Investify confirms that news is within the consent scope.
- **Phases 2 to 5:** approved-pending. Each one starts only on explicit owner approval.

## Technicals engine (Phase 5b input)

Reads OHLCV bars and computes:
- **Accumulation and distribution:** on-balance volume (OBV), the accumulation/distribution line, and the volume trend.
- **Support and resistance:** levels from repeated price and volume reactions.
- **Fundamental-versus-technical divergence:** for example, good fundamentals with persistent distribution is a
  caution flag, and weak fundamentals with accumulation is a watch flag. The flag shows its criterion and its values.

Technicals describe the tape. They never produce a buy or sell signal on their own.

## Tiered understanding model (coverage without deep-diving every company)

The watchlist has about 110 companies. Deep research on each is not required.

**Tier 1: baseline understanding of every watchlist company, automatic.** No report upload is needed. It is derived
from the auto-collected Investify profile (business description, sector, geography hints), competitors, and
fundamentals. That is enough for first-pass transmission reasoning: routing an event to sectors and companies, and
flagging the likely affected ones. Each Tier 1 output states its confidence as baseline, and notes where deeper data
would sharpen it.

**Tier 2: deep understanding for roughly 10 to 20 owner-priority names, from uploaded reports.** This is the precise
exposure map: specific plant locations, trade routes, debt and FX structure, and customer concentration. It answers
"who is affected most, and exactly how." Any name can be deepened on demand when an event makes it matter.

**Learning from news.** Exposures are enriched over time from the news and announcement flow. For example, a flood
item that names a company's northern plant teaches the system that exposure. Understanding grows from the flow, not
only from PDFs.

**Operating guidance.** Seed deep dives for the five to ten core names first. The other roughly 100 run on the
automatic Tier 1 layer, and Tier 2 expands gradually. No one needs to upload 100 reports.

## Knowledge base ("the brain"): distilled, compact, learning

**Store distilled knowledge, not documents.** Per company, the knowledge base holds verified facts, the exposure map,
computed baselines and norms, live narrative threads, relationships (peers, supply chain), and reasoned
interpretations. All of it is compact: numbers and short text.

**PDFs never enter Turso.** A report is processed once. The raw file lives in the cheap vault, or it is discarded
after extraction with its provenance kept. The operational and analytical database never carries heavy documents.
This is what keeps Turso lean.

**Reasoning reads the brain, not the PDFs.** Once a document is distilled, the system does not reopen it. It reasons
from the knowledge base, which is fast and light.

**It accumulates and learns.** Each new report, news item, insider filing, or event updates the relevant part of the
brain: a corrected fact, a revised baseline, a new exposure, an updated thread, or a sharper interpretation.
Understanding compounds over time.

**Honesty (non-negotiable).** Verified facts (from filings and statements) and derived interpretations (reasoned
conclusions) are stored separately, and each is clearly labelled. A derived item stays traceable to its basis and is
never promoted to fact. Confidence and sources travel with every stored item.

## Illustrative transmission examples (reasoned hypotheses, to be tested against flows)

These show the pattern the engine reasons with: event, then channel, then exposed companies ranked by intensity, then
direction and why, then confidence, then verification against flows. Reason first, then verify.

1. **Political unrest or road closures.** Channel: inter-city logistics and supply routes. Exposed: logistics-
   dependent names, and companies with a northern footprint. Direction: negative for exposed names; possible positive
   for an alternative route owner. Confidence: low to moderate, and the event's duration is the main unknown. Verify:
   flows and volume in the affected names.
2. **Open-market operations or T-bill injection.** Channel: bank liquidity and yields. Exposed: banks with large
   government-securities books. Direction: mixed, depending on the yield path. Confidence: moderate, if the injection
   size and tenor are known. Verify: FIPI and bank volume.
3. **Global market crash.** Channel: foreign portfolio outflow (FIPI). Exposed: PSX names with high foreign ownership.
   Direction: negative, with liquidity and valuation effects. Confidence: moderate. Verify: FIPI and settlements, not
   the price move alone.
4. **Housing-loan policy change.** Channel: construction and lending demand. Exposed: cement, steel, and construction
   names, and the lending banks. Direction: positive for demand-linked names, with a possible credit-quality effect on
   banks. Confidence: low to moderate. Verify: sector volume and the company's own disclosures.

## Completeness pass (this section records what each checklist item maps to)

| Element | Where it is recorded |
|---|---|
| Data layer: Investify fundamentals, profile, competitors, announcements (insider, material, actions, meetings), news | Layer 1; Phase 1 |
| Data layer: macro factors (oil, SBP rate, FX reserves, IMF, budget, policy), free sources only | Layer 1; Phase 2 |
| Data layer: market flows (FIPI, LIPI, settlements, volume) | Layer 1; Layer 5; Phase 2b |
| Data layer: technicals (OHLCV) | Layer 1; Layer 7; Phase 5b |
| Data layer: deep report uploads into the archive | Layer 1; Tiered model; Knowledge base |
| Tiered understanding model | Tiered understanding model |
| Knowledge-base "brain": distilled, PDFs never in Turso, learns, verified vs derived | Knowledge base |
| Exposure map: geography, supply chain and trade routes, commodity, rate and FX, customer concentration, sector | Layer 2 |
| Dossier: static facts, time series, baselines, threads, expectations; context-aware ingestion (beat or miss, deviation, thread update) | Layer 3; Phase 3 |
| Macro-factor layer linked to stocks through the driver model (per-stock weights) | Layer 4 |
| Market-flow layer as the reality check; reason, then verify | Layer 5; Layer 7 |
| Event-transmission engine: channels, exposure, ranked by intensity, both directions and offsets, confidence and what breaks it, hypothesis not certainty | Layer 6; Transmission examples; Phase 5a |
| Composite and divergence engine: driver-weighted, interaction-aware, narrative versus money | Layer 7; Phase 5b |
| Scenario and forecast engine: bull, base, bear; swing factors; probabilities | Layer 8; Phase 5c |
| Technicals: accumulation and distribution, support and resistance, divergence | Layer 7; Phase 5b (technicals engine) |
| Dashboard: ranked, reasoned, descriptive, not buy or sell; score breakdown; scenario; divergence flags; transmission chain | Layer 9; Phase 5d |
| Guardrails: legitimacy (consent, robots, caps, no scraping, private, attribution); three-database separation; grounding; verified versus derived; no buy or sell; probabilistic, not prediction; estimates labelled; observation versus inference; confidence and what breaks it; reason, then verify; phased and gated; prove on HUBC | Cross-cutting guardrails |
| Build sequence Phases 1 to 5, including 5a, 5b, 5c, 5d | Build sequence |
| Decisions: OCR (small future phase; image_disclosure fallback until approved); News off until consent; per-phase approvals; free sources only (no paid X API, no disallowed scraping) with a manual paste intake | Recorded owner decisions; Phase 2 (manual intake) |

**Gaps closed by this pass:** the manual paste intake for analyst takes, and the technicals engine (5b), which were
mentioned only in passing before, are now stated in the sections above.

**Status of this blueprint:** complete as of this pass. It is a design record only and changes no runtime behavior.
