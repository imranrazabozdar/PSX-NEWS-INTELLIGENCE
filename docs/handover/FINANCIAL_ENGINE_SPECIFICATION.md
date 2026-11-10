# Financial engine specification

Last verified: 2026-11-10. Source requirements: the project specification (`docs/SPECIFICATION.md` in the news repository, section 21 and the financial sections) and the owner's handover brief.

## 1. Purpose
Turn a company's real annual and interim reports into evidence-backed financial conclusions. The chain: report → extracted statements and notes → reconciliation → quality analysis → cash conversion → change detection (improvement and deterioration) → forecast → valuation → evidence-backed report. The engine describes and quantifies only what the sourced inputs support.

## 2. Non-negotiable rules
1. **Never convert missing data to zero.** Missing is `insufficient_data` with the missing inputs named. A genuine zero is a value with its source.
2. **Every number carries provenance:** source document, page, verbatim excerpt, metric identifier and basis (reported, restated, calculated).
3. **Separate the four kinds of statement:** reported fact, calculation, estimate, inference. Label each.
4. **Point-in-time:** distinguish the filing date from the period end. A figure filed after a date must not affect an analysis as of that date (`fundamentals.metrics` implements `as_of`).
5. **No grading without the owner's thresholds** (open item U9 in `STATUS`). The engine states numbers and divergences.
6. **No fabricated filings, statements, prices or consensus.** Synthetic inputs may test mechanics only and must be labelled synthetic.
7. **Reconcile before presenting.** Segments must add to the group within a stated tolerance. Statement subtotals must reconcile.
8. **Sector applicability:** banks, insurers, and other financial institutions use their own framework. Do not apply industrial-company DCF to them.

## 3. What exists [SRC, see inventory]
| Requirement | Implementation | Status |
|---|---|---|
| Statement import with rights attestation, mapping, reconciliation, promotion | `engines/financials.py` (`import_report`, `reconcile`, `promote`, `parse_statement_text`) | Implemented; tested offline |
| Canonical metric store (`financial_metrics`, scopes, restated versus reported) | migration 0011 tables; `engines/fundamentals.py` `metrics`, `choose_scope` | Implemented; tested offline |
| Ratios: margins, returns, leverage, coverage, liquidity, efficiency, growth | `engines/fundamentals.py` `RATIOS` | Implemented; tested offline |
| Free cash flow, dividend cover | `engines/fundamentals.py` `_fcf`, `_dividend_cover` | Implemented; tested offline |
| Dimensions A–C written to `dimension_assessments` | `engines/fundamentals.py` `assess` | Implemented; bands null (owner) |
| Valuation inputs, multiples, DCF (Gordon and explicit), scenario models | `engines/valuation.py` | Implemented; tested offline; inputs must be sourced |
| Macro series registry (definitions only) | `engines/macro.py`, `config/macro_series.json` | Implemented; no values |
| PDF reading | `engines/pdf_reader.py`, `engines/pdf_extraction.py` (pdfplumber, pinned, owner-approved) | Implemented; no real report run [UNKNOWN] |
| Earnings quality, cash conversion, receivables vs revenue, auditor signals | `engines/earnings_quality.py` (branch PR #61) | Implemented on branch; synthetic tests only |
| Segment reconciliation and margins | `engines/segments.py` (branch PR #62) | Implemented on branch; synthetic tests only |
| Notes extraction with page evidence (labelled rows, brackets, ambiguity) | `engines/notes_extraction.py` (branch PR #62) | Implemented on branch; synthetic text only |

## 4. Gaps (not implemented)
- **Multi-year normalisation** of a company's statements into one comparable series, with restatement handling across years. Partly in `financials.py` (comparatives). No multi-year series builder.
- **Receivables ageing** table extraction and analysis. No ageing parser.
- **Inventory, payables and borrowings schedules** from notes: not extracted.
- **Deferred tax, leases, contingent liabilities, related-party transactions, subsequent events**: not extracted.
- **Auditor's report text** (opinion wording, KAM headings): the audit-signals module accepts sourced facts but nothing extracts them from a report.
- **Management discussion and governance** text: not extracted.
- **Forecasts:** no revenue, margin, working capital, debt or cash-flow forecast engine. Dimension E–L not implemented (STATUS).
- **Financial-impact transmission** from a sourced input change to statement lines: the T1–T9 framework is qualitative only.
- **Relative valuation** by industry multiples with sourced peer data: not implemented beyond the multiples function.
- **Sector-specific frameworks** for banks and insurers: not implemented (fundamentals has a `bank` and `insurer` framework tag for some ratios only).

## 5. Required method details
### 5.1 Earnings quality (as implemented, `engines/earnings_quality.py`)
- Cash conversion = CFO / profit after tax. Not applicable when profit ≤ 0.
- Accruals to assets = (profit after tax − CFO) / total assets (closing, not averaged; basis stated).
- Receivable days = trade receivables / revenue × 365 (closing).
- Receivables versus revenue = growth of receivables − growth of revenue, percentage points. Needs the prior year.
- Audit facts (opinion, KAM count, going concern) need page and excerpt; unstated = not reported.
Owner must set bands. Trend interpretation (for example, receivables rising then collection improving) requires multi-year series, which does not yet exist.

### 5.2 Segments (as implemented, `engines/segments.py`)
Reconcile segment revenue to the group within the larger of 1.0 reporting unit or 0.1% of group. Unreconciled → no shares presented. Margin = profit / revenue per segment; zero revenue → not applicable. Segment growth absent in prior year → not reported.

### 5.3 Valuation (existing, `engines/valuation.py`)
DCF and multiples produce results with state and missing inputs. A fair value is not produced when essential inputs are missing. Scenarios (base, optimistic, adverse) are model outputs under stated assumptions, not forecasts. Owner must approve assumptions before any use.

## 6. Validation requirements (not yet met)
1. At least one real company's annual report must be processed end to end, with each extracted figure checked against the printed statement and its page.
2. Reconciliation: statement subtotals and segment totals must agree with the report within the stated tolerance on that real report.
3. Historical back-test: point-in-time financial inputs only, with no look-ahead and survivorship checks. Not yet possible.
4. Owner review of the chosen thresholds (U9).

## 7. Reuse guidance
The technical repository's `fundamental_engine/` contains an LLM extraction path, a number parser and verbatim-quote grounding. Reuse ideas through the scoped exception only. Keep the news engines' rules (deterministic numbers, no model-produced figures).
