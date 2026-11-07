# Source-access review proposal: company annual reports and official company websites

Status: **PROPOSAL ONLY.** No source is registered, activated, fetched or contacted by this
document. It needs owner approval before any step is taken.

## Why it is needed
Phase 4 can only confirm a company exposure from company-specific evidence. Examples: a refinery
buying crude oil, floating-rate borrowings, export revenue share, subsidiaries and ownership. The
natural primary sources are the companies' own published annual and quarterly reports and investor
pages. None is registered or approved today, so every real mapping stays `unverified`.

## Proposed review, per company (start with the 50 listed companies in the master)
| Question | What to record | Evidence to keep |
|---|---|---|
| Official website and investor-relations URL | verified URL (https) | page reviewed and date |
| Terms of use or legal notice | automated access allowed / prohibited / silent | quoted clause and date |
| robots.txt | allows or disallows the reports path | snapshot hash and date |
| Automated access | permitted / needs permission / prohibited | basis |
| Storage | metadata only / excerpts / full document | basis |
| Retention period | how long excerpts may be kept | basis |
| Historical documents | whether archives may be used for backfill | basis |
| LLM processing | whether excerpts may be processed by a third-party LLM | basis; default **not permitted** until clarified |
| Redistribution in the private dashboard | permitted / not | basis |
| Contact for permission | IR or company secretary address (recorded, **not contacted**) | — |

## Proposed registry treatment (after approval)
- One source per company, for example `co_luck_ir`, with `source_type = 'other'` and category
  `company_reports`, starting at NOT REVIEWED and `retention_mode = metadata_only`.
- Lifecycle follows the existing rules: REVIEWED → TESTED (dry run) → ACTIVE only with
  `terms_status = approved`.
- Documents are fetched one by one with `collect_document` (PDF metadata only). The same permission
  gate and robots.txt checks apply.
- Exposure rows would be entered from reviewed excerpts (≤1000 characters) with `confidence =
  'documented'`. They would never be LLM-only.

## Out of scope until separately approved
- PSX filings, PUCARS and SECP eServices.
- Paid providers (Capital Stake, Mettis).
- Any scraping, any bypass of access controls, and any contact with companies without the owner's instruction.
