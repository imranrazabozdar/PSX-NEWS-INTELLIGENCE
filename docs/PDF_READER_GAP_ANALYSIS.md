# PDF reader: evidence-based gap analysis

Scope: `engines/pdf_reader.py`, `engines/pdf_extraction.py`, `engines/subtotals.py`, `engines/financials.py`.
Evidence: three owner-supplied OGDCL documents (SHA-256 in `OGDC_ACCOUNTING_RECONCILIATION.md`) and the synthetic
fixtures in `tests/`. Synthetic results are not real-world accuracy.

| Area | Demonstrated on real documents | Demonstrated on synthetic tests only | Not demonstrated |
|---|---|---|---|
| Single-column statements | Interim report pp 10–15 and 34–39 parse; 35 figures match page images | Labels, brackets, dashes, notes | Any other company's layout |
| Side-by-side statements | Annexure B balance sheet: two columns split at gutter 413 pt, 12 agreeing rows | Gutter detection, uncertain flag, page-wide headings ignored | Other side-by-side layouts |
| Consolidated and unconsolidated | Both scopes of one document imported separately | Scope isolation, duplicate key includes scope | Two documents with different scopes |
| Negative figures and brackets | Yes (cash flow, tax) | Yes | — |
| Thousands separators and lakh grouping | Yes (1,234,567 style) | Lakh grouping tests | Irregular grouping in real filings |
| Dashes and nil | Yes (nil items in adjustments block) | Dash counted as nil only in block sum | Dashes meaning "not applicable" vs "not reported" distinguished in text |
| Note references | Yes | Yes | Notes with multi-digit references beyond the 1–2 digit rule |
| Figures inside labels | Refused (flagged), never stored under a guessed label | Yes | — |
| Touching glyphs | Three joins in annexure B; 0.0 pt gap rule | Yes | Other encodings |
| Text-layer digit splits with a gap | Not observed | — | Gaps of 0.1–0.2 pt or larger |
| Structural subtotals | Equity, assets, current totals, cost of sales, liabilities-and-equity total, cash-flow adjustments | Positive and negative | Subtotals whose operands are on other pages |
| Unlabelled totals | Recognised only by the fixed rules | Yes | Any unlabelled total outside those rules is left unresolved |
| Multi-page statements | Cash flow on one page; balance sheet over two pages (assets page and liabilities page) | Continuation by page list | Automatic continuation detection (pages are listed by hand) |
| Repeated headers and footers | Headings and signatures ignored for gutter check | Yes | Headers that contain figures |
| Scanned pages | FY2026 annexure: 15 of 16 pages refused (`extraction_failed`) | Yes | OCR accuracy at scale (Tesseract evaluated on 2 pages only) |
| Notes and disclosures | Not parsed as statements; read for evidence only in manual review | — | Automated note extraction (ageing tables, ECL, borrowings schedules) |
| Annual-report narrative sections | Not extracted | — | Chairman, directors' report, auditor's report, governance |
| Multi-year comparatives | Two periods per statement | — | Three-plus-year histories from one document |
| Tables spanning pages | Not detected automatically | — | Automatic table continuation |

## Exception classes implemented
- `extraction_failed`: no statement lines extracted; nothing stored.
- `layout uncertain`: gutter not established or a label/figure crosses it; the page is refused, not parsed.
- `not_reported` (dash or nil): stored as not reported, never zero.
- `unlabelled, unresolved`: a figures-only row not recognised by a rule; stored with no canonical code and flagged.
- `needs_review`: an import with unparsed lines or scanned pages.

## Known failure modes
1. A text layer that splits a figure with a real (non-touching) gap is not repaired and is flagged.
2. A label that contains a figure is refused, so a legitimate label containing a number (for example a standard number) is also flagged.
3. Subtotal rules rely on exact arithmetic; a restatement inside a block makes the block unrecognised (flagged).
4. Scanned pages are not read. OCR is not approved for production.

## Conclusion
The reader is reliable for the single-column and side-by-side statements tested on the OGDC documents, and it refuses
rather than guesses in the cases above. It is **not** an annual-report reader. Notes, narrative sections, auditor
reports and multi-year histories are not implemented and must not be presented as analysed.
