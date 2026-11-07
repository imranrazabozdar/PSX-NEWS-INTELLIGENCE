# Data acquisition resolution

Research and documentation only (2026-11-07, `main` @ `09e84d4`).
- No collector, source activation, credential, migration, workflow or production change.
- No provider contact or purchase.
- Evidence comes from read-only fetches of official terms and documentation pages: one request each,
  an identified user agent, no data endpoints. Pages that returned 403 were recorded, not bypassed.
- This builds on PR #17 (merged) and PRs #6–#8. Where today's evidence differs, it is noted in §4.

Companion documents:
- [`PAKISTAN_NEWS_SOURCE_REVIEW.md`](PAKISTAN_NEWS_SOURCE_REVIEW.md)
- [`PSX_DATA_PROVIDER_REVIEW.md`](PSX_DATA_PROVIDER_REVIEW.md)
- [`MACROECONOMIC_DATA_SOURCE_REVIEW.md`](MACROECONOMIC_DATA_SOURCE_REVIEW.md)
- [`DATA_ACQUISITION_ACTION_PLAN.md`](DATA_ACQUISITION_ACTION_PLAN.md)

## 1. Overall conclusions
1. **Nothing can be safely activated today.** No source has verified rights for the full intended use
   (automated retrieval, storage and LLM processing) **and** an owner approval.
2. **Closest to approvable:**
   - **EIA Open Data:** public domain per its reuse page; the API ToS must still be read and the owner
     must register a key.
   - **ADB CC BY 3.0 IGO material:** per-item licence checks needed.
3. **Pakistani news:**
   - Express Tribune requires written consent for any reuse.
   - Dawn and Business Recorder now return HTTP 403 to an identified client, and their terms couldn't
     be read.
   - The others have no readable terms.
   - **There is no free, verified automated route.**
4. **PSX:**
   - Automated retrieval and database compilation are prohibited without written permission.
   - Manual download is limited to a personal, non-commercial single copy.
   - Every PSX dataset (announcements, prices, OHLCV, indices, corporate actions) needs either a PSX
     licence, written permission, or an authorised redistributor (Capital Stake or Mettis; prices
     QUOTE_REQUIRED).
5. **Government:**
   - SBP, SECP and the Ministry of Commerce return 403.
   - FBR's terms grant only single-page copying for sharing information.
   - NEPRA reserves all rights.
   - No dataset is verified for automation.

## 2. Classification scheme (per source and per data type)
| Classification | Meaning |
|---|---|
| `APPROVED_AUTOMATION` | verified permission for the intended automated retrieval and storage use |
| `APPROVED_METADATA_ONLY` | only specifically verified metadata fields may be collected and stored |
| `APPROVED_MANUAL_IMPORT` | manual import permitted under verified conditions |
| `WRITTEN_PERMISSION_REQUIRED` | access or intended use needs written permission |
| `LICENCE_REQUIRED` | a licence or paid subscription is needed |
| `TERMS_UNCLEAR` | available evidence is insufficient |
| `PROHIBITED` | the intended access or use is prohibited |
| `NOT_TECHNICALLY_AVAILABLE` | no usable official access route |
| `NOT_ASSESSED` | investigation incomplete |

**No source is assigned `APPROVED_AUTOMATION`, `APPROVED_METADATA_ONLY` or `APPROVED_MANUAL_IMPORT`
in this review.** EIA and ADB are marked "candidate" because one confirming step (the API ToS or the
per-item licence) and the owner's approval remain.

## 3. Strategies
| | A — Minimum-cost lawful | B — Hybrid | C — Comprehensive licensed |
|---|---|---|---|
| Components | EIA API, ADB CC BY material; owner manual reading; written-permission requests to publishers, PSX, SBP and FBR | A + one PSX redistributor (Capital Stake or Mettis: EOD/delayed prices, announcements, corporate actions) + 2–3 news permissions | Redistributor full package + PSX licence + licensed news (publisher licences or an aggregator) |
| Initial cost | 0 (owner time) | QUOTE_REQUIRED | QUOTE_REQUIRED |
| Monthly cost | 0 | QUOTE_REQUIRED | QUOTE_REQUIRED |
| Coverage | Energy and macro only; **no PSX prices; no news** until permissions arrive | PSX prices, announcements and history (depth UNCONFIRMED); core news | Broad |
| Frequency | Daily (EIA) | Delayed/EOD prices; webhook announcements | Up to real-time (not needed) |
| History | EIA long series | Provider depth UNCONFIRMED | Broadest |
| Legal certainty | High for EIA/ADB, nothing else | High **if** the agreements name storage, LLM and retention | High |
| Complexity | Low | Medium | High |
| Fit | Starting point; insufficient alone | **Recommended target** | Not justified (real-time not needed) |

