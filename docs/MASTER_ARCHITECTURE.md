# PSX Investment Intelligence — master architecture

Status: DESIGN (main `012a6bf`, 2026-11-08). Nothing in this document is implemented unless it is marked
EXISTS. This is the definitive description of the target system. Companion documents:
`MASTER_IMPLEMENTATION_PLAN.md` (milestones M0–M10), `MASTER_DATA_SOURCE_REGISTER.md`, `MASTER_DATABASE_DESIGN.md`,
`MASTER_VALIDATION_STRATEGY.md`, `MASTER_SECURITY_AND_OPERATIONS.md`. Where they overlap, this document defines the
concepts and the companions define the detail.

## 1. Starting point (verified at `012a6bf`)

| Area | State | Evidence |
|---|---|---|
| Collection: RSS metadata (10 feeds), SCS OHLCV 1m/1h/4h/1d, single-writer orchestration, calendar, gaps | EXISTS, merged; **operational acceptance pending** | `COLLECTION_ORCHESTRATION.md`; Turso lease verified 2026-11-08 |
| Events: headline builder, classification (23 types, 14 stages), entities, evidence independence | EXISTS (offline-tested; not run in production) | PRs #33–#35 |
| Exposure (Phase 4) and T1–T9 impact (0009), scenarios, revalidation, review, validation harness, dashboard, reports | EXISTS (offline-tested; not run in production) | PRs #36–#37 |
| Company master | **51 companies** (seed) | `database/seed/companies.json` |
| Financial statements, valuation, macro series, portfolio | **NOT IMPLEMENTED**; some tables reserved (0003) but empty | `MASTER_DATABASE_DESIGN.md` §1 |
| Human-labelled validation data | **None** (`data/validation/labels.json` empty) | |
| Production intelligence processing | **Not approved** | `INTELLIGENCE_ACTIVATION.md` |

Permanent constraints:
* ADR-0001 independence from the owner's technical-analysis project. No imports, dependencies, shared data,
  credentials or workflows.
* `PSXNI_` secrets only.
* No invented data.
* No buy/sell instructions or price targets presented as predictions.
* Every production change and activation needs explicit owner approval.

## 2. Layered architecture

```
 L0 SOURCES ── RSS feeds · SCS chart feed · company IR sites (PDF) · official statistics (manual or API) ·
               licensed providers (if contracted) · owner manual imports
      │  source adapters (collectors/*): permission gate, robots, budget, provenance, idempotent storage
 L1 RAW STORE ── source_items / source_item_versions (metadata, permitted excerpts, document hashes),
                 market_bars (+corrections), dataset_loads
      │  extraction (deterministic first; optional reviewed AI assist)
 L2 NORMALISED FACTS ── events · financial_reports + financial_line_items → financial_metrics (canonical) ·
                        corporate_actions · macro_observations · commodity_prices · company master history
      │  analytics engines (pure, versioned, reproducible)
 L3 ASSESSMENTS ── exposure_candidates · impact_assessments (T1–T9) · dimension_assessments (A–L) ·
                   valuations · forecasts (alerts_predictions) · outcomes (market_outcomes)
      │  research composition
 L4 PRODUCTS ── dashboard (Streamlit) · company / sector / macro / portfolio reports (report_snapshots) ·
                alerts · review queue · validation and calibration reports
```

**Rules that hold at every layer:**
* Each layer only reads the layers below it.
* Every row carries provenance: source item, run, version and timestamp.
* Lower layers are append-only, with corrections stored as new rows.
* Every engine is deterministic and versioned. Re-running a version gives the same result, and a new
  ruleset is a new version, never an overwrite.

## 3. Workstreams (A–H) and their place in the layers

### A. Financial data intelligence (L0→L2)
* **Acquisition:** see the source register (§1).
  * The **primary route** is company investor-relations PDFs, reviewed company by company, through the
    existing `collect_document` metadata-and-hash path, extended with permitted local text extraction.
  * The **secondary route** is owner manual import of documents or provider files (`MANUAL_IMPORT_DESIGN.md`).
  * A licensed provider (Capital Stake or Mettis) is used only if contracted.
* **Document identity:** SHA-256 of the file. A duplicate report is detected by hash, or by (company,
  period, scope, document type).
