# Source access and scheduling matrix

Assessment only (2026-11-07).
- **No source is approved for production automated collection, and none is ACTIVE.**
- "Use after terms decision" means *a candidate*, not an approval. Every UNCONFIRMED right must be
  established first.
- A working RSS feed or a free API is never a grant of storage, retention, LLM or redistribution
  rights.

- **"Permitted interval":** what the provider's terms or documentation allow. UNCONFIRMED means no
  terms were found or read.
- **"Preferred interval":** the operational recommendation **if** the owner approves the source.
- Technical feasibility (does it work?) and legal permission (may we?) are separate columns.
- Market-hours, after-close and overnight windows are defined in `COLLECTION_SCHEDULING_STRATEGY.md`.

| Source | Data type | Access method | Technically feasible | Permitted interval | Preferred interval | Market-hours relevance | After-close relevance | Historical availability | Incremental | Rate limits | Storage permission | LLM processing | Cost | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Dawn (business) | News metadata | RSS | Yes (dry run passed) | UNCONFIRMED | 15 min (market hours), 60 min otherwise | High | High | Feed holds the latest ~30 items; site archive depth UNCONFIRMED | Yes (ETag / Last-Modified, item GUID) | None documented; project limit 1 req/host/≥2 s | UNCONFIRMED (metadata only) | UNCONFIRMED | Free | **Candidate**: rights UNCONFIRMED per field (headline, link, timestamp, summary) |
| Business Recorder | News metadata | RSS | Yes | UNCONFIRMED | 15 min / 60 min | High | High | Latest ~30 | Yes | None documented | UNCONFIRMED | UNCONFIRMED | Free | **Candidate**: rights UNCONFIRMED |
| Express Tribune | News metadata (feed has full text; not stored) | RSS | Yes | UNCONFIRMED | 15 min / 60 min | High | High | Latest ~25 | Yes | None documented | UNCONFIRMED | UNCONFIRMED | Free | **Candidate**: rights UNCONFIRMED |
| The News | News metadata | RSS (wrong or stale category) | Parses; stale | UNCONFIRMED | — | — | — | — | Yes | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** (find the current business feed) |
| Profit (Pakistan Today) | News | No feed; sitemap | Partially (sitemap) | UNCONFIRMED | — | Medium | Medium | UNCONFIRMED | Possible via sitemap lastmod (not assessed) | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** (ask the publisher) |
| Mettis Global news | News | No feed; sitemap | Partially | UNCONFIRMED | — | Medium | Medium | UNCONFIRMED | — | — | UNCONFIRMED | UNCONFIRMED | Free site; MG Link licensed | **Investigate** |
| Nukta | News | — | Not reachable | UNCONFIRMED | — | Low | Low | — | — | — | UNCONFIRMED | UNCONFIRMED | — | **Investigate** (domain) |
| Investify | Market and news | Website | — | **Prohibited** | — | — | — | — | — | — | Prohibited | Prohibited | — | **Reject** without written permission |
| SCS Trade | Market and news | Website | — | UNCONFIRMED (no terms) | — | — | — | — | — | — | UNCONFIRMED | UNCONFIRMED | — | **Investigate** (written clarification) |
| Sarmaaya | Market data | Website | — | **Prohibited** | — | — | — | — | — | — | Prohibited | Prohibited | Consumer plans only | **Reject** |
| PSX websites (www, DPS) | Announcements, filings, market files | Website / PDF | Technically yes | **Prohibited** (automation) | — | High | High | On site | No official mechanism | reCAPTCHA present | Not permitted without licence | Not permitted without licence | Licence price not published | **Reject automation; manual import only after written confirmation** |
| PSX Downloads (daily files) | Market summaries | Owner download | Yes (manual) | Personal single copy only | — | Low | High | On site | — | — | **Not authorised** without PSX written clarification | **Not authorised** without PSX written clarification | Free (manual) | **Proposed manual import only**, after PSX written clarification |
| Capital Stake | Announcements (PUCARS mirror), financials, EOD, payouts | REST, WebSocket, webhook | Documented | By agreement | Webhook (push) + after-close REST reconciliation | High | High | Date-range queries documented; depth UNCONFIRMED | Yes (webhook, date range) | UNCONFIRMED | By agreement | By agreement (must be named) | **Not published** | **Investigate later (Priority 4)** |
| Mettis MG Link | Market data, calendars | API | Advertised | By agreement | — | High | High | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | By agreement | By agreement | Not published | **Investigate later** |
| PUCARS | Corporate filings | Unknown | TLS certificate expired | Not verified | — | — | — | — | — | — | — | — | — | **Investigate** (ask PSX) |
| PBS | Statistics releases | RSS + PDFs | Yes (dry run passed) | UNCONFIRMED | 60 min; daily after close | Low | Medium | Site archive | Yes | None documented | UNCONFIRMED | UNCONFIRMED | Free | **Candidate**: rights UNCONFIRMED |
| SBP | Policy, statistics | Website / PDF | **HTTP 403** to automation | UNCONFIRMED | — | High (MPS days) | High | — | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Manual import; ask for official channel** |
| SECP | Regulatory notices | Website | **HTTP 403** | UNCONFIRMED | — | Medium | Medium | — | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Manual import; ask** |
| Ministry of Commerce | Trade policy | Website | **HTTP 403** | UNCONFIRMED | — | Medium | Medium | — | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Manual import; ask** |
| FBR | Tax notifications | Website / PDF | Reachable | Single-page copying allowed; automation not addressed | — | Medium | High | Site | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** (ask FBR) |
| OGRA | Price notifications | HTML / PDF | Reachable | UNCONFIRMED | — | High (price days) | High | Site | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Manual import or investigate** |
| NEPRA | Determinations | PDF; sitemaps | Reachable | UNCONFIRMED | — | Medium | High | Site | Sitemap lastmod (not assessed) | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** |
| Finance Division | Budget, fiscal | Website / PDF | Reachable | UNCONFIRMED | — | Low | Medium | Site | — | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** |
| World Bank | Indicators | Official API (no key) | Yes (documented) | Per API terms (UNCONFIRMED) | Weekly or overnight | Low | Low | Long history | Yes (by date) | UNCONFIRMED | Dataset licence per dataset (UNCONFIRMED) | UNCONFIRMED | Free | **Candidate**: not production-approved |
| IMF | Macro data | Data API (SDMX) | Documented (not tested) | UNCONFIRMED | Weekly or overnight | Low | Low | Long history | Yes | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** (website blocked) |
| EIA | Oil, gas, energy | Open Data API v2 (free key) | Documented | Per API terms; RSS **refused by robots.txt** | Daily after close; overnight | Medium | High | Long history | Yes | Documented on the API page (to be read) | Public domain (acknowledgement); API terms UNCONFIRMED | UNCONFIRMED | Free (key) | **Candidate**: not production-approved |
| OPEC | Oil market reports | Website / PDF | **HTTP 403** | UNCONFIRMED | — | Low | Medium | — | — | — | UNCONFIRMED | UNCONFIRMED | Free site | **Manual import** |
| ADB | Reports, data | Website / PDF | Reachable | Reuse with attribution | Weekly | Low | Low | Site | — | — | Permitted with attribution (confirm) | UNCONFIRMED | Free | **Candidate**: not production-approved |
| IEA | Energy data | Licensed | — | Licence | — | Low | Medium | — | — | — | Licence | Licence | Paid (UNCONFIRMED) | **Investigate later** |
| Reuters | News | Licensed | — | Licence required | — | High | High | — | — | — | Licence | Licence | Paid | **Reject until licensed** |
| YouTube (7 channels) | Video metadata | YouTube Data API v3 | Documented | API terms; daily quota | Hourly in market hours, or after close | Medium | Medium | Channel upload history | Yes (publishedAfter) | 10,000 units/day default | Limited by API terms (UNCONFIRMED) | UNCONFIRMED | Free quota | **Investigate** (key + terms); captions unavailable for third-party videos |
| X (23 + 2 accounts) | Posts | X API | Documented | Paid tier needed for reads | — | High | Medium | Tier-dependent | Yes | Tier-dependent | Developer agreement (UNCONFIRMED) | UNCONFIRMED | **Paid, price UNCONFIRMED** | **Defer** (Phase 11 cost proposal) |
| Company IR websites | Annual and quarterly reports | Website / PDF | Varies | Per company (UNCONFIRMED) | After close (on publication) | Low | High | Varies | Per document | — | UNCONFIRMED | UNCONFIRMED | Free | **Investigate** (`SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`) or **manual import** |

