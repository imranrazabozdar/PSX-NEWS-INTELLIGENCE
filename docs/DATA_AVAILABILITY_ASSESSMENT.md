# Data availability and access assessment

Status: **ASSESSMENT ONLY, for owner review.**
- No source is approved or activated by this document.
- No production change, migration, collection run, provider contact or LLM call was made.
- Prepared 2026-11-07 on `main` @ `98b167a`.

Companion documents:
- [`SOURCE_ACCESS_MATRIX.md`](SOURCE_ACCESS_MATRIX.md): per-source scheduling and permission matrix.
- [`COLLECTION_SCHEDULING_STRATEGY.md`](COLLECTION_SCHEDULING_STRATEGY.md): the delayed batch architecture.
- [`MANUAL_IMPORT_DESIGN.md`](MANUAL_IMPORT_DESIGN.md): owner-download fallback (design only).

## Method and evidence base
- **Evidence:** the findings rest on reviews already recorded in this repository:
  - the source registry (`database/seed/sources.json`) and `docs/SOURCE_ACCESS_REGISTER.md`, with live
    dry runs and robots/terms checks on 2026-11-07;
  - `docs/INVESTIFY_SCS_TRADE_ASSESSMENT.md` (PR #6, merged);
  - `docs/PSX_ANNOUNCEMENT_ACCESS_INVESTIGATION.md` (PR #7, open);
  - `docs/PYPSX_CAPITAL_STAKE_PROVIDER_ASSESSMENT.md` (PR #8, open).
- **No new requests:** per the owner's instruction, no new network requests were made to any provider
  for this assessment.
- **UNCONFIRMED:** any permission, limit or price not established by those reviews or by the
  provider's public documentation is marked **UNCONFIRMED**. It must be read on the provider's own
  page, or confirmed in writing, before approval.
- **Separate rights:** being able to download a page is **not** permission to collect, store, retain,
  process with an LLM or redistribute it. Each right is assessed separately.

## Executive recommendation
1. **Lawful first, automated second.**
   - No source is currently cleared for automated production collection, because no publisher's terms
     have been approved (`terms_status = approved` for none).
   - The first step is an owner decision on terms, not engineering.
2. **Priority 1 candidates.** These are free, technically working, with no prohibition found, but
   permission is unconfirmed:
   - RSS headline-and-link metadata from Dawn, Business Recorder, Express Tribune and PBS;
   - ADB publications, whose terms permit reuse with attribution.

   Recommended owner decision: either approve a documented **"RSS metadata-only" policy** (title, link,
   publication time and short feed summary; no full text; no LLM processing of full articles), or write
   to each publisher first.
3. **Official open-data APIs are the best macro and energy route.** These are the World Bank
   Indicators API, the EIA Open Data API (free key) and the IMF data services. Each still needs its
   terms read and confirmed for storage and LLM use (UNCONFIRMED).
4. **PSX data:** automated retrieval from PSX websites is **prohibited** without written permission.
   - The lawful options are a licensed redistributor (Capital Stake documents a PUCARS webhook and REST
     API; Mettis advertises MG Link), a PSX data licence, or a **manual import** of documents the owner
     downloads personally.
   - Even manual import needs confirmation that private database storage and LLM extraction are
     covered (UNCONFIRMED).
5. **Blocked official sources:** SBP, SECP, Ministry of Commerce, IMF website and OPEC returned
   HTTP 403 to automated requests. These are candidates for official API or data channels, or manual
   import. They are never to be bypassed.
6. **X and YouTube:**
   - YouTube: the Data API (key, daily quota) gives video metadata. Captions for third-party videos are
     **not** downloadable through the official API without the owner's authorisation.
   - X: read access needs a paid API tier (price UNCONFIRMED). Defer.
7. **Schedule:**
   - a **15-minute** scheduled batch during PSX hours, for permitted RSS and API sources only;
   - a full **after-close** batch;
   - an **overnight** reconciliation.

   GitHub Actions can run this at no infrastructure cost for this public repository. Schedules are
   best-effort and can be delayed, so the 5–15 minute target is a goal, not a guarantee. See
   `COLLECTION_SCHEDULING_STRATEGY.md`.

## Part A — Source-by-source findings

### A1. Pakistani financial and news sources
| Source | Feed / API | Technical status (2026-11-07) | Terms found | Automated collection | Private storage | Retention | External LLM processing | Cost | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Dawn | RSS `https://www.dawn.com/feeds/business` | Dry run passed: 30 items, all timestamped | No terms page at `/terms` | UNCONFIRMED (robots allows; no prohibition found) | UNCONFIRMED (metadata only planned) | UNCONFIRMED | UNCONFIRMED; full text not stored | Free feed | Archive on site; depth UNCONFIRMED |
| Business Recorder | RSS `https://www.brecorder.com/feeds/business-finance` (also latest-news) | Dry run passed: 30 items | Not found | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Free feed | — |
| Express Tribune | RSS `https://tribune.com.pk/feed/business` | Dry run passed: 25 items; feed carries full text | Not found | UNCONFIRMED | UNCONFIRMED; project stores metadata only | UNCONFIRMED | UNCONFIRMED | Free feed | Full text in the feed is not stored |
| The News | RSS `/rss/1/8` | Parses, but **stale** (newest item 2026-05-29) | Not found | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Free | The correct business feed must be identified first |
| Profit (Pakistan Today) | No feed at `/feed/` (404); sitemap published | robots allows | Not found | UNCONFIRMED; sitemap use not assessed | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Free site | Needs a publisher answer |
| Mettis Global (news) | No feed (404); sitemap | robots allows | Not found | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Data via MG Link API is licensed (price not published) | Also a PSX-authorised redistributor |
| Investify | — | — | **Prohibits** automated access and reuse without written permission | **Prohibited** | Prohibited without permission | — | — | — | RESTRICTED (PR #6) |
| Nukta | — | Did not respond (2026-11-07) | Not reviewed | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | — | Official domain to be confirmed |
| SCS Trade | — | — | No terms published | UNCONFIRMED (absence of terms ≠ permission) | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | — | Written clarification needed |
| Sarmaaya | — | — | **Prohibits** bots and scraping; personal non-commercial use | **Prohibited** | Prohibited | — | — | Consumer plans are not data licences | RESTRICTED |

Other publications discovered but **not reviewed** (no claims made):
- The Nation, Arab News Pakistan, ProPakistani, Geo/The News business pages, Pakistan Today main site.

These should be added to the registry as NOT REVIEWED if the owner wants them assessed.

### A2. PSX official data (separate rights)
| Right | Status | Basis |
|---|---|---|
| 1. An individual downloading a document in a browser | **Permitted** for personal, non-commercial use (single copy) | PSX Terms of Use, `https://www.psx.com.pk/psx/terms-of-use` |
| 2. Automated retrieval (any program, any rate, one item or many) | **Prohibited** without prior written permission | Same terms: robots, spiders and "systematic retrieval to create collections, compilations, databases or directories" |
| 3. Storing documents in a private database | **UNCONFIRMED**, likely "compilation"; needs written permission or a licence | Same terms; PSX legal notice on commercial use of market data |
| 4. Historical bulk backfill | **Prohibited** without permission or licence | Systematic retrieval |
| 5. LLM extraction | **UNCONFIRMED**; must be named explicitly in any licence | Not addressed by the public terms |
| 6. Redistribution of documents or extracted data | **Not needed and not proposed**; prohibited without licence | PSX Data Services & Vending |

What PSX offers:
- no public API;
- no RSS;
- no alert sign-up found;
- a Downloads page with daily market files, under the same terms;
- data requests via `marketdatarequest@psx.com.pk`;
- licences through Data Services & Vending (real-time and delayed feeds; price not published).

Authorised redistributors listed by PSX:
- **Capital Stake:** documents REST, WebSocket and a `pucars` webhook for corporate announcements
  (`https://csapis.com`).
- **Mettis Global:** MG Link API.
- **Sarmaaya:** consumer site only.

PUCARS (PSX's corporate-action reporting system) had an expired TLS certificate when checked, so it
was **not verified**.

Coverage by data type:

| PSX data type | Lawful route today | Route needing permission or licence |
|---|---|---|
| Company announcements, material information, board meetings, corporate actions | Owner reads them manually (personal use) | Capital Stake `pucars` webhook / REST; Mettis; PSX licence |
| Financial statements, annual and quarterly reports | Company's own IR website (per-company terms; see `SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`); owner manual download | Redistributor financials endpoints (Capital Stake documents `/3.0/company/financials/...`) |
| Daily market summaries, historical reports | Owner manual download from the Downloads page (personal use) | PSX data licence; redistributor EOD endpoints |

**Manual download and import:**
- The owner downloading files is permitted.
- Importing them into the private database and running LLM extraction is **UNCONFIRMED** under PSX's
  terms (compilation/database clause).
- Recommendation: ask PSX in writing, in the same request as the licence question (PR #7 §9), before
  using manual import for PSX documents.

### A3. Government and regulatory sources
| Source | Channel found | Access result | Terms | Assessment |
|---|---|---|---|---|
| Ministry of Commerce | none (site blocked) | **HTTP 403** on home page and robots.txt | not reviewed | Ask for an official channel, or manual import; never bypass |
| State Bank of Pakistan | none confirmed; publishes statistical releases and PDFs | **HTTP 403** on robots.txt | no reuse terms on the disclaimer page | Ask SBP about permitted access (the SBP data portal is UNCONFIRMED); manual import |
| SECP | none confirmed | **HTTP 403** on home page (robots allows) | not reviewed | Ask SECP; manual import |
| PBS | **RSS** `https://www.pbs.gov.pk/feed/` | Dry run passed: 10 items | no terms page found | Priority 1 candidate (metadata) pending terms confirmation |
| FBR | none found | reachable | Terms allow residents to copy and print single pages to share information; automated collection **not addressed** | UNCONFIRMED; ask FBR |
| OGRA | none (`/rss` is an HTML page) | robots allows | no reuse terms | Notification PDFs are manual-import candidates; automated metadata UNCONFIRMED |
| NEPRA | none; sitemaps published | robots allows | none found | Determinations are PDFs; manual import, or metadata after terms are confirmed |
| Finance Division | none found | robots allows | none found | UNCONFIRMED |
| Ministry of Energy (Petroleum, Power) | official addresses to be verified | not reviewed | not reviewed | Not reviewed |
| ECC / Cabinet, EAD, Planning, CCP, PTA, NDMA, Privatisation | not reviewed | — | — | Not reviewed |

### A4. International sources
| Source | Channel | Access / registration | Rate limits | Storage and LLM rights | Assessment |
|---|---|---|---|---|---|
| World Bank | **Indicators API** `https://api.worldbank.org/v2/` (documented at `https://datahelpdesk.worldbank.org/knowledgebase/topics/125589`), no key | — | UNCONFIRMED | Datasets are typically published under the World Bank open-data licence (`https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets`); **confirm per dataset (UNCONFIRMED)**. The website terms (personal, non-commercial) differ from the dataset terms. | Priority 1 candidate for the API after a terms read |
| IMF | IMF data services (SDMX API; see `https://data.imf.org`) | website returned **HTTP 403** to automated requests | UNCONFIRMED | UNCONFIRMED | Investigate the API and its terms; do not use the blocked website |
| EIA | **Open Data API v2** `https://www.eia.gov/opendata/` (free key) | key from the owner | UNCONFIRMED (documented on the API page; to be read) | US government public-domain content; acknowledgement requested | Priority 1 via the API. The RSS route is **refused** by robots.txt (`Disallow: /rss`). |
| OPEC | none confirmed | **HTTP 403** | not reviewed | — | Manual import of monthly reports (terms UNCONFIRMED) |
| IEA | — | not reviewed | — | Much data is licensed (UNCONFIRMED) | Priority 4 |
| ADB | publications and data | reachable | — | Terms permit reuse with attribution (recorded 2026-11-07) | Priority 1 for documents; feed address to be located |
| WTO, OECD | APIs exist (UNCONFIRMED details) | not reviewed | — | — | Investigate |
| Reuters | — | — | — | Licence required | Priority 5 until licensed (ADR-0003 C6) |
| Commodity prices (Brent, LNG, coal, urea) | EIA API covers US and international oil series; others UNCONFIRMED | — | — | — | Use EIA first; others need a licensed or open source |

### A5. X and YouTube
Watchlists are stored in `database/seed/media_watchlist.json`: 23 X handles and 2 pending, plus
7 YouTube channels.

| Platform | Official access | Free limits | Paid | Alternatives | Transcripts | Storage / processing | Practical delayed option |
|---|---|---|---|---|---|---|---|
| YouTube | YouTube Data API v3 (`https://developers.google.com/youtube/v3`), API key | Default quota of 10,000 units/day per project, per Google's documentation; per-call costs are listed in the quota calculator | Quota increases by application | Per-channel public feeds exist, but their status as a supported API is **UNCONFIRMED**; do not rely on them without review | `captions.download` needs authorisation by the video's owner, so third-party captions are **not** available officially; mark transcripts unavailable | YouTube API Services Terms and Developer Policies, `https://developers.google.com/youtube/terms` (storage limits apply; **UNCONFIRMED** for our use) | Hourly or after-close: list new uploads per channel (metadata only) within quota |
| X | X API (`https://developer.x.com`) | The free tier's read access is very limited or absent (**UNCONFIRMED**) | Paid tiers needed for reading timelines; **price UNCONFIRMED** (not assumed) | None permitted; no scraping | — | Developer Agreement restricts storage and redistribution (**UNCONFIRMED** for our use) | Defer to Phase 11 with a costed proposal |

## Part F — Priority ranking
| Priority | Sources | Expected cost | Complexity |
|---|---|---|---|
| **1 — free, accessible, no prohibition found** (still needs owner terms approval) | Dawn, Business Recorder, Express Tribune RSS (metadata); PBS RSS; EIA Open Data API; World Bank Indicators API; ADB documents | Free (EIA needs a free key) | Low: collectors exist for RSS; API adapters are small |
| **2 — free but needs clarification or written permission** | The News (fix the feed), Profit, Mettis news, Nukta, SCS Trade, FBR, OGRA, NEPRA, Finance Division, IMF data API, YouTube Data API (terms for storage), company IR websites, MUFAP / AMCs, brokers' public reports | Free | Medium: per-source terms and letters |
| **3 — manual-import candidates** | PSX announcements and downloads (owner downloads; storage UNCONFIRMED), SBP, SECP and Commerce publications (403 to automation), OPEC reports, OGRA/NEPRA PDFs, company annual reports | Owner's time | Medium: needs the manual-import workflow |
| **4 — paid, evaluate later** | Capital Stake (PUCARS webhook, REST), Mettis MG Link, PSX data licence, X API, IEA data | **Not published; quotes needed** | Medium to high |
| **5 — do not use** | PSX website automation, Investify automation, Sarmaaya automation, Reuters without licence, adeerkhan/PSX-data and pypsx scrapers (PR #8, #9), PSX Terminal closed API (PR #10), any bypass of HTTP 403, robots or CAPTCHA | — | — |

## Remaining permission uncertainties (all UNCONFIRMED)
1. Whether the Pakistani publishers permit automated RSS metadata collection, private storage and LLM
   processing of their headlines and summaries. No terms pages were found.
2. Whether PSX permits private storage and LLM extraction of documents the owner downloads manually.
3. Whether SBP, SECP and the Ministry of Commerce offer an official data channel.
4. World Bank, IMF and EIA API terms for storage and LLM processing, and their exact rate limits.
5. YouTube API storage limits for our use, and the X API price and terms.
6. Capital Stake and Mettis pricing and licence scope (see PR #7 §9 for the exact questions).
