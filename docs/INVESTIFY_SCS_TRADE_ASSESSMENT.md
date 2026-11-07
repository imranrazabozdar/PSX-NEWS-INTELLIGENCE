# Investify and SCS Trade: assessment as PSX data providers

* **Date of review:** 2026-11-07
* **Scope:** investigation and feasibility only. Nothing was activated, stored in the project
  database, purchased or requested from either provider. PR #5 is not merged and Phase 3 has
  not started.
* **Method:** a small number of polite, human-paced HTTP requests from the project's cloud
  environment (about 2 seconds apart, descriptive User-Agent): robots.txt, sitemap, home page,
  terms, privacy, data-policy, about and research listing pages, plus PSX's own data-vending
  page. Data sampling stopped as soon as the terms showed that automated collection is
  prohibited (Investify) or unclear (SCS Trade), as instructed.

## 1. Conclusion

**Recommendation D: neither provider can currently be used without additional permission or
licensing.**

* **Investify** (Recube Technologies LLP) is a licensed PSX data client. Its Terms and
  Conditions expressly prohibit robots, scrapers and other automated means used to
  "systematically copy, collect, store or monitor Market Information … to build, supplement or
  feed a database … without the express written consent of Recube Technologies". They also
  prohibit redistribution, and its data API (`/api/v1/`) is disallowed in robots.txt. PSX's
  vending page does **not** mark Recube as authorised to redistribute PSX data, so even with
  Recube's consent, PSX-sourced market data would still need PSX's licence or approval.
* **SCS Trade** (Standard Capital Securities (Pvt.) Ltd, a PSX broker) publishes no website
  Terms of Use, no API and no feed. Its footer reserves "proprietary rights". It is not on PSX's
  list of data clients. Automated use is therefore **unclear** and needs written permission.
  Its research, mutual-fund and payout reports are broker publications whose reuse terms are
  not stated.

The project's existing safeguards already prevent any use. Neither provider is added as
ACTIVE, and the PSX registry entries stay RESTRICTED.

## 2. Provider identity (VERIFIED)

| | Investify | SCS Trade |
|---|---|---|
| Domain | https://www.investify.pk/ | https://scstrade.com/ |
| Operator | Recube Technologies LLP (stated in Terms and About page) | Standard Capital Securities (Pvt.) Ltd, brokerage, formed 1990, incorporated 1998 (About page) |
| Contact shown | support@investify.pk (PSX vending page, site) | info@scstrade.com, +92 21 111 111 721, Park Towers, Clifton, Karachi |
| PSX data status | Listed as PSX data client "6. Recube Technologies (investify.pk)", **not** marked authorised to redistribute | Not on PSX's data-client list |
| Other | App "Investify PSX Stocks Pakistan" (Google Play, App Store) | TradingView charting partner (privacy page) |

## 3. Provider comparison

Statuses: VERIFIED · PARTIALLY VERIFIED · NOT VERIFIED · NOT AVAILABLE · RESTRICTED · PERMISSION REQUIRED

