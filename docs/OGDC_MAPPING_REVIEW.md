# OGDC account mapping review (D7, finalised)

Status: the owner approved the mappings and codes below in this batch. **Approved OGDC mappings are applied through a versioned, company-specific overlay (`config/company_mappings/ogdc.json`), never through the universal seed.** Nothing here is a universal PSX mapping.

Source: the 88 distinct ordinary labels in the unconsolidated Q1 FY27 interim report (document C, pages 10–15). Labels the structural rules name are not in this list.

## Summary
- Ordinary labels reviewed: 88
- Owner-approved and applied (OGDC overlay): 11
- Rejected mapping: 1 (amortisation to depreciation_amortisation)
- Remaining unmapped (kept, no explicit canonical meaning): 77
- Unresolved figure rows (not labels): cash-flow subtotal '105,987,076 72,895,745' stays unresolved.

## 1. Owner-approved mappings (applied)

| Statement | Original label (exact) | Canonical code | Status | Context and scope |
|---|---|---|---|---|
| IS | Profit before income tax | `profit_before_tax` | Approved (owner). Applied to OGDC only. | any period; OGDC only |
| IS | Profit for the quarter | `profit_after_tax` | Approved (owner). Applied to OGDC quarterly statements only. | quarterly only; OGDC only |
| IS | Earnings per share- basic and diluted (Rupees) | `eps_basic` | Approved (owner). Combined basic and diluted wording kept; no diluted EPS derived. | quarterly only; OGDC only |
| CF | Amortization of development and production assets | `amortisation_expense` | Approved as a NEW code (owner). Replaces the rejected mapping to depreciation_amortisation. | any period; OGDC only |
| CF | Cash and cash equivalents at beginning of the quarter | `cash_opening` | New code approved (owner); exact-label mapping applied to OGDC quarterly cash flows. | quarterly only; OGDC only |
| CF | Cash and cash equivalents at end of the quarter | `cash_closing` | New code approved (owner). Cash-flow closing balance; NOT the balance-sheet cash line. | quarterly only; OGDC only |
| CF | Net cash (used in) /generated from investing activities | `cfi` | New code approved (owner). | any period; OGDC only |
| CF | Net cash used in financing activities | `cff` | New code approved (owner). | any period; OGDC only |
| CF | Net increase /(decrease) in cash and cash equivalents | `net_change_in_cash` | New code approved (owner). | any period; OGDC only |
| CF | Cash generated from operations | `cash_generated_from_operations` | New code approved (owner); definition per the source statement. | any period; OGDC only |
| CF | Income taxes paid | `income_tax_paid` | New code approved (owner). Cash tax paid, not tax expense. | any period; OGDC only |

## 2. Rejected mapping

| Original label | Rejected code | Reason | Replacement |
|---|---|---|---|
| Amortization of development and production assets | `depreciation_amortisation` | Amortisation is not reported as combined depreciation and amortisation in this line. | `amortisation_expense` (section 1) |

## 3. New canonical codes (owner-approved definitions)

Full definitions and validation are in `config/canonical_codes.json`. Spelling convention: British, matching `depreciation_amortisation`.

| Code | Definition |
|---|---|
| `cfi` | Net cash flow from investing activities. |
| `cff` | Net cash flow from financing activities. |
| `net_change_in_cash` | Net change in cash and cash equivalents during the period. |
| `cash_opening` | Opening cash and cash equivalents for the cash-flow period. |
| `cash_closing` | Closing cash and cash equivalents in the cash-flow statement. NOT balance-sheet cash. |
| `cash_generated_from_operations` | Cash generated from operations, per the source definition. |
| `income_tax_paid` | Actual cash income tax paid, not tax expense. |
| `other_income` | Only an explicitly reported other-income line. Not applied to OGDC: its only candidate, 'Finance and other income', is a combined line. |
| `amortisation_expense` | Amortisation reported explicitly as amortisation. |

## 4. Cash closing versus balance-sheet cash (must stay distinct)

