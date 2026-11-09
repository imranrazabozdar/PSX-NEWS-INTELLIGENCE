# OGDC accounting reconciliation: consolidated versus unconsolidated, cash, subtotals and comparatives

Source: the owner's Q1 FY27 interim report (SHA-256 `7578698baff711412a7725ca158866b88aa4134e255d2c484fad4a075060b515`),
unconsolidated statements pages 10–15 and consolidated statements pages 34–39, with the notes on pages 16–33 (company)
and 40–56 (consolidated). All amounts are Rs '000 unless stated. Every figure below was read from the document's
text layer and checked against the page; no figure was forced to agree.

Status legend: **Explained** = the amount is matched to an explicit disclosure. **Explained, mechanism inferred** =
the amount matches an explicit disclosure but the link between them is inferred, not stated. **Unresolved** = no
disclosure in the document explains the difference.

## C1. Consolidated versus unconsolidated: balance sheet, every line that differs

| Line | Period | Unconsolidated | Consolidated | Difference | Source | Status |
|---|---|---|---|---|---|---|
| Cash and bank balances | 30 Sep 2026 | 39,711,514 | 39,711,614 | +100 | p11 / p35; note 23 (p27 / p51) | Explained, mechanism inferred (see C2) |
| Long term investments in subsidiary and associates (unconsolidated) / in associates (consolidated) | 30 Sep 2026 | 182,965,772 | 182,965,672 | −100 | note 11.1 (p21): subsidiary OREL at cost 100 | Explained: the subsidiary's cost is eliminated |
| Other receivables | 30 Sep 2026 | 1,630,771 | 1,627,906 | −2,865 | note 28 (p28): receivable from OREL 2,865 at 30 Sep 2026 | Explained, mechanism inferred (elimination not stated) |
| Unappropriated profit (total equity) | 30 Sep 2026 | 1,499,398,074 | 1,499,395,209 | −2,865 | Follows from the identity (see below) | Explained in amount; cause not disclosed |
| Current assets | 30 Sep 2026 | 1,260,590,703 | 1,260,587,938 | −2,765 | = +100 cash − 2,865 receivable | Explained |
| Non-current assets subtotal | 30 Sep 2026 | 626,182,859 | 626,182,759 | −100 | = −100 investment | Explained |
| Total assets | 30 Sep 2026 | 1,886,773,562 | 1,886,770,697 | −2,865 | = −100 + 100 − 2,865 | Explained |
| Total liabilities | 30 Sep 2026 | 309,156,089 | 309,156,089 | 0 | — | Identical |
| Total equity | 30 Sep 2026 | 1,577,617,473 | 1,577,614,608 | −2,865 | = assets − liabilities | Explained (follows from the identity) |

**Residual at 30 September 2026: 0.** Every difference sums exactly: total assets −2,865 = cash +100, investments −100,
other receivables −2,865. The equity difference equals the asset difference because liabilities are identical.

### Comparative column, 30 June 2026

| Line | Unconsolidated | Consolidated | Difference | Status |
|---|---|---|---|---|
| Cash and bank balances | 62,143,448 | 62,143,548 | +100 | Explained, mechanism inferred (same OREL cash as above) |
| Long term investments (subsidiary and associates / associates) | 178,823,045 | 178,822,945 | −100 | Explained (note 11.1: OREL at cost 100) |
| Other receivables | 1,624,562 | 1,622,962 | **−1,600** | **Unresolved.** The only OREL receivable disclosed is at 30 Sep 2026 (2,865) and 30 Sep 2025 (1,100) in note 28. No 30 June 2026 amount is disclosed. |
| Trade and other payables (and total liabilities) | 150,888,218 | 150,889,483 | **+1,265** | **Unresolved.** No note disclosure found for this difference. |
| Unappropriated profit | 1,441,247,229 | 1,441,244,364 | −2,865 | Follows from the identity; cause not disclosed |
| Total assets | 1,852,828,189 | 1,852,826,589 | −1,600 | = +100 − 100 − 1,600 |
| Total liabilities | 333,278,025 | 333,279,290 | +1,265 | Unresolved (see above) |
| Total equity | 1,519,550,164 | 1,519,547,299 | −2,865 | = −1,600 − 1,265 |

**Residual at 30 June 2026: −1,600 (assets) and +1,265 (liabilities).** The identity holds
(−1,600 = +1,265 − 2,865), but the two residual components are not explained by any disclosure in this document. The
consolidated annual audited statements, which are the stated source of the 30 June 2026 comparative, are not available.

**What the evidence does and does not show.** The OREL amounts (cost 100, receivable 2,865, subscribed capital 100) are
explicit. The statement that OREL's cash and its receivable are eliminated on consolidation, and the statement that the
unappropriated-profit difference is OREL's result, are not written in the document; they are the only reading that fits
the explicit amounts. They are therefore recorded as "mechanism inferred". The 30 June 2026 residuals are not forced.

## C2. Cash and cash equivalents

Note 23 (p27 unconsolidated, p51 consolidated) defines the measure. Cash and cash equivalents = cash and bank balances +
short-term highly liquid investments (term deposits).

| Component | 30 Sep 2026 unconsolidated | 30 Sep 2026 consolidated | Source |
|---|---|---|---|
| Cash and bank balances | 39,711,514 | 39,711,614 | Balance sheet; note 23 |
| Short-term highly liquid investments (term deposits) | 281,746,313 | 281,746,313 | Note 23 |
| **Cash and cash equivalents (note 23)** | **321,457,827** | **321,457,927** | Note 23 |
| Cash-flow statement closing balance | 321,457,827 | 321,457,927 | p39 (consolidated), p15 (unconsolidated) |
| Difference, note total vs cash-flow closing | 0 | 0 | — |