| Requirement | Investify | SCS Trade |
|---|---|---|
| Company master | PARTIALLY VERIFIED: site navigation advertises "Every PSX share", company pages, sectors (not sampled) | PARTIALLY VERIFIED: menus list market valuations and stock lists (not sampled) |
| Announcements | PARTIALLY VERIFIED: `/announcements` listing; links carry PSX Data Portal document IDs (e.g. `/announcements/OGDC/dps-image-288835-1`), i.e. re-published PSX filings | PARTIALLY VERIFIED: "Announcements", "Board Meetings", "xPrice Dates" pages in menu (not sampled) |
| Financial statements | PARTIALLY VERIFIED: advertises "EPS, P/E, ROE, dividend yield, book value" and company financials (not sampled) | PARTIALLY VERIFIED: "Ratios & Financials", "Top Expected P/E", valuation matrix pages in menu (not sampled) |
| Historical prices | PARTIALLY VERIFIED: charts advertised; date range NOT VERIFIED | PARTIALLY VERIFIED: "Historical Prices", "Historical Indices" pages in menu; date range NOT VERIFIED |
| Corporate actions | NOT VERIFIED | PARTIALLY VERIFIED: public PDFs linked on home page: "PSX Company Dividend Schedule", "Merger Information", "Delisted Information", "PSX Change of Company Name Information" (not downloaded) |
| Mutual fund reports | NOT AVAILABLE (none found) | PARTIALLY VERIFIED: `/research/RE_Mutual_Fund_Reports.aspx` listing with date filter (contents not sampled) |
| Broker research | NOT AVAILABLE (Investify is not a broker; shows Buy/Sell/Neutral labels) | PARTIALLY VERIFIED: company, market, technical, trading-desk reports, news briefs, MTS report (not sampled) |
| API availability | RESTRICTED: `/api/v1/` exists but is disallowed in robots.txt; no public API documentation found | NOT AVAILABLE (none found) |
| Authorised feed | PERMISSION REQUIRED (none advertised; would also need PSX redistribution approval) | NOT AVAILABLE / PERMISSION REQUIRED |
| Terms reviewed | VERIFIED (Terms and Conditions, Data & Editorial Policy, Privacy, About) | VERIFIED: no website terms of use exist; privacy policy and disclaimer reviewed |
| Automated access permitted | RESTRICTED: prohibited without express written consent | NOT VERIFIED (terms silent; no robots.txt) → PERMISSION REQUIRED |
| Database storage permitted | RESTRICTED: storing to "build, supplement or feed a database" prohibited | PERMISSION REQUIRED |
| Historical retention permitted | RESTRICTED | PERMISSION REQUIRED |
| Streamlit display permitted | RESTRICTED: personal licence only; no redistribution or providing access to others | PERMISSION REQUIRED |
| LLM processing permitted | PERMISSION REQUIRED: robots.txt carries `Content-Signal: ai-input=yes, ai-train=yes`, but the Terms (which govern) prohibit systematic collection | PERMISSION REQUIRED |
| Pricing | NOT AVAILABLE: only consumer "Ad-free Services" subscriptions mentioned; no data licence pricing published | NOT AVAILABLE: none published |

"Not sampled" means the page exists in the site's own navigation, but its data was not fetched
for testing, because automated retrieval is prohibited or unclear.

## 4. Technical findings

| Tested URL | Result | Notes |
|---|---|---|
| https://www.investify.pk/robots.txt | 200 | `Allow: /`; `Disallow: /api/v1/, /api/account/, /api/auth/, /api/community/, /api/health, /settings`; sitemap declared; `Content-Signal: search=yes, ai-input=yes, ai-train=yes` |
| https://www.investify.pk/sitemap.xml | 200 (2.5 KB) | sitemap index |
| https://www.investify.pk/ | 200 (≈600 KB) | Next.js app; links to `/terms`, `/privacy`, `/data-policy`, `/announcements`, `/psx-data-portal-alternative` |
| https://www.investify.pk/terms | 200 | Terms and Conditions (key clauses quoted in §5) |
| https://www.investify.pk/data-policy | 200 | "Market data: licensed from PSX … under a Pakistan Stock Exchange data license held by Recube Technologies (investify.pk)" |
| https://www.investify.pk/about, /psx-data-portal-alternative | 200 | product description |
| https://scstrade.com/robots.txt | 404 | no robots.txt |
| https://scstrade.com/sitemap.xml | 200 (35 KB) | site map |
| https://scstrade.com/ | 200 (≈240 KB) | ASP.NET WebForms pages; live ticker in HTML; links to research and report PDFs |
| https://scstrade.com/PrivacyPolicy.aspx, /AboutUs/AboutUs.aspx | 200 | privacy policy, disclaimer, company identity |
| https://scstrade.com/research/RE_Mutual_Fund_Reports.aspx, /research/RE_Reports.aspx | 200 | report listings with date / company filters |
| https://www.psx.com.pk/psx/product-and-services/data-services-vending | 200 | PSX's authorised data-client list (evidence for §2) |

* **Response formats:** HTML only. Investify renders client-side (Next.js) and loads data from
  its own API, which robots.txt disallows. SCS uses server-rendered ASP.NET pages plus PDFs.
* **Failed requests:** none. No rate limiting was encountered at this volume (about 15
  requests in total, spread over several minutes).
* **Not done, by design:** no calls to `/api/v1/`, no undocumented endpoints, no downloads of
  report PDFs, no company/price/financial sampling, nothing stored.

## 5. Legal and licensing assessment

**Investify: Terms and Conditions (quoted, 2026-11-07)**
* "You may not use any robot, spider, scraper, crawler or other automated means to
  systematically copy, collect, store or monitor Market Information or other Content from the
  Services, including to build, supplement or feed a database, product or service … without the
  express written consent of Recube Technologies."
