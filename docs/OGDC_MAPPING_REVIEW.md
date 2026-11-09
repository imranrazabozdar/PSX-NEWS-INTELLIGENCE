# OGDC account mapping review (D7)

Status: **review only. Nothing here is approved or loaded.** Each proposal needs the owner's decision, and any approved mapping is a new versioned entry (`add_mapping`), never an edit to the seed file.

Source: the 88 distinct ordinary labels in the unconsolidated Q1 FY27 interim report (document C, pages 10–15), extracted by the approved reader. Labels that the structural rules already name (for example the cost-of-sales and total-asset subtotals) are not in this list. Confidence reflects the wording and the statement context, not accuracy.

Decision key: **Propose** = existing standard code, owner approval needed. **Keep** = no standard code applies; stays unmapped and is not used by any check.

| # | Statement | Page | Original label | Decision | Proposed standard code | Financial meaning | Confidence | Affects reconciliation | Reusable or OGDC-specific |
|---|---|---|---|---|---|---|---|---|---|
| 1 | BS | 10 | Reserves | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 2 | BS | 10 | Unappropriated profit | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 3 | BS | 10 | Deferred taxation | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 4 | BS | 10 | Deferred employee benefits | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 5 | BS | 10 | Provision for decommissioning cost | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 6 | BS | 10 | Short term lease liability | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 7 | BS | 10 | Trade and other payables | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 8 | BS | 10 | Unpaid dividend | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 9 | BS | 10 | Unclaimed dividend | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 10 | BS | 11 | Property, plant and equipment | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 11 | BS | 11 | Development and production assets | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 12 | BS | 11 | Exploration and evaluation assets | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 13 | BS | 11 | Long term investments in subsidiary and associates | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 14 | BS | 11 | Long term investments at amortized cost | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 15 | BS | 11 | Long term loans- secured | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 16 | BS | 11 | Long term advances and prepayments | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 17 | BS | 11 | Lease receivables | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 18 | BS | 11 | Stores, spare parts and loose tools | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 19 | BS | 11 | Loans and advances | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 20 | BS | 11 | Deposits and short term prepayments | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 21 | BS | 11 | Other receivables | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 22 | BS | 11 | Income tax- advance | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 23 | BS | 11 | Current portion of long term investments | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 24 | BS | 11 | Current portion of lease receivables | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 25 | BS | 11 | Other financial assets | Keep | — | Balance sheet component: no standard total code applies; kept unmapped | High | No | Reusable |
| 26 | CF | 15 | Profit before income tax | Keep | — | Starting point of the cash flow; same measure as the income statement line, not mapped twice | High | No | Reusable |
| 27 | CF | 15 | Amortization of development and production assets | Propose | depreciation_amortisation | Amortisation charge added back in operating cash flow | Medium | No | Reusable; wording OGDC-specific |
| 28 | CF | 15 | Amortization of premium on Pakistan Investment Bonds | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 29 | CF | 15 | Amortization of prepaid employee benefit | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 30 | CF | 15 | Unwinding of loss on modification in terms of TFCs | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 31 | CF | 15 | Unwinding of present value of interest free loan to employees | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 32 | CF | 15 | Royalty | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 33 | CF | 15 | Workers’ profit participation fund | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 34 | CF | 15 | Provision for deferred employee benefits | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 35 | CF | 15 | Unwinding of discount on provision for decommissioning cost | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 36 | CF | 15 | Interest income on investments and bank deposits | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 37 | CF | 15 | Interest income on lease | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 38 | CF | 15 | Unwinding of lease liability | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 39 | CF | 15 | Un-realized gain on investments at fair value through profit or loss | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 40 | CF | 15 | Realized gain on investments at fair value through profit or loss | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 41 | CF | 15 | Exchange loss on lease | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 42 | CF | 15 | Exchange loss on foreign currency investments and deposit accounts | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 43 | CF | 15 | Dividend income from investment at fair value through profit or loss | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 44 | CF | 15 | Gain on disposal of property, plant and equipment | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 45 | CF | 15 | Share of profit in associates - net of taxation | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 46 | CF | 15 | Stores inventory written off | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 47 | CF | 15 | Cost of dry and abandoned wells during the quarter | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 48 | CF | 15 | Reversal of trade debts provision | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 49 | CF | 15 | Stores, spare parts and loose tools | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 50 | CF | 15 | Stock in trade | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 51 | CF | 15 | Trade debts | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 52 | CF | 15 | Deposits and short term prepayments | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 53 | CF | 15 | Loan and advances and other receivables | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 54 | CF | 15 | Trade and other payables | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 55 | CF | 15 | Cash generated from operations | Keep | — | Operating cash before tax payments; no standard code. New code would need approval | High | No | Reusable |
| 56 | CF | 15 | Royalty paid | Keep | — | Royalty paid in cash; no standard code | High | No | Reusable |
| 57 | CF | 15 | Deferred employee benefits paid | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 58 | CF | 15 | Long term advances and prepayments | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 59 | CF | 15 | Decommissioning cost paid | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 60 | CF | 15 | Payment to workers’ profit participation fund-net | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 61 | CF | 15 | Income taxes paid | Keep | — | Tax paid in cash; no standard code (taxation is the P&L charge) | High | No | Reusable |
| 62 | CF | 15 | Interest received | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 63 | CF | 15 | Lease payments received | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 64 | CF | 15 | Dividends received | Keep | — | Dividends received (inflow); distinct from dividends_paid (outflow): not mapped to avoid a sign error | High | No | Reusable |
| 65 | CF | 15 | Term Finance Certificates interest received | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 66 | CF | 15 | Investments at fair value through profit or loss - net | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 67 | CF | 15 | Investment in associates | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 68 | CF | 15 | Proceeds from disposal of property, plant and equipment | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 69 | CF | 15 | Net cash (used in) /generated from investing activities | Keep | — | Net investing cash flow; no standard code. New code 'cfi' would need owner approval | High | No | Reusable |
| 70 | CF | 15 | Lease payments made | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 71 | CF | 15 | Net cash used in financing activities | Keep | — | Net financing cash flow; no standard code. New code 'cff' would need owner approval | High | No | Reusable |
| 72 | CF | 15 | Net increase /(decrease) in cash and cash equivalents | Keep | — | Net change in cash; no standard code. Useful for the cash identity; new code would need approval | High | No | Reusable |
| 73 | CF | 15 | Cash and cash equivalents at beginning of the quarter | Keep | — | Opening cash for the cash flow; no standard code, a new code would need approval | High | No | Reusable |
| 74 | CF | 15 | Effect of movements in exchange rate on cash and cash equivalents | Keep | — | Cash flow line: no standard code; kept unmapped | High | No | Reusable |
| 75 | CF | 15 | Cash and cash equivalents at end of the quarter | Keep | — | Closing cash in the cash flow (321,457,827) is NOT the balance sheet cash line (39,711,514): mapping both to one code would conflict. Kept unmapped; definition to be confirmed from the notes | High | No | Reusable |
| 76 | IS | 12 | Royalty | Keep | — | Cost of sales component (royalty); covered by the structural cost-of-sales subtotal | High | No | Reusable |
| 77 | IS | 12 | Operating expenses | Keep | — | Cost of sales component; covered by the structural cost-of-sales subtotal | High | No | Reusable |
| 78 | IS | 12 | Transportation charges | Keep | — | Cost of sales component; covered by the structural cost-of-sales subtotal | High | No | Reusable |
| 79 | IS | 12 | Finance and other income | Keep | — | Other income: no standard code exists; a new code would need owner approval | High | No | Reusable |
| 80 | IS | 12 | Exploration and prospecting expenditure | Keep | — | Income statement component: no standard code; kept unmapped | High | No | Reusable |
| 81 | IS | 12 | General and administration expenses | Keep | — | Income statement component: no standard code; kept unmapped | High | No | Reusable |
| 82 | IS | 12 | Workers’ profit participation fund | Keep | — | Statutory fund charge; OGDC presentation; no standard code | High | No | Reusable |
| 83 | IS | 12 | Share of profit in associates -net of taxation | Keep | — | Income statement component: no standard code; kept unmapped | High | No | Reusable |
| 84 | IS | 12 | Profit before income tax and final taxes | Keep | — | Subtotal before final levies: a different measure from profit before income tax; ambiguous, kept unmapped | High | No | Reusable |
| 85 | IS | 12 | Final taxes -levies | Keep | — | Final levies, separate from income tax expense; mapping it to taxation would misstate tax | High | No | Reusable |
| 86 | IS | 12 | Profit before income tax | Propose | profit_before_tax | Profit before income tax after final taxes; the figure that reconciles to profit after tax | High | Yes: profit_after_tax identity | Reusable |
| 87 | IS | 12 | Profit for the quarter | Propose | profit_after_tax | Profit for the period after taxation | High | Yes: profit_after_tax identity | Reusable |
| 88 | IS | 12 | Earnings per share- basic and diluted (Rupees) | Propose | eps_basic | Basic and diluted EPS in rupees | High | No (EPS consistency only, not yet checked) | Reusable |

## Summary
- Distinct ordinary labels reviewed: 88
- Proposed for owner approval: 4
- Kept unmapped (no standard code): 84
- Unresolved figure rows (not labels): the cash-flow subtotal '105,987,076 72,895,745' on page 15 has no structural rule and stays unresolved.

## New canonical codes needed (owner decision, not proposed as mappings)
`cfi` (net investing cash flow), `cff` (net financing cash flow), `net_change_in_cash`, `cash_opening`, `cash_generated_from_operations`, `income_tax_paid`, `other_income`. Adding any of these changes the schema or config and needs approval.

## What approval unlocks (tested in a disposable database only)
Applying the three proposed profit and EPS mappings (test overlay, not approved) makes the profit-after-tax identity pass (58,513,345 = 87,988,861 − 29,475,516) and enables net margin 44.19%, ROE 14.84% (annualised), ROA 12.40% (annualised) and cash conversion 0.588. Those values were checked by hand against the page figures.
