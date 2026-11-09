# M5 valuation: existing functionality, gaps and implementation plan

Status: **M5 is not validated on real data.** The OGDC documents contain no market price, share-count history or
forecast, so no valuation output has been produced from them. Nothing here is a price target.

## 1. Existing functionality (engines/valuation.py)

| Method | State | Requirement | Gap |
|---|---|---|---|
| P/E (trailing) | Implemented | Price (stored SCS daily close) and reported EPS | Real-data not tested; not_applicable for loss-making periods |
| P/B | Implemented | Price, shares, total equity | Real-data not tested |
| EV/EBITDA | Implemented; not applicable to banks and insurers | Market capitalisation, net debt, EBITDA | EBITDA definition not standardised; no net-debt validation |
| Dividend yield | Implemented | Owner-recorded cash dividends and price | Real-data not tested |
| Forward P/E | Blocked | Consensus EPS (open decision U6) | No approved source; always insufficient_data |
| DCF | Implemented with an explicit owner basis | Declared basis FCFF (WACC) or FCFE (cost of equity), forecast, growth | Forecast engine not built (see CFA design F4); the owner supplies the cash-flow path |
| DDM and justified P/B (banks) | Implemented from owner assumptions | Low, base, high assumptions | No assumption source; sensitivity grid only |
| Point-in-time inputs | Implemented | Price and fiscal metrics dated on or before the as-of date; filing date checked | Comparative balances now promotable (controlled rule) but only at fiscal year-ends |

## 2. Gaps against the CFA-style requirements

1. **Scenario valuation (bear, base, bull) for every method.** Only the DDM and justified P/B produce conservative,
   base and optimistic values. Multiples and DCF need the same structure.
2. **Fair-value range and margin of safety.** Not produced. A range requires the scenario set and a stated reference
   price with its date.
3. **Sensitivity analysis.** Exists for the DDM and justified P/B grid; not for multiples or the DCF growth/discount grid.
4. **Insurance valuation.** No method. Insurers need book-value and earnings methods with capital considerations and
   appropriate solvency inputs, none of which is in the current data.
5. **Forecast-driven DCF.** Requires the forecasting layer (CFA design F4), which is not built.
6. **Valuation date and data staleness.** The price date and the fiscal-metric period are recorded; a rule that refuses a
   target when either input is stale is not implemented.
7. **Forward P/E.** Blocked by open decision U6 (consensus source). Internal scenario estimates must not be presented as
   consensus.

## 3. Implementation plan (next batches, dependency order)

1. Scenario framework: a bear/base/bull assumption set per method, recorded with its source and date, applied to the
   existing multiples and DCF. No target is issued.
2. Range and margin of safety: from the scenario set and a dated reference price, with the price age recorded.
3. Sensitivity grids for the DCF (discount rate against terminal growth) and multiples (multiple against EPS).
4. Staleness rule: refuse a range when the price or the fiscal inputs are older than the documented limits.
5. Forecast layer (F4) feeding the DCF with explicit driver assumptions per sector.
6. Insurance valuation method, only after insurer documents exist and are verified.

## 4. Blockers

- No real market price, share-count history or forecast in the owner's OGDC documents.
- Open decision U6 (consensus source) for forward P/E.
- Insurer documents are not available (no insurer in the current seed).