* "… no part of the Services, Content and/or Marks … may be copied, reproduced, distributed,
  republished, downloaded, displayed … without Recube Technologies's prior explicit written
  consent."
* "You will not 'deep-link', redistribute or facilitate the redistribution of Market
  Information …" Users receive a "limited personal license".
* Market Information is "sourced from or related to Pakistan Stock Exchange (PSX), CS
  Solutions (Pvt.) Limited (CS) and other market data providers". Recube's PSX licence is
  personal to Recube. PSX's page says redistribution needs PSX approval, and that "PSX license
  and permission to use market data still applies to the third party(s) or sub client(s)".

**SCS Trade**
* No website Terms of Use. The only terms are "Online Trading Terms" for trading clients.
* Footer: "Standard Capital reserves the right to terminate the accounts of subscribers /
  customers, who violate the proprietary rights, in addition to necessary legal action."
* No licence or reuse statement for its research reports. PSX-sourced market data shown by a
  broker remains subject to PSX's licensing.

**Private versus public use:** both providers' published terms allow, at most, personal
viewing. Our use would be private and internal: storing in our own Turso database, historical
retention, display in a private dashboard, and LLM processing. That still falls under
"collect, store … feed a database", which needs written permission. Public redistribution
would additionally need PSX's licence or approval.

## 6. Data-quality comparison

**NOT PERFORMED.** Comparing UBL, BOP, NETSOL, HUBCO, SSGC, OGDC, LUCK and SYS across both
sites would have meant automated retrieval of the data that Investify's terms prohibit and that
SCS Trade has not authorised. The instruction was to stop when access is not permitted or
unclear, and no values were recorded. This comparison can be run once written permission (or a
licensed feed) is in place. The comparison plan in §8 is ready for that.

## 7. Recommended integration architecture

The platform should not depend on any single provider. Proposed layers, each needing its own
authorisation:

1. **Primary disclosures:** each listed company's own website and filings (annual and
   quarterly reports are published by the companies). Terms are company-specific and must be
   reviewed per company. PSX announcements require PSX's written permission.
2. **Licensed PSX market data:** either a direct PSX licence (Data Services & Vending), or a
   PSX-**authorised redistributor** with a sub-licence approved by PSX. The PSX page marks
   Capital Stake, Mettis Global and Sarmaaya Financials as authorised to redistribute. These
   are candidates to evaluate next. None has been contacted.
3. **Value-added providers (optional):** Investify (fundamentals, announcement summaries) and
   SCS Trade (broker research, mutual-fund reports, dividend/merger/delisting schedules), only
   under written agreements that cover storage, retention, private display and LLM processing.
4. **Engine:** each provider is a separate `sources` entry with its own terms, licensing and
   retention mode. The Phase 2 registry, ACTIVE gate and provenance already support this. Each
   value stays attributable to its provider, and cross-provider differences are recorded rather
   than silently merged.

## 8. Outstanding questions for providers (owner to ask; nothing has been sent)

**To Recube Technologies (Investify), support@investify.pk**
1. Do you offer an official API or data feed for third parties, and on what terms and price?
2. Can you grant written consent for automated collection, storage in our private database,
   historical retention, private dashboard display and LLM processing?
3. Does your PSX licence allow you to supply PSX-sourced data to us, or would PSX approval or a
   sub-licence be needed?
4. Which of your data (fundamentals, announcement summaries, news) is your own and not
   PSX-sourced?

**To Standard Capital Securities (SCS Trade), info@scstrade.com**
1. Are there website terms of use for the public pages and research reports?
2. Can you give written permission to collect and retain your research reports, mutual-fund
   reports and schedules (dividend, merger, delisting) for private analysis, display and LLM
   processing?
3. Is there a data feed or API (as a broker or otherwise), and at what cost?
4. Which of your market data is PSX-licensed, and what restrictions follow from that?

**To PSX (Data Services & Vending)**
1. What licence covers a private, non-redistributing research database of announcements,
   end-of-day prices and company information, and what does it cost?
2. Would a sub-licence through an authorised redistributor (Capital Stake, Mettis Global,
   Sarmaaya) cover this use?

## 9. Estimated costs

No pricing is published by Investify (data), SCS Trade or PSX (data licences). All costs
**require provider confirmation**. No expenditure is proposed until quotes are presented to the
owner.
