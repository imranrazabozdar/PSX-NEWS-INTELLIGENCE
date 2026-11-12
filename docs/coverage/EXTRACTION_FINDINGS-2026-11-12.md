# Extraction findings, 2026-11-12

Scope: what the deterministic extraction engine proved, what the live IR fetch reached, and why most published
PDFs could not be extracted. No network fetch, OCR, production or Turso write was made for this document. Figures
come from the existing pilot fixtures (`docs/coverage/EXTRACTION_COVERAGE.md`) and the throwaway identity run
(`scripts/run_position_identities.py`, six readable reports).

## Conclusion

**The engine works. The binding constraint is input quality, not the parser.**

- On the three pilots (UBL, OGDC, LUCK) all 30 extracted cells reconcile with zero delta. Five statements and two
  periods per company. Those PDFs came from owner-supplied uploads, not from a live fetch.
- NRL's identities were verified by hand: equity from components 799,666 + 4,407,382 + 46,134,419 = 51,341,467,
  matching the printed subtotal; PBT − tax = PAT holds on all four H1 columns.
- **All live-fetched PDFs that were reached were unusable for deterministic extraction.** HUBC quarters are
  image-only, PSO is vector-outline, and NRL has a shadow-corrupted text layer. HUBC's annual PDF does have a text
  layer, but its identity checks did not resolve (see below). Correction to the premise: LUCK was not fetched live,
  because its report host is robots-disallowed. Its figures came from the owner's upload.

## Per company

| Company | Live-fetch status | PDF machine-readability | Extraction outcome | Bucket |
|---|---|---|---|---|
| UBL | manual_import (no clean self-host; PSX store gated, not fetched) | clean text (owner upload) | 10 of 10 green (2 periods × 5 statements), pilot | Pilot, reconciled |
| OGDC | manual_import (Cloudflare challenge; not bypassed) | clean text (owner upload) | 10 of 10 green, pilot | Pilot, reconciled |
| LUCK | needs_manual (report host robots-disallowed) | clean text (owner upload) | 10 of 10 green, pilot | Pilot, reconciled |
| HUBC | live (reached) | annual: text layer present. Quarterly: **image-only** | Annual 2026-06-30: balance sheet requires_review (ambiguous), income statement unresolved. Quarterly: no extraction | Annual: not proven. Quarterly: needs_OCR |
| PSO | live (reached) | **vector-outline**, no text layer | Not extractable deterministically | needs_OCR |
| NRL | live (reached) | **shadow-corrupted text layer** (overprinted columns) | Balance sheet 2026-09-30 reconciles on components (flagged). Interim IS not resolved by the matcher. Hand-verified identities are sound | needs_manual |
| POL | todo_unreachable (TLS chain failed local verification; not disabled) | not assessed | none | Re-test from an environment with the CA trusted |
| ATRL | todo_unverified (report pages not yet fetched) | not assessed | none | Verify links first |
| PPL | blocked_by_site (Cloudflare on robots and homepage) | not assessed | none | Manual import, not bypassed |

## Why NRL is manual, not OCR

The matcher failed on NRL in two specific ways. Header-group detection did not find the quarter/half-year groups
on most interim pages, so the income statement stayed unresolved. Component matching dropped the
surplus-on-revaluation row on some pages: the NRL 2026-06-30 balance-sheet delta equals that figure exactly
(46,134,419). Both are layout problems in the auto-matcher. The fix is more matcher work, which this decision stops.
The owner keys NRL's key totals by hand; OCR is not used.

## What the identity run showed

Six readable reports, 2 periods × statement checks, status counts: reconciled 2 (NRL 2026-09-30 balance sheet,
components only, flagged), requires_review, unreconciled 2 (NRL 2026-06-30 balance sheet, surplus row dropped),
insufficient_data, and unresolved income-statement columns. These results are NOT evidence of reconciliation beyond
the two reconciled balance-sheet checks, and the NRL one rests on the same matcher.
