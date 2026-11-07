# Data availability and access assessment

Status: **ASSESSMENT ONLY, for owner review.**
- No source is approved or activated by this document.
- No production change, migration, collection run, provider contact or LLM call was made.
- Prepared 2026-11-07 on `main` @ `98b167a`.

## Approval status (unambiguous)
| Item | Status |
|---|---|
| Sources approved for production automated collection | **None** |
| Sources ACTIVE | **None** (registry and production) |
| Production data extraction | **Not authorised** |
| API purchases or provider contracts | **Not authorised** |
| Live LLM processing | **Not authorised** (provider not connected) |
| Production migrations 0006–0008 | **Blocked** until verified on a disposable Turso database and separately approved |
| Basis for future approval | Data rights evaluated **source by source and right by right**; technical accessibility is never legal permission |

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
2. **Priority 1 candidates.** These are free and technically working, with no prohibition found:
   - RSS feeds of Dawn, Business Recorder, Express Tribune and PBS;
   - ADB publications, whose terms permit reuse with attribution.

   **A working feed is not a grant of rights.** For these four feeds, every right in §A0 (collection,
   storage, indexing, retention, LLM processing, redistribution) is **UNCONFIRMED**, for each field
   (headline, link, timestamp, summary). **No blanket "RSS metadata-only" policy is approved or
   proposed for approval here.**

   The next step is to obtain each publisher's terms or written permission. Only then can the owner
   decide, field by field, what may be collected and stored.
3. **Official open-data APIs are the most promising macro and energy route.** These are the World
   Bank Indicators API, the EIA Open Data API (free key), the IMF data services and ADB data.
   - Free access is not production approval.
   - Each right (registration, attribution, storage, caching and retention, backfill, LLM processing,
     redistribution) is assessed per API in §A4b, and most are **UNCONFIRMED**.
4. **PSX data:** automated retrieval from PSX websites is **prohibited** without written permission.
   - The lawful options are a licensed redistributor (Capital Stake documents a PUCARS webhook and REST
     API; Mettis advertises MG Link) or a PSX data licence.
   - **A personal-use download does not authorise** persistent database storage, bulk retention,
     backfill, LLM extraction or reuse in an intelligence product.
   - **Written clarification from PSX is required** before any manually downloaded PSX document enters
     the persistent intelligence database or is sent to an external LLM.
   - Manual import stays a *proposed* workflow only. See §A2.
5. **Blocked official sources:** SBP, SECP, Ministry of Commerce, IMF website and OPEC returned
   HTTP 403 to automated requests. These are candidates for official API or data channels, or manual
   import. They are never to be bypassed.
6. **X and YouTube:**
   - YouTube: the Data API (key, daily quota) gives video metadata. Captions for third-party videos are
     **not** downloadable through the official API without the owner's authorisation.
   - X: read access needs a paid API tier (price UNCONFIRMED). Defer.
7. **Schedule**, once sources are approved:
   - a **15-minute** default batch during PSX hours (5 minutes only if independently justified,
     permitted and reliable);
   - a full **after-close** reconciliation;
   - an **overnight** deduplication and maintenance batch.

   GitHub Actions start times are **not** guaranteed latency, and **no 5–15 minute SLA is offered**.
   See `COLLECTION_SCHEDULING_STRATEGY.md`.
8. **Market data** (prices, volume, OHLCV, indices, corporate actions) has **no lawful free automated
   route** today. See §A6.

## Part A — Source-by-source findings

### A0. RSS feeds: what a feed does and does not authorise
A public RSS feed is a technical delivery format. It does **not** by itself authorise any of the
following. Each right needs the publisher's terms or written permission:

| Right | Meaning | Status for Dawn, Business Recorder, Express Tribune, PBS |
|---|---|---|
| Automated collection | a scheduled program fetching the feed | **UNCONFIRMED** (no terms pages found; robots.txt allows, but robots.txt is not a licence) |
| Persistent storage | keeping items in our database | **UNCONFIRMED** |
| Database indexing / search | making items searchable over time | **UNCONFIRMED** |
| Retention | how long items may be kept | **UNCONFIRMED** |
| External LLM processing | sending text to a third-party model | **UNCONFIRMED** |
| Redistribution | showing items to anyone except the owner | **Not proposed**; UNCONFIRMED |