## Market data
| Source | Data type | Access method | Technically feasible | Permitted interval | Preferred interval | Market-hours relevance | After-close relevance | Historical availability | Incremental | Rate limits | Storage permission | LLM processing | Cost | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PSX Data Portal / Downloads | Daily prices, volume, indices, OHLCV | Website / owner download | Technically yes | **Automation prohibited**; personal single copy | — | Medium | High | On site | — | reCAPTCHA | Not authorised without PSX written permission | Not authorised | Free (personal) | **Reject automation**; personal reading only |
| Capital Stake | EOD adjusted and unadjusted, intraday bars, payouts, corporate actions | REST, WebSocket (documented) | Documented | By agreement | After-close EOD pull; webhook for corporate actions | Medium | High | Date ranges; dividends 5 years; other depth UNCONFIRMED | Yes | UNCONFIRMED | By agreement | By agreement | **Not published** | **Investigate later (Priority 4)** |
| Mettis MG Link | Market data, calendars | API (advertised) | Advertised | By agreement | After close | Medium | High | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | By agreement | By agreement | Not published | **Investigate later** |
| PSX Data Services & Vending | Delayed and real-time feeds, historical | Licence | Official | Licence terms | Per licence | Medium | High | On request | Per product | Per product | Licence | Must be named | Not published | **Investigate later** |
| pypsx, adeerkhan/PSX-data, PSX Terminal | Scraped or closed APIs | — | — | **Prohibited / unknown source** | — | — | — | — | — | — | — | — | — | **Reject** (PRs #8–#10) |