* **Extraction pipeline** (`engines/financial_extraction`, new):
  1. **Text-layer PDF:** page text and tables via a pure-Python PDF library. This needs a dependency
     decision (U3).
  2. **Scanned PDF:** optional OCR, only if approved (a system package); otherwise routed to manual entry.
  3. **Statement detection:** income statement, balance sheet, cash flow, notes; consolidated or
     unconsolidated, from the headings.
  4. **Line items:** label, value, unit (Rs / '000 / mn), period columns (current and comparative), page and
     table coordinates.
  5. **Mapping:** labels map to a versioned canonical chart of accounts per industry framework (bank,
     insurer, general corporate), via an exact label dictionary first and reviewed fuzzy matches second.
  6. **Validation:** the balance sheet must balance; subtotals must equal the sum of their components;
     comparative figures must match the prior report (else flag a restatement); units must be consistent
     across a statement.
  7. **Confidence:** `exact` (text layer, reconciled), `reconciled_with_warning`, `unreconciled`, `manual`.
     Anything below reconciled goes to review.
* **Storage:**
  * `financial_reports`: one row per document and statement scope.
  * `financial_line_items`: raw, append-only.
  * Canonical values go to the existing `financial_metrics` table (long format, now with a link to their
    report).
  * Restatements are new rows that reference the superseded row. Nothing is overwritten.
* **Corporate disclosures** (dividends, bonus shares, rights issues, AGM results):
  * Stored in `corporate_actions`, from the report notes or owner imports.
  * PSX announcements are **not** collected automatically, because PSX Terms prohibit automation (§4).
* **Also extracted:** shareholding patterns, debt notes, contingencies, related parties and auditor's
  opinions, as typed `financial_line_items` or `report_disclosures` text spans, with page references. Only
  where the document contains them.

### B. Fundamental intelligence (L2→L3)
* **Engine:** `engines/fundamentals` (new). It runs pure calculations over canonical metrics, by industry
  framework:

  | Framework | Applies to | Key measures |
  |---|---|---|
  | Bank / DFI | Commercial banks | NII, NIM (if disclosed), cost-to-income, advances/deposits, NPL ratio and coverage, CAR, ROE |
  | Insurer | Insurance | Premium growth, claims and combined ratios, investment income |
  | General corporate | All others | Revenue growth, gross / operating / net margin, ROE, ROA, ROIC (if invested capital is derivable), debt/equity, net debt, interest cover, current ratio, OCF, FCF, cash conversion, working-capital days, capex |
  | Sector overlays | E&P, refinery, OMC, fertiliser, cement, power IPP | Volumes, realised prices, circular-debt receivables, capacity utilisation; only from disclosures |

* **Four kinds of output, never mixed:**
  1. **Facts:** reported values.
  2. **Calculated metrics:** with formula and inputs, stored in `financial_metrics` with
     `basis = 'calculated'` and a `calculation_method` id.
  3. **Interpretations:** rule-based flags such as "negative OCF for 3 consecutive years" or "interest cover
     below 1.5", each with its rule id and threshold provenance.
  4. **Estimates:** none in this engine.
* **Dimension assessments A–C:** quality, strength and growth (§5) are written to `dimension_assessments`
  with their components. The bands are rule-based, and thresholds are owner-approved policy (U9).

### C. Valuation intelligence (L2/L3→L3)
* **Engine:** `engines/valuation` (new).
* **Methods by company type:**

  | Type | Methods |
  |---|---|
  | Banks | P/B versus ROE; dividend yield; DDM where payout is stable |
  | General corporate | P/E, EV/EBITDA, FCF yield; DCF only when ≥ 5 years of reconciled cash flows exist |
  | Holding companies | Sum-of-the-parts, from listed subsidiaries' market values |
  | Peers and history | Peer comparison by framework; ranges over the company's own available history |

* **Inputs:** SCS daily close and the share count from reports, adjusted by `corporate_actions`. Net debt
  comes from the balance sheet. Cost-of-equity inputs are owner-approved assumptions with provenance
  (risk-free rate from an approved source, or manual). Nothing is hard-coded.
* **Output:** each `valuations` row stores the method, its inputs (ids), assumptions, conservative / base /
  optimistic values, a sensitivity grid, the valuation date and data timestamp, and data quality.
  * `not_applicable` and `insufficient_data` are first-class results.
  * It is presented as "value under stated assumptions", never as a price forecast.
* **Forward P/E** is produced only from a sourced, dated consensus, if a licensed source provides one (U6).
  Otherwise it is not produced.

### D. Market intelligence (L1→L3)
* **Data:** SCS stays the primary provider. The existing collector and validation are kept, and the
  universe expands within the write budget (§6).
* **Engine:** `engines/market_intel` (new), computed on demand or cached daily:
  * returns and adjusted returns (from corporate actions);
  * volume, traded value and liquidity: ADV over 20 sessions, traded value, zero-volume days;
  * volatility, relative strength versus a benchmark (only if the KSE-100 series becomes available, U5);
  * moving averages and momentum;
  * breadth over the tracked universe;
  * unusual activity (volume versus its own baseline);
  * price-volume divergence;
  * accumulation/distribution (on-balance volume, money-flow).
* **Independence:** every indicator is implemented here independently. Nothing is imported or copied from
  the technical project, and there is no data exchange or runtime coupling with it (§7).
* **Liquidity qualification:** 20 sessions, initial 100,000 shares ADV threshold, plus traded value. It is
  computed per symbol, gates **only** technical and market analytics, and never removes the owner's priority
  list.

### E. Macro, geopolitical and sector intelligence (L0→L3)
* **Stage 2 event framework reused:** events, T1–T9 and scope. Structured series are added:
  * `macro_observations`: policy rate, CPI, PKR/USD, reserves, current account, remittances, fiscal
    aggregates. They come from manual import of official releases (SBP is blocked to automation) or a
    verified API.
  * `commodity_prices` (existing table): Brent/WTI and Henry Hub from the EIA API (free key, U2), plus manual
    coal, urea and LNG benchmarks.
* **Transmission:** the Stage 2 T1–T9 framework stays the single transmission model. Series give it a
  stated change and magnitude inputs. Quantified magnitude still needs approved thresholds A/B (U9).
* **Seven layers kept separate:** global event; Pakistan macro transmission; sector exposure; company
  exposure; fundamental effect; valuation effect; sentiment effect. These extend Stage 2's `impact_layers`.
* **Sector intelligence:** aggregates of company-level facts and assessments only. Membership is never
  evidence.

### F. Predictive intelligence and backtesting (L3)
* **Forecasts:** a forecast is a **recorded, falsifiable statement** made at time *t* using only data
  available at *t*.
  * Stored in the existing `alerts_predictions` table: direction, horizon in sessions, confidence, thesis,
    invalidation, and a snapshot of its inputs.
  * Evaluated in the existing `market_outcomes` table: stock, benchmark, sector and dividend-adjusted
    returns, net of costs.
* **Three families, kept separate and labelled:**
  1. deterministic rules (T1–T9 directions, fundamental flags);
  2. statistical models (e.g. event-study abnormal-return estimates), only after M7 data exists;
  3. future AI-assisted models (not authorised).
* **No claims without validation:** no accuracy claim without walk-forward, out-of-sample validation
  (`MASTER_VALIDATION_STRATEGY.md`).

### G. Portfolio and opportunity intelligence (L3→L4)
* **Data:**
  * Holdings, transactions and theses are user data, stored in a **separate** Turso database, per user
    (§6, U8).
  * Alert rules are evaluated against L2/L3.
* **Opportunity views:** a set of dimension components (§5), not one opaque score. Any ranking is a sorted
  view of named components, with its definition versioned and validated (M7) before it is shown as a
  "screen".
* **Theses:** each thesis records its assumptions and invalidation conditions. Invalidation is checked
  against new facts, events and valuations.

### H. Integrated research platform (L4)
* **Navigation:** the Streamlit app gets the full navigation: market, macro, sector, company (financials /
  fundamentals / valuation / market / events), scenarios, portfolio, screens, history, reports, evidence.
* **Reports:** the 15 required sections are built from L2/L3 only.
* **Reproducibility:** each generated report is stored in `report_snapshots`, with the input version ids
  and a content hash. Re-rendering a snapshot reproduces it exactly.
* **Missing data:** shown as one of the §6 states, never as zero.

## 4. Data-source strategy (summary; detail in the source register)
* **Smallest reliable set:**

  | Data | Source |
  |---|---|
  | Market data | SCS chart feed (active) |
  | News | 10 RSS feeds (active) |
  | Releases | PBS RSS (active) |
  | Financials | Company IR PDFs, reviewed per company (research task R1) |
  | Commodities | EIA API (free key; terms reviewed, U2) |
  | Pakistan macro | Owner manual import of official SBP / MoF / PBS releases |
  | Fallback for listings, announcements and financials at scale | A licensed PSX redistributor (quote needed, U1) |

* **Excluded:** PSX websites, for automated collection (verified Terms prohibit it). Pages may be read
  manually for owner-maintained reference data such as the calendar.

## 5. Investment-reasoning framework (dimensions A–L)
Each dimension is assessed separately, with its own evidence, version, as-of date and state (§6):

| Dim | Name | Built from | Engine |
|---|---|---|---|
| A | Fundamental quality | Margins, returns, consistency | fundamentals |
| B | Financial strength | Leverage, coverage, liquidity, maturities | fundamentals |
| C | Earnings growth | Revenue/EPS trends, segments | fundamentals |
| D | Valuation | Methods in §3C versus own history and peers | valuation |
| E | Sector outlook | Sector aggregates, sector events | sector |
| F | Macro conditions | T1–T9 exposures × macro series | impact (Stage 2) + macro |
| G | Geopolitical exposure | T8, route and location exposures | impact |
| H | Market sentiment | Market-wide breadth and risk-premium events | market_intel |
| I | Technical behaviour | Trend, momentum, A/D | market_intel |
| J | Liquidity / tradability | ADV, traded value | market_intel |
| K | Event-driven opportunity | Events with direct exposure and assessed impact | impact |
| L | Risk and uncertainty | Flags, conflicts, data quality, scenario width | all |

* **Interactions are shown, not netted.** For example, "strong A/B, weak D" or "strong A, negative F (temporary
  macro pressure)".
