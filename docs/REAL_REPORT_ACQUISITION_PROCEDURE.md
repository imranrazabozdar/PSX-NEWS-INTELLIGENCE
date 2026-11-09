# Source-acquisition procedure for real company financial reports

Status (2026-11-09): **no company report has been acquired.** Company investor-relations sites returned no
response from this environment (network policy). Their terms are therefore unread. Nothing here says any report
is lawfully obtainable until its site's terms have been read and recorded.

## Rules
1. A source is used only if its published terms allow the intended use: private internal research, storing the
   original file, and computing from its figures. Where terms are silent or prohibit automated access, nothing is
   retrieved automatically.
2. No login, paywall, CAPTCHA, rate-limit or access-control bypass.
3. A permissive robots.txt does not on its own permit systematic retrieval.
4. The owner may download a document personally through a normal browser and import it under
   `docs/MANUAL_IMPORT_DESIGN.md`, recording the source URL, the download date and the rights attestation.
5. Nothing is invented. A missing report is recorded as missing.

## Steps for each candidate (one row per source)
| Step | Record |
|---|---|
| 1. Official investor-relations or disclosure page | URL; ticker |
| 2. Published terms and copyright notice | Terms URL; what they permit or prohibit; date read |
| 3. robots.txt | Result; whether the report path is disallowed |
| 4. Route | `lawful_public_download` / `permission_required` / `prohibited` / `unreviewed` |
| 5. For `lawful_public_download`, a small sample by ordinary means | Document SHA-256; download date; URL |
| 6. Filing date only if printed on the document or stated by the publisher; else `unknown` | Date and evidence |
| 7. Scope (consolidated or standalone), currency, units, audit status | As printed |

## Candidates (unverified; none checked)
UBL, HBL (banking); OGDC, PSO (oil and gas); FFC, EFERT (fertiliser); LUCK, KOHC (cement); NETSOL, SYS
(technology). These come from the owner's brief.

## Current result
Every candidate was unreachable from this environment, so every route is `unreviewed`.
