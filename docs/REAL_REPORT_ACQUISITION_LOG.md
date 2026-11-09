# Real annual-report acquisition log (M2 real-data readiness)

Status (2026-11-09): **no annual report acquired. Real-data validation not performed.** This log records what was
attempted, so that no later session repeats an attempt the policy already ruled out.

## Source policy applied
1. Official PSX disclosures and repositories first, then company investor-relations sites.
2. No login, paywall, CAPTCHA, rate-limit or access-control bypass. No unauthorised scraping.
3. A permissive robots.txt does not override a site's terms.

## Attempts
| Source | Attempt | Result | Reason |
|---|---|---|---|
| PSX data portal `dps.psx.com.pk` | Read home page links; robots.txt | Page links reachable; robots.txt returns 404 HTML | The project's register records PSX Terms of Use prohibiting automated navigation and systematic retrieval without written permission. Not downloaded. |
| PSX financial repository `financials.psx.com.pk` | Connect | Refused by the network proxy (HTTP 403 on tunnel) | Host not on the environment's allowlist. Not requested, because the terms above would still apply. |
| `www.psx.com.pk` | robots.txt | Allows all except `/cgi-bin/` | Permissive robots file does not override the PSX terms. Not used for document retrieval. |
| UBL, HBL, OGDC, Fauji Fertilizer, Lucky Cement, NetSol (investor-relations domains) | Connect | Refused by the network proxy (HTTP 403 on tunnel) | Not on the environment's allowlist. Company IR review is research task R1, not yet approved. |

## What is needed to proceed (owner)
1. **Company IR review (R1):** approve read-only review of named company IR sites, or add them to the approved hosts
   after their terms are checked.
2. **Or an owner-downloaded sample:** the owner downloads the PDFs through a normal browser and records them through
   `docs/MANUAL_IMPORT_DESIGN.md` (source URL, download date, rights attestation). This was the owner's stated
   preference, and it is not automated retrieval.
3. **PDF library approval (U3):** `pdfplumber` 0.11.10 (MIT) is recommended as the single reader. `pypdf` 7.0.0
   (BSD-3-Clause) is optional. Both pass the known-vulnerability check, and both support the project's Python
   3.12. Not installed.