* **No unvalidated composite score:** an overall score may only be introduced as a versioned formula whose
  weights come from M7 walk-forward evidence, and it is displayed with its components. None is defined now.

## 6. System-wide data states and quality
**Data states:** every value or assessment carries exactly one of the following.

| State | Meaning |
|---|---|
| `source_unavailable` | The source could not be reached or is not permitted |
| `data_unavailable` | The source has no such data |
| `not_applicable` | The concept doesn't apply, e.g. gross margin for a bank |
| `zero` | A real reported zero |
| `not_processed` | Not yet processed |
| `processing_failed` | Processing failed |
| `unverified` | Not yet verified |
| `estimated` | Labelled estimate with method |
| `reported` / `calculated` | Facts, and values derived from facts |

Missing is never zero.

**Common controls:**
* source reliability tier and freshness;
* completeness per period;
* duplicate detection (document hashes, key constraints);
* unit and scale validation;
* financial reconciliation;
* historical consistency (comparatives versus prior reports);
* outliers (period-over-period change beyond a policy bound → review, never auto-correct);
* extraction confidence, provenance and an append-only audit trail;
* idempotent, lease-protected jobs.

## 7. Integration boundary with the technical-analysis project
* **None, permanently (ADR-0001).** There is no integration and no data exchange of any kind (files,
  tables, exports or imports), and no shared database, credentials, code, dependencies, submodules,
  workflows or runtime coupling with the technical-analysis project, in either direction.
