# Macroeconomic and government data source review

Checked 2026-11-07 (UTC) with read-only page fetches. "Free" never means unrestricted rights.

## 1. International
| Source | Access | Key | Limits | Licence evidence (primary) | Storage / caching | Internal use | LLM | Redistribution | Classification |
|---|---|---|---|---|---|---|---|---|---|
| **EIA Open Data** (`https://www.eia.gov/opendata/`) | API v2 | Free registration: "Registration and compliance with the API Terms of Service Agreement help EIA monitor usage" | "our API only returns a maximum of 5,000 rows" per request (documentation page); other rate limits not stated on the pages read | `https://www.eia.gov/about/copyrights_reuse.php`: "U.S. government publications are in the public domain… You may use and/or distribute any of our data, files, databases…"; acknowledgment requested ("Source: U.S. Energy Information Administration (date)") | Permitted (public domain) | Permitted | Not restricted by the reuse page; API ToS text **not read** | Permitted with acknowledgment | **Candidate (not approved)**: public domain verified on the reuse page. Still needed: the **API Terms of Service** read, the attribution wording recorded, a key registered by the owner, and **explicit owner approval**. |
| **World Bank** | Indicators API (no key) | None | UNCONFIRMED | Datasets terms page (`/en/about/legal/terms-of-use-for-datasets`): "provided for informational and non-commercial purposes only, unless otherwise stated". Per-dataset licences (e.g. on the Data Catalog) were not read. | UNCONFIRMED per dataset | Non-commercial private research likely fits; UNCONFIRMED | UNCONFIRMED | Not proposed | **TERMS_UNCLEAR** (check each dataset's licence) |
| **IMF** | Data services | — | — | `https://www.imf.org/external/terms.htm` returned **HTTP 403** | — | — | — | — | **TERMS_UNCLEAR** |
| **ADB** | Publications and data library | None | — | `https://www.adb.org/terms-use`: ADB-only material "under a Creative Commons Attribution (CC BY 3.0 IGO)"; jointly published "CC BY NC ND"; others "All Rights Reserved"; project data "may be… included in other products for commercial and noncommercial purposes at no cost" | Permitted for CC BY material with attribution | Permitted | Not restricted for CC BY material; UNCONFIRMED for others | Attribution | **Candidate (not approved)**: CC BY 3.0 IGO items only. Still needed: each dataset's or publication's licence checked (joint material is CC BY NC ND; others "All Rights Reserved"), attribution recorded, and **explicit owner approval**. |
| **FRED** (St. Louis Fed) | API (key) | Key | UNCONFIRMED | Host not reachable from this session | — | — | — | Series-level third-party restrictions are common (UNCONFIRMED) | **NOT_ASSESSED** |
| **World Bank Pink Sheet** (commodities) | Monthly files | — | — | Not read (same terms family as above) | UNCONFIRMED | — | — | — | **TERMS_UNCLEAR** |

Indicator coverage:
- **Brent, WTI, natural gas:** EIA.
- **Coal, gold, silver, cotton, wheat, palm oil:** World Bank Pink Sheet (UNCONFIRMED terms).
- **Pakistan reserves, current account, remittances, USD/PKR:** SBP (blocked; see below).
- **Global growth and inflation:** World Bank, IMF (unclear).
- **US rates:** FRED (not assessed).

## 2. Pakistan government and regulators
| Source | Result 2026-11-07 | Channels | Terms evidence | Classification |
|---|---|---|---|---|
| SBP (incl. EasyData) | **HTTP 403** (home); EasyData host not tested from this session | Statistical releases, EasyData portal (UNCONFIRMED) | Not readable | **WRITTEN_PERMISSION_REQUIRED** (ask SBP about EasyData or an API); manual import candidate |
| SECP | **HTTP 403** | — | Not readable | **TERMS_UNCLEAR**; ask |
| Ministry of Commerce | **HTTP 403** | — | Not readable | **TERMS_UNCLEAR**; ask |
| Finance Division / Economic Survey | Loaded; no terms link found | PDFs (annual survey) | None found | **TERMS_UNCLEAR**; manual import candidate |
| PBS | Loaded; RSS `/feed/` | Releases (CPI, trade) as PDF/Excel | No terms link found | **TERMS_UNCLEAR** (feed works) |
| FBR | Loaded | Notifications, SROs | `/Term-of-Use/544`: "Permission is granted to residents and citizens of Pakistan to copy electronically and to print single pages … without any deletion, addition or modification and for the sole purpose of sharing information" | **WRITTEN_PERMISSION_REQUIRED** (automation and database storage not granted) |
| OGRA | Loaded; `/rss` is not a feed | Price notifications | `/disclaimer`: "published for general information only… advised to confirm and verify" (no reuse grant) | **TERMS_UNCLEAR**; manual import candidate |
| NEPRA | Loaded | Determinations (PDF) | `/Legal.php`: "NEPRA Copyright 2023. All Rights Reserved." | **WRITTEN_PERMISSION_REQUIRED** |
| Pakistan Customs, trade statistics | Not checked | — | — | **NOT_ASSESSED** |

**No Pakistani government dataset is verified for automated collection and storage.**
