# CFA-style financial analysis layer: design and status

This layer is a rigorous, transparent, evidence-based analysis engine inspired by established financial-analysis
methods. It is **not** a CFA-certified analysis, it does not replace professional investment judgement, and it issues no
buy or sell instruction. Its outputs are analytical classifications with their evidence.

It reuses the existing architecture: `engines/financials.py` (reported figures), `engines/fundamentals.py` (ratios),
`engines/valuation.py` (M5), `engines/sector_applicability.py` (applicability) and `engines/earnings_quality.py`
(review indicators). No duplicate engine is built.

## Status by layer

| Layer | Scope | Implemented | Synthetic-tested | Real-data tested | Manually verified | Not yet |
|---|---|---|---|---|---|---|
| F1 Statement analysis | Three-statement relationships, margins, working capital, liquidity, leverage | Ratios and reconciliation exist (M3) | Yes | OGDC interim (one company, one quarter) | Yes (35 figures + hand ratios) | Full three-statement narrative; revenue-recognition policy changes |
| F2 Earnings quality | Growth gaps, cash conversion, accrual ratio | `engines/earnings_quality.py` (cash conversion, growth gap, accrual, like-period growth) | Yes (hand-calculated) | Not yet (needs prior-period balances and multi-period cash flows) | No | Red-flag set beyond these four; related-party and provision analysis |
| F3 Trends | Year-over-year, like-period growth, margins over time | `yoy_growth` refuses mixed period types | Yes | No (one comparable period only) | No | Multi-year series, dividend and share-count history, restatement handling |
| F4 Forecasting | Driver-based revenue, margin, cash-flow model by sector | Not built | — | — | — | Entire layer; sector drivers designed in the applicability matrix only |
| F5 Valuation | M5 | Multiples, DCF (owner basis), DDM and justified P/B (owner assumptions) | Yes | No (no price or forecast in documents) | No | See `M5_VALUATION_GAP_ANALYSIS.md` |
| F6 Governance and capital allocation | Dividends, related parties, auditor qualifications | Dividend declarations are visible in the announcement text only | No | No | No | Extraction of related-party tables, auditor reports, capital-allocation analysis |
| F7 Investment thesis and risk | Classifications: strong, improving, cyclical recovery, value, expensive growth, distressed, speculative, insufficient evidence | Not built | — | — | — | Entire layer; requires F1–F6 evidence |

## Principles applied

- Every figure carries source, period, scope, unit and page (through the existing provenance).
- Missing values stay missing (`insufficient_data`, `not_computable`, `not_checkable`); they are never zero.
- Annual and quarterly values are not compared or mixed; interim ratios are annualised only with a stated basis.
- Indicators are reviewable flags with alternative explanations and the further evidence needed. A ratio alone never
  supports an accusation of misconduct or distress.
- Sector applicability decides which measures are meaningful (see `sector_applicability.py`).

## Next implementation steps (in order)

1. Multi-year series ingestion for one company (requires more verified annual documents, owner-provided).
2. Prior-period receivable and inventory balances, to make the growth-gap indicators calculable on real data.
3. Driver-based forecast layer (F4) with explicit assumptions and their sources, for one sector first.
4. Scenario and range layer for valuation (M5 gap plan).
5. Governance extraction (F6) from owner-provided reports.