## 4. Corrections to earlier records
- **Express Tribune:** PR #17 said "terms page not found". The copyright page
  `https://tribune.com.pk/copyrights` requires prior written consent for reuse.
- **Dawn and Business Recorder:** both now return HTTP 403 to an identified client. They were 200 on
  2026-11-07 earlier.
- **Investify:** the current terms add an AI-retrieval clause (with attribution) but still prohibit
  automated collection to feed a database.
- **EIA:** the reuse page confirms public domain; the API returns at most 5,000 rows per request.
- **World Bank:** the datasets terms page says "informational and non-commercial purposes only, unless
  otherwise stated", so a per-dataset licence check is required.
- **ADB:** CC BY 3.0 IGO for ADB-only material; CC BY NC ND for joint material.

## 5. Direct answers
1. **Free automated Pakistani news collection: no.** No publisher's permission was verified, and
   Tribune requires written consent.
2. **Publishers permitting metadata collection, storage and analysis: none verified.**
3. **Written permission required:** Express Tribune (explicit). Dawn, Business Recorder, The News,
   Profit and Mettis news must be asked (terms unclear). Investify requires consent for database use.
4. **Full article text:** not permitted for any verified publisher. Tribune prohibits it without
   consent.
5. **Practical route:** written licences from 2–3 core publishers, or a licensed aggregator
   (Mettis MG Link; QUOTE_REQUIRED).
6. **PSX announcements via an authorised provider:** plausibly yes, through Capital Stake (PUCARS
   webhook and REST per PR #8; not re-verified today because its docs host isn't reachable from this
   session) or Mettis, under agreement.
7. **Manual download into a private database:** the terms allow a personal, non-commercial single copy
   only. Database storage needs written permission from PSX.
8. **Historical OHLCV, legally:** yes, through a licence or redistributor only (QUOTE_REQUIRED). There
   is no free lawful route.
9. **Cheapest delayed prices:** QUOTE_REQUIRED (Capital Stake, Mettis, PSX vending). No public price.
10. **Cheapest history:** QUOTE_REQUIRED.
11. **Capital Stake: viable.** Unverified: current API docs, terms of service, price, history depth,
    rights to store, retain and process with an LLM, and confirmation of PSX approval for our use.
12. **Mettis: viable** (MG Link API advertised). Unverified: endpoints, price, history, rights.
13. **SCS Trade:** no published reuse permission. Database use needs written permission from Standard
    Capital, and PSX's licence still applies to the PSX data it shows.
14. **Free official international APIs:** EIA (public domain), ADB (CC BY items). World Bank and IMF
    have terms unclear. FRED was not assessed.
15. **Pakistani government datasets for automation: none verified.**
16. **Possible now, without licences:**
    - read the EIA API ToS and, after owner approval, register a key;
    - check ADB per-item licences;
    - draft permission letters;
    - design the per-source rights configuration (§6) in documentation;
    - continue synthetic-only Phase 5 development (separately authorised).
17. **Blocked until permission or a licence:** all PSX data, all Pakistani news storage, SBP, SECP,
    Commerce, FBR and NEPRA automation, X and YouTube storage.
18. **Recommended minimum-cost strategy:** start with Strategy A, then request quotes and move to
    Strategy B. See `DATA_ACQUISITION_ACTION_PLAN.md`.

## 6. Architecture recommendation (no implementation)
Each source should carry an explicit rights record, extending the current registry:

| Field | Purpose |
|---|---|
| Source id, access method | identity and route |
| Classification per data type | rights per §2 |
| Permitted fields | for example headline, link, timestamp only |
| Permitted processing | storage, index, LLM, derived facts |
| Permitted retention | period and deletion duty |
| Attribution | required wording |
| Minimum polling interval, maximum requests per day | provider limits |
| Collection interval | operational choice |
| Last checked, last published, last successful fetch | operations |
| Licence or terms review date, expiry | re-review trigger |
| Evidence URL, clause, date checked | provenance of the rights decision |

**Fail-closed:** a working URL never activates a source. Only an owner-approved rights record plus
lifecycle ACTIVE does. The existing `authorise()` gate would be extended to check permitted fields
and processing (a future, separately approved change).
