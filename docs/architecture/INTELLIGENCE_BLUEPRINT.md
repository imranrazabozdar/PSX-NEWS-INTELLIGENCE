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