The cash-flow closing balance equals the note-23 total, so the disclosed definition explains the difference between
the two measures exactly: 321,457,827 − 39,711,514 = 281,746,313 (term deposits). Both measures remain separate canonical
values: `cash_closing` (cash-flow statement) and `cash_and_equivalents` (balance sheet). They are not merged.

Prior-period check (30 Sep 2025, note 23): cash and bank 12,513,411 + term deposits 167,534,527 = 180,047,938, equal to the
comparative cash-flow closing 180,047,938. The opening cash for the quarter (291,123,943) is the 30 June 2026 cash
and cash equivalents; the 30 June 2026 term-deposit balance is not disclosed in the document, so it is not stated here.

**Open classification question (not a measure question):** the balance sheet does not state which line holds the
term deposits (possibly "Other financial assets", 325,816,683). This does not change either measure.

Ratios: no cash ratio is calculated from the balance-sheet line alone. Any cash-based metric must state which measure it
uses.

## C3. Cash-flow subtotals (previously unresolved)

| Figure | Column | Arithmetic established | Result |
|---|---|---|---|
| 105,987,076 | 30 Sep 2026 | Profit before income tax 87,988,861 + adjustments 17,998,215 (23 rows; 8 nil dashes counted as zero in the check only) = 105,987,076 | **Recognised structurally** (rule R8, cash-flow adjustments block). No canonical code. |
| 72,895,745 | 30 Sep 2025 | Profit before income tax 61,982,220 + adjustments 10,913,525 = 72,895,745 | **Recognised structurally** (rule R8). No canonical code. |
| Cash generated from operations (labelled) | 2026 / 2025 | 105,987,076 − 15,286,161 (changes block) = 90,700,915; 72,895,745 + 138,081 = 73,033,826 | Confirms both subtotals against the labelled line. |

The subtotals therefore have an established meaning from the statement layout: "profit before tax plus adjustments for
non-cash and other items". No standard canonical code exists for that meaning, so none was invented.

## C4. Owner-approved mappings (preserved)

Unchanged: `Profit before income tax` → `profit_before_tax`; `Profit for the quarter` → `profit_after_tax`;
`Earnings per share- basic and diluted (Rupees)` → `eps_basic`; `Amortization of development and production assets` →
`amortisation_expense`; the seven cash-flow codes (`cfi`, `cff`, `net_change_in_cash`, `cash_opening`, `cash_closing`,
`cash_generated_from_operations`, `income_tax_paid`). `other_income` remains defined and unmapped (no separately reported
other-income line exists; "Finance and other income" is a combined line). None of these is broadened to a universal PSX
mapping.

## D. Comparative balance-sheet promotion (controlled rule)

`promote_balance_comparative` promotes the 30 June 2026 comparative balance sheet as point-in-time balances:
- only balance-sheet lines with balance codes, only from the named comparative column, only at a fiscal year-end date;
- the company, currency, unit and consolidated/unconsolidated scope of the source report are preserved;
- the source document hash (through the report's source item) and the page number are preserved, and the original
  comparative label is recorded in the calculation method;
- restated comparatives use the `restated` basis when the report states it restates an earlier period; otherwise `reported`;
- an existing different value at the same date refuses the whole promotion and nothing is overwritten;
- income-statement and cash-flow comparatives are never promoted by this rule.

Result on this document: 9 balance points promoted for each scope (unconsolidated and consolidated), 30 June 2026.

**Date provenance for these balances:** publication/filing date = the interim report's filing date (30 Oct 2026, the
letter date; the PUCARS timestamp is not verified). The balances are first known to the project on the receipt date
(9 Nov 2026) and were imported at the system time recorded at import. The download date is unknown. Because the
point-in-time read uses the filing date, a 30 June 2026 balance from this report is not visible to any analysis as of a
date before 30 October 2026 (conservative; the annual results annexure of 4 September 2026 is not processed here).

## E. Average-balance M3 results, real data (hand-checked)

Inputs (Rs): revenue 132,418,817,000 (quarter); profit after tax 58,513,345,000; total assets 1,886,773,562,000 (30 Sep
2026) and 1,852,828,189,000 (30 Jun 2026); total equity 1,577,617,473,000 and 1,519,550,164,000.

| Ratio | Engine | Hand check | Limitation |
|---|---|---|---|
| Asset turnover, average assets (annualised) | 0.283279 | 132,418,817,000 × 4 ÷ ((1,886,773,562,000 + 1,852,828,189,000) ÷ 2) = 0.283279 ✓ | Quarter annualised ×4, labelled |
| ROA, average assets (annualised) | 0.125176 | 58,513,345,000 × 4 ÷ 1,869,800,875,500 = 0.125176 ✓ | Quarter annualised ×4 |
| ROE, average equity (annualised) | 0.151140 | 58,513,345,000 × 4 ÷ ((1,577,617,473,000 + 1,519,550,164,000) ÷ 2) = 0.151140 ✓ | Quarter annualised ×4 |

Consolidated results agree to the sixth decimal place (for example ROE 0.151141), as expected for a balance sheet that
differs by 0.15% in equity.

## Unresolved items (not forced)

1. Other receivables at 30 June 2026: −1,600 (consolidated versus unconsolidated). No disclosure.
2. Trade and other payables at 30 June 2026: +1,265. No disclosure.
3. The mechanism for OREL's cash, receivable and equity effects is inferred from explicit amounts; the document does not
   state the elimination entries.
4. The balance-sheet line that holds the term deposits is not stated.
5. The annual audited consolidated statements (the stated source of the 30 June 2026 comparative) are not available.