| Measure | Canonical code | Q1 FY27 value (Rs '000) |
|---|---|---|
| Balance-sheet cash and bank balances | `cash_and_equivalents` | 39,711,514 (unconsolidated); 39,711,614 (consolidated) |
| Cash-flow closing balance | `cash_closing` | 321,457,827 |

They are reported as different measures and are never forced to agree. The gap is an open accounting question (see section 7).

## 5. Unmapped labels (77), grouped by statement and analytical importance

| # | Statement | Page | Original label | Category | Affects profitability / cash / debt / working capital / valuation | Decision |
|---|---|---|---|---|---|---|
| 1 | BS | 10 | Reserves | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 2 | BS | 10 | Unappropriated profit | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 3 | BS | 10 | Deferred taxation | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 4 | BS | 10 | Deferred employee benefits | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 5 | BS | 10 | Provision for decommissioning cost | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 6 | BS | 10 | Short term lease liability | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 7 | BS | 10 | Trade and other payables | working capital | working capital | Keep unmapped; needs owner decision on a code |
| 8 | BS | 10 | Unpaid dividend | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 9 | BS | 10 | Unclaimed dividend | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 10 | BS | 11 | Property, plant and equipment | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 11 | BS | 11 | Development and production assets | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 12 | BS | 11 | Exploration and evaluation assets | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 13 | BS | 11 | Long term investments in subsidiary and associates | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 14 | BS | 11 | Long term investments at amortized cost | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 15 | BS | 11 | Long term loans- secured | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 16 | BS | 11 | Long term advances and prepayments | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 17 | BS | 11 | Lease receivables | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 18 | BS | 11 | Stores, spare parts and loose tools | working capital | working capital | Keep unmapped; needs owner decision on a code |
| 19 | BS | 11 | Loans and advances | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 20 | BS | 11 | Deposits and short term prepayments | working capital | working capital | Keep unmapped; needs owner decision on a code |
| 21 | BS | 11 | Other receivables | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 22 | BS | 11 | Income tax- advance | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 23 | BS | 11 | Current portion of long term investments | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 24 | BS | 11 | Current portion of lease receivables | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 25 | BS | 11 | Other financial assets | balance sheet component | none (component) | Keep unmapped; needs owner decision on a code |
| 26 | CF | 15 | Profit before income tax | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 27 | CF | 15 | Amortization of premium on Pakistan Investment Bonds | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 28 | CF | 15 | Amortization of prepaid employee benefit | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 29 | CF | 15 | Unwinding of loss on modification in terms of TFCs | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 30 | CF | 15 | Unwinding of present value of interest free loan to employees | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 31 | CF | 15 | Royalty | profitability | profitability, cash | Keep unmapped; needs owner decision on a code |
| 32 | CF | 15 | Workers’ profit participation fund | profitability | profitability, cash | Keep unmapped; needs owner decision on a code |
| 33 | CF | 15 | Provision for deferred employee benefits | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 34 | CF | 15 | Unwinding of discount on provision for decommissioning cost | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 35 | CF | 15 | Interest income on investments and bank deposits | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 36 | CF | 15 | Interest income on lease | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 37 | CF | 15 | Unwinding of lease liability | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 38 | CF | 15 | Un-realized gain on investments at fair value through profit or loss | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 39 | CF | 15 | Realized gain on investments at fair value through profit or loss | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 40 | CF | 15 | Exchange loss on lease | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 41 | CF | 15 | Exchange loss on foreign currency investments and deposit accounts | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 42 | CF | 15 | Dividend income from investment at fair value through profit or loss | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 43 | CF | 15 | Gain on disposal of property, plant and equipment | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 44 | CF | 15 | Share of profit in associates - net of taxation | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 45 | CF | 15 | Stores inventory written off | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 46 | CF | 15 | Cost of dry and abandoned wells during the quarter | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 47 | CF | 15 | Reversal of trade debts provision | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 48 | CF | 15 | Stores, spare parts and loose tools | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 49 | CF | 15 | Stock in trade | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 50 | CF | 15 | Trade debts | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 51 | CF | 15 | Deposits and short term prepayments | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 52 | CF | 15 | Loan and advances and other receivables | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 53 | CF | 15 | Trade and other payables | working capital | cash, working capital | Keep unmapped; needs owner decision on a code |
| 54 | CF | 15 | Royalty paid | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 55 | CF | 15 | Deferred employee benefits paid | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 56 | CF | 15 | Long term advances and prepayments | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 57 | CF | 15 | Decommissioning cost paid | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 58 | CF | 15 | Payment to workers’ profit participation fund-net | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 59 | CF | 15 | Interest received | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 60 | CF | 15 | Lease payments received | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 61 | CF | 15 | Dividends received | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 62 | CF | 15 | Term Finance Certificates interest received | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 63 | CF | 15 | Investments at fair value through profit or loss - net | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 64 | CF | 15 | Investment in associates | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 65 | CF | 15 | Proceeds from disposal of property, plant and equipment | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 66 | CF | 15 | Lease payments made | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 67 | CF | 15 | Effect of movements in exchange rate on cash and cash equivalents | cash flow | cash | Keep unmapped; needs owner decision on a code |
| 68 | IS | 12 | Royalty | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 69 | IS | 12 | Operating expenses | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 70 | IS | 12 | Transportation charges | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 71 | IS | 12 | Finance and other income | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 72 | IS | 12 | Exploration and prospecting expenditure | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 73 | IS | 12 | General and administration expenses | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 74 | IS | 12 | Workers’ profit participation fund | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 75 | IS | 12 | Share of profit in associates -net of taxation | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 76 | IS | 12 | Profit before income tax and final taxes | profitability | profitability | Keep unmapped; needs owner decision on a code |
| 77 | IS | 12 | Final taxes -levies | profitability | profitability | Keep unmapped; needs owner decision on a code |

## 6. Recommended manual-review priorities

1. **Profitability:** 'Profit before income tax and final taxes' (an ambiguous subtotal), 'Final taxes -levies', 'Finance and other income' (combined), royalty and operating cost lines (covered by the structural cost-of-sales total).
2. **Cash flow:** 'Cash generated from operations' is now applied; the remaining operating add-backs and payments need a decision on codes before any cash analysis.
3. **Working capital:** receivable, inventory and payable movements in the cash flow (not yet coded).
4. **Debt:** no borrowings line is mapped in these statements, so debt-to-equity stays unavailable. Total liabilities are never treated as borrowings.
5. **Valuation:** no market or share-price input is in these documents; the M5 valuation items remain insufficient_data.

## 7. Open accounting question

The cash-flow closing balance (321,457,827) differs from balance-sheet cash and bank (39,711,514). The notes may define cash and cash equivalents to include other items (for example short-term investments). This needs confirmation from the notes before any reconciliation between the two.

## 8. Reusability

- Reusable (standard statement lines): profit before tax, profit after tax, EPS, cash-flow totals, cash opening and closing, income tax paid.
- OGDC-specific presentation (not evidence for a universal mapping): 'Royalty', 'Workers’ profit participation fund', 'Term Finance Certificates interest received', 'Amortization of premium on Pakistan Investment Bonds', 'Cost of dry and abandoned wells during the quarter'.
- No OGDC-specific mapping has been promoted to a universal PSX mapping.
