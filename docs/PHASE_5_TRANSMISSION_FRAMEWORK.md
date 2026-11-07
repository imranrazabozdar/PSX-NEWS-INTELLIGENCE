# Phase 5 economic transmission framework (design)

Implements spec §7.1 as versioned deterministic chains.

Ground rules:
- **A chain applies to a company only through its own documented exposure** (Phase 4
  `exposure_candidates_current`), never through sector membership alone.
- **No company-specific sensitivity is hardcoded.** Sensitivities come from sourced `financial_metrics`
  or remain qualitative.
- **"Expected direction" applies only when the trigger's change is stated and the exposure is
  documented.** Otherwise the direction is unknown.

## 1. Mechanisms
| # | Trigger variables | Transmission chain | Required company exposure | Expected direction (if supportable) | Reversing / weakening conditions | Required evidence | Direct / indirect | Confidence limits |
|---|---|---|---|---|---|---|---|---|
| T1 Oil price | Brent/Arab Light change; PKR/USD | crude cost → refinery margin (crack spread), inventory gain or loss with lag; E&P realised price; OMC inventory valuation and margins (regulated) | refiner buys crude; E&P sells crude/condensate; OMC holds product inventory; consumers use fuel | E&P: + on rise; refiner: **mixed** (cost vs inventory gain, product prices); OMC: **mixed**/unknown (regulated margins, inventory); fuel users: − | price pass-through via OGRA; hedging; inventory accounting; crack spreads; PKR moves | benchmark price (sourced), company exposure, regulated-price notification | Direct (E&P, refiners); indirect (users) | low without margin data |
| T2 Gas / RLNG and circular debt | regulated gas price notification; RLNG price; circular-debt settlement | feedstock and fuel cost → margins; utility allowed returns; receivables recovery and liquidity | gas as feedstock (fertiliser) or fuel; gas utility; producers with government receivables | feedstock user: − on rise unless pass-through; producer: + on rise; settlement of receivables: + liquidity | subsidised feedstock regimes; pass-through orders; delayed payment | notification text, company exposure, receivable disclosure | Direct | medium only with notification + exposure |
| T3 Interest rates | SBP policy rate decision | floating-rate debt → finance cost; banks: asset and deposit repricing → NII; demand via credit | KIBOR-linked borrowings; bank balance-sheet repricing data | borrower: − on rise; bank: **unknown** without repricing gap data | fixed-rate debt, hedges, deposit mix, lags | MPS statement; company debt terms | Direct | banks low until repricing data exists |
| T4 PKR exchange rate | PKR/USD level change | import costs; FX debt revaluation; export revenue translation; receivables/payables | documented import share, FX debt, FX revenue | exporter: +; importer: −; FX debt: − on depreciation | pricing power, hedging, natural hedge, pass-through | FX data (sourced), company FX disclosures | Direct | medium with disclosure; else low |
| T5 Inflation, tax and duties | CPI release; budget/SRO/duty notification | input costs, demand, pricing; tax on product or input | product or input named **within the notification's scope** | taxed product: − unless pass-through; protected domestic producer: + (only if documented) | notification vs implementation stage; exemptions; pass-through | notification text (stage), scope match | Direct (scope) | low until stage = notification or implementation |
| T6 Electricity tariffs | NEPRA determination; tariff notification | energy cost for energy-intensive users; power producers' tariff | documented energy intensity; tariff-regulated producer | heavy user: − on rise; producer: per determination | captive power; fuel mix; determination vs notification | determination text; exposure | Direct (producers), indirect (users) | low without energy cost share |
| T7 Global commodities (coal, urea, steel, cotton…) | benchmark of the **specific grade and location** | input cost → COGS with inventory lag; output price for producers | documented buyer/seller of that benchmark (spec §9.2: coal and cement) | buyer: − on rise; seller: + | grade mismatch; local vs imported mix; freight; FX | benchmark (grade, date, source); company fuel/input mix | Direct | per §9.2: qualitative unless inputs exist |
| T8 Geopolitical, shipping, supply | conflict, chokepoint, border or port closure, sanctions | freight and insurance cost; delivery delays; lost production or exports; energy security | **location- or route-specific** exposure (spec §7.1) | affected route users: −; alternative suppliers: unknown | duration, rerouting, inventory buffers | verified event (Phase 3), route/location exposure | Direct (route), indirect (energy) | low; duration often unknown |
| T9 Fiscal policy, borrowing, IMF | budget, IMF review, borrowing announcement | tax measures, subsidies, development spending, rates and liquidity | sector or company named in measures; government receivables | per measure; often **mixed** | negotiation stage; implementation lag | official documents (stage) | Mostly indirect | low; stage-dependent |

Module 24 (Global Energy & Oil Shock Monitor; PR #13, unmerged) would reuse T1, T2, T7 and T8. This
framework is compatible with it and does not depend on it.

## 2. Direction rules
- The sign comes from: the change direction stated in the event × the documented exposure role
  (buyer/seller/borrower…) × the mechanism sign.
- **If any factor is unknown, the direction is unknown.**
- When a company has several mechanisms with opposite signs, its aggregate is **mixed**. Opposites are
  never netted without quantified inputs.
- `neutral` only when the evidence says there is no material effect (for example, an exemption covers
  the company).

## 3. Magnitude (separate from confidence)
| Level | Qualitative basis (default) | Deterministic or quantified basis (only with sourced inputs) |
|---|---|---|
| low | indirect exposure, minor input share, or a long lag | modelled effect < threshold A of the relevant line |
| medium | direct exposure with a moderate documented share | between A and B |
| high | direct exposure to a core input or revenue line, with a large stated change | ≥ B |
| not_assessable | inputs missing | — |

Thresholds A and B are a **versioned policy choice** (proposed initial values: 2% and 10% of the
affected line, for review). They are not a statistical finding.

## 4. Scenarios (qualitative framing in Phase 5; editable simulator in Phase 12)
- **Base:** the stated change persists at the stated level for the assumed horizon.
- **Optimistic and adverse:** pass-through, duration or lag assumptions varied within stated bounds,
  each listed.
- Each scenario carries direction, magnitude level and assumptions. **Scenarios are not forecasts or
  price predictions.**

## 5. Horizons
| Horizon | Range | Typical mechanisms |
|---|---|---|
| short | within one quarter | FX revaluation, inventory gains/losses |
| medium | 1–4 quarters | cost pass-through, finance-cost repricing |
| long | more than 1 year | capacity, demand, structural policy |
| unknown | — | mechanism timing not documented |