* This is a settled architectural constraint, not an open decision. It can change only if the owner
  explicitly changes the project boundary in a future, separately documented decision (a new ADR).
* The independence guard stays unchanged.

## 8. AI and automation (optional, not authorised)
* **Possible future uses:** extraction assistance for hard tables, classification of ambiguous headlines,
  relationship research, report drafting.
* **Requirements:**
  * the existing `LLMGateway` (kill switch, cost cap, prompt hashing, `llm_calls` audit);
  * schema-validated outputs carrying source spans;
  * human review for material values;
  * caching by input hash;
  * provider-agnostic;
  * deterministic results remain the baseline and the fallback.
* **Never:** autonomous trading or order execution.

## 9. Unresolved decisions (owner)
| Id | Decision |
|---|---|
| U1 | Listings, announcements and financials at scale: per-company IR review plus manual import, or a licensed provider (Capital Stake or Mettis quote) |
| U2 | EIA API key (free) and terms acceptance; World Bank's non-commercial terms acceptable for private research |
| U3 | PDF libraries (`pypdf` / `pdfplumber`; PyPI only) and optional OCR (system Tesseract) |
| U4 | Approved authoritative listed-company universe source |
| U5 | KSE-100 benchmark: does SCS serve an index symbol? (research task); otherwise a licensed source |
| U6 | Consensus estimates (licensed only), or forward P/E not offered |
| U7 | Actual intraday (1-minute) universe size within the write budget (§6 of the database design); the manually curated priority list (100+ stocks) itself is not reduced by this |
| U8 | Single-user versus multi-user, authentication, and a separate portfolio database |
| U9 | Policy thresholds: fundamentals bands, impact magnitude A/B, outlier bounds, valuation assumptions |
| U10 | Labelling capacity: who labels, how many items per month |
| U11 | Optional AI provider and budget |


## Update (2026-11-09): CFA-style analysis layer and sector applicability

- Added `engines/sector_applicability.py` (applicability classes per ratio and PSX sector; calculation guard; company
  sector link) and `engines/earnings_quality.py` (review indicators with evidence and limits).
- The CFA-style layer reuses the existing financial, fundamentals and valuation modules. Its status by layer is in
  `docs/CFA_STYLE_ANALYSIS_DESIGN.md`. It is not a certified analysis and issues no investment instruction.
- Independence is unchanged: no import from, or data shared with, the separate technical-analysis project.