The fields in a feed carry different risk, so they are assessed separately:

| Field | Nature | Notes |
|---|---|---|
| Headline | short expressive text | likely protected as part of the publication; rights UNCONFIRMED |
| Link (URL) | locator | lowest risk, but storing it in an index is still covered by the above |
| Publication timestamp | factual metadata | low risk; rights UNCONFIRMED |
| Feed summary / description | publisher's text (Express Tribune's feed carries **full article text**) | highest risk; storing or sending it to an LLM needs explicit permission |

**No blanket "RSS metadata-only" policy is approved.** The Phase 2 collectors can run dry runs
technically, but production collection of these feeds waits for per-publisher, per-right confirmation.

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

**Manual download and import (proposed only):**
- An individual personal-use download is permitted (single copy, personal, non-commercial).
- That permission does **not** automatically extend to:
  1. persistent storage in a private database;
  2. bulk retention of documents;
  3. historical backfilling, even by manual downloads in bulk;
  4. LLM extraction (sending text to an external model);
  5. reuse inside an intelligence product, even a private one.
- **Written clarification from PSX is required** before manually downloaded PSX documents are used in
  the persistent intelligence database or sent to an external LLM. Ask in the same request as the
  licence question (PR #7 §9).
- Until then, PSX manual import remains a proposal, and the owner reading documents personally is the
  only permitted use.

### A3. Government and regulatory sources
| Source | Channel found | Access result | Terms | Assessment |
|---|---|---|---|---|
| Ministry of Commerce | none (site blocked) | **HTTP 403** on home page and robots.txt | not reviewed | Ask for an official channel, or manual import; never bypass |
| State Bank of Pakistan | none confirmed; publishes statistical releases and PDFs | **HTTP 403** on robots.txt | no reuse terms on the disclaimer page | Ask SBP about permitted access (the SBP data portal is UNCONFIRMED); manual import |
| SECP | none confirmed | **HTTP 403** on home page (robots allows) | not reviewed | Ask SECP; manual import |
| PBS | **RSS** `https://www.pbs.gov.pk/feed/` | Dry run passed: 10 items | no terms page found | Candidate; all rights UNCONFIRMED (see §A0); not approved |
| FBR | none found | reachable | Terms allow residents to copy and print single pages to share information; automated collection **not addressed** | UNCONFIRMED; ask FBR |
| OGRA | none (`/rss` is an HTML page) | robots allows | no reuse terms | Notification PDFs are manual-import candidates; automated metadata UNCONFIRMED |
| NEPRA | none; sitemaps published | robots allows | none found | Determinations are PDFs; manual import, or metadata after terms are confirmed |
| Finance Division | none found | robots allows | none found | UNCONFIRMED |
| Ministry of Energy (Petroleum, Power) | official addresses to be verified | not reviewed | not reviewed | Not reviewed |
| ECC / Cabinet, EAD, Planning, CCP, PTA, NDMA, Privatisation | not reviewed | — | — | Not reviewed |

### A4. International sources
| Source | Channel | Access / registration | Rate limits | Storage and LLM rights | Assessment |
|---|---|---|---|---|---|
| World Bank | **Indicators API** `https://api.worldbank.org/v2/` (documented at `https://datahelpdesk.worldbank.org/knowledgebase/topics/125589`), no key | — | UNCONFIRMED | Datasets are typically published under the World Bank open-data licence (`https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets`); **confirm per dataset (UNCONFIRMED)**. The website terms (personal, non-commercial) differ from the dataset terms. | Candidate; rights UNCONFIRMED (see §A4b); not approved |
| IMF | IMF data services (SDMX API; see `https://data.imf.org`) | website returned **HTTP 403** to automated requests | UNCONFIRMED | UNCONFIRMED | Investigate the API and its terms; do not use the blocked website |
| EIA | **Open Data API v2** `https://www.eia.gov/opendata/` (free key) | key from the owner | UNCONFIRMED (documented on the API page; to be read) | US government public-domain content; acknowledgement requested | Candidate via the API (rights per §A4b); the RSS route is **refused** by robots.txt (`Disallow: /rss`). Not approved. |
| OPEC | none confirmed | **HTTP 403** | not reviewed | — | Manual import of monthly reports (terms UNCONFIRMED) |
| IEA | — | not reviewed | — | Much data is licensed (UNCONFIRMED) | Priority 4 |
| ADB | publications and data | reachable | — | Terms permit reuse with attribution (recorded 2026-11-07) | Candidate (rights per §A4b); not approved |
| WTO, OECD | APIs exist (UNCONFIRMED details) | not reviewed | — | — | Investigate |
| Reuters | — | — | — | Licence required | Priority 5 until licensed (ADR-0003 C6) |
| Commodity prices (Brent, LNG, coal, urea) | EIA API covers US and international oil series; others UNCONFIRMED | — | — | — | Use EIA first; others need a licensed or open source |

### A4b. API licensing, right by right
Free or public access is **not** production approval. **No API is production-approved.**

| Right | EIA Open Data API | World Bank Indicators API | IMF data API | ADB data and publications |
|---|---|---|---|---|
| Free access | Yes | Yes | Yes (UNCONFIRMED for the current API) | Yes |
| Registration | Free API key required (owner registers) | None for the API | UNCONFIRMED | None for public downloads |
| Attribution | Requested (EIA as source); exact wording UNCONFIRMED | Required under the dataset licence (UNCONFIRMED per dataset) | UNCONFIRMED | Required |
| Private storage | Public-domain content suggests yes; **UNCONFIRMED** for API terms | UNCONFIRMED per dataset licence | **UNCONFIRMED** | Permitted with attribution per terms recorded 2026-11-07; **confirm** |
| Retention and caching | UNCONFIRMED (API terms not read) | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED |
| Historical backfill | Technically supported (date ranges); rights UNCONFIRMED; rate limits to be read | Technically supported; UNCONFIRMED | Technically supported; UNCONFIRMED | Per document; UNCONFIRMED |
| External LLM processing | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED |
| Redistribution | Not proposed; public domain, but terms UNCONFIRMED | Not proposed; licence-dependent | Not proposed; UNCONFIRMED | Not proposed; attribution terms |
| Production status | **Not approved** | **Not approved** | **Not approved** | **Not approved** |

### A5. X and YouTube
Watchlists are stored in `database/seed/media_watchlist.json`: 23 X handles and 2 pending, plus
7 YouTube channels.

| Platform | Official access | Free limits | Paid | Alternatives | Transcripts | Storage / processing | Practical delayed option |
|---|---|---|---|---|---|---|---|
| YouTube | YouTube Data API v3 (`https://developers.google.com/youtube/v3`), API key | Default quota of 10,000 units/day per project, per Google's documentation; per-call costs are listed in the quota calculator | Quota increases by application | Per-channel public feeds exist, but their status as a supported API is **UNCONFIRMED**; do not rely on them without review | `captions.download` needs authorisation by the video's owner, so third-party captions are **not** available officially; mark transcripts unavailable | YouTube API Services Terms and Developer Policies, `https://developers.google.com/youtube/terms` (storage limits apply; **UNCONFIRMED** for our use) | Hourly or after-close: list new uploads per channel (metadata only) within quota |
| X | X API (`https://developer.x.com`) | The free tier's read access is very limited or absent (**UNCONFIRMED**) | Paid tiers needed for reading timelines; **price UNCONFIRMED** (not assumed) | None permitted; no scraping | — | Developer Agreement restricts storage and redistribution (**UNCONFIRMED** for our use) | Defer to Phase 11 with a costed proposal |

### A6. Market data (prices, volume, indices, corporate actions)
Purpose: identify lawful options for future fundamental and news event-reaction analysis. This
project does **not** connect to or reuse the separate technical engine (ADR-0001). No PSX endpoint
was accessed and no collection experiment was run for this section.

| Data | Official PSX availability | Individual download | Permitted API or licensed provider | Historical availability | Automation rights | Storage and retention | Cost and limitations |
|---|---|---|---|---|---|---|---|
| Daily stock prices (close) | PSX Data Portal and Downloads page (daily market files) | Yes, for personal use (single copy) | Capital Stake EOD unadjusted and adjusted (`/3.0/market/eod-adj`, documented); Mettis MG Link (advertised); PSX Data Services & Vending (delayed and real-time feeds) | Capital Stake: date ranges documented, depth not stated; PSX: on request | **Prohibited** on PSX sites without written permission; provider by agreement | UNCONFIRMED; must be named in an agreement | Prices not published |
| Daily traded volume | Same files | Same | Same (EOD includes volume) | Same | Same | Same | Same |
| Historical OHLCV | PSX Data Portal history pages (JavaScript-driven) | Personal viewing only | Capital Stake EOD plus 1/5/15-minute bars (documented); PSX licence | Capital Stake depth not stated | **Prohibited** on PSX sites; the third-party scrapers that pull from PSX (pypsx, adeerkhan/PSX-data) are **rejected** (PRs #8, #9) | UNCONFIRMED | Prices not published |
| KSE-100 and other indices | PSX index pages and daily files | Personal use | Provider index series (Capital Stake sample data appears to include index levels: UNCONFIRMED); PSX licence | UNCONFIRMED | **Prohibited** on PSX sites | UNCONFIRMED | Not published |
| Corporate actions and adjusted prices | PSX announcements (dividends, bonus, rights) | Personal use | Capital Stake payouts (dividends, bonus, rights, splits; dividends documented for the last 5 years), adjusted EOD | Partial (5 years for dividends) | Provider by agreement | UNCONFIRMED | Not published |
| Market breadth and sector performance | Derivable from daily files; PSX sector indices | Personal use | Derived from licensed EOD data; provider sector series UNCONFIRMED | Depends on EOD source | Same as underlying data | Same | — |

**Conclusion:**
- There is **no lawful free automated route** to PSX market data today.
- The options are:
  1. a licensed redistributor (Capital Stake first, Mettis as alternative), with private storage,
     retention, LLM processing and no redistribution written into the agreement;
  2. a PSX data licence;
  3. owner manual download, only for personal reading until PSX confirms storage rights in writing.
- Event-reaction analysis (Phase 13) stays dependent on a licensed provider.

## Part F — Priority ranking
| Priority | Sources | Expected cost | Complexity |
|---|---|---|---|
| **1 — free, accessible, no prohibition found** (rights still UNCONFIRMED; not approved) | Dawn, Business Recorder, Express Tribune RSS (metadata); PBS RSS; EIA Open Data API; World Bank Indicators API; ADB documents | Free (EIA needs a free key) | Low: collectors exist for RSS; API adapters are small |
| **2 — free but needs clarification or written permission** | The News (fix the feed), Profit, Mettis news, Nukta, SCS Trade, FBR, OGRA, NEPRA, Finance Division, IMF data API, YouTube Data API (terms for storage), company IR websites, MUFAP / AMCs, brokers' public reports | Free | Medium: per-source terms and letters |
| **3 — manual-import candidates** | PSX announcements and downloads (owner downloads; storage UNCONFIRMED), SBP, SECP and Commerce publications (403 to automation), OPEC reports, OGRA/NEPRA PDFs, company annual reports | Owner's time | Medium: needs the manual-import workflow |
| **4 — paid, evaluate later** | Capital Stake (PUCARS webhook, REST, EOD and market data), Mettis MG Link, PSX data licence (incl. market data), X API, IEA data | **Not published; quotes needed** | Medium to high |
| **5 — do not use** | PSX website automation, Investify automation, Sarmaaya automation, Reuters without licence, adeerkhan/PSX-data and pypsx scrapers (PR #8, #9), PSX Terminal closed API (PR #10), any bypass of HTTP 403, robots or CAPTCHA | — | — |

## Remaining permission uncertainties (all UNCONFIRMED)
1. Whether the Pakistani publishers permit automated RSS metadata collection, private storage and LLM
   processing of their headlines and summaries. No terms pages were found.
2. Whether PSX permits private storage and LLM extraction of documents the owner downloads manually.
3. Whether SBP, SECP and the Ministry of Commerce offer an official data channel.
4. World Bank, IMF and EIA API terms for storage and LLM processing, and their exact rate limits.
5. YouTube API storage limits for our use, and the X API price and terms.
6. Capital Stake and Mettis pricing and licence scope (see PR #7 §9 for the exact questions), including
   market data (EOD, OHLCV, indices, adjusted prices) and history depth.
7. Field-level rights for RSS items (headline, link, timestamp, summary) at each publisher.
