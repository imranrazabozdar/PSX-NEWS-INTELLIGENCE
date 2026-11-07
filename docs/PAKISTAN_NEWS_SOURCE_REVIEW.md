# Pakistan news source review

Checked 2026-11-07 (UTC). Read-only fetches of terms and home pages, one request each, with an
identified user agent. No articles were collected. Classifications follow
`DATA_ACQUISITION_RESOLUTION.md` §2.

**Rights are assessed separately for each publisher:**
- automated retrieval of the feed (headlines and metadata);
- storing headline, link, timestamp and summary;
- storing full text;
- indexing and search;
- LLM extraction;
- retaining derived facts;
- internal intelligence use.

| Publisher | Official feed / API | Terms evidence (verbatim where found) | Headline + metadata | Full text | LLM / derived facts | Classification | Confidence |
|---|---|---|---|---|---|---|---|
| **Express Tribune** | RSS index linked from site (`https://tribune.com.pk/rss`); business feed dry-run passed 2026-11-07 | `https://tribune.com.pk/copyrights`: "Re-use of The Express Tribune content is NOT permitted without prior written consent"; footer: "This material may not be published, broadcast, rewritten, redistributed or derived from." Reprints licensing offered. | Retrieval technically works; storage/indexing **not permitted without consent** | Not permitted without consent | "derived from" prohibited | **WRITTEN_PERMISSION_REQUIRED** (all stored uses) | High (primary terms) |
| **Dawn** | RSS `https://www.dawn.com/feeds/business` (dry-run passed 2026-11-07) | Terms page `https://www.dawn.com/terms` returned **HTTP 403** on 2026-11-07 to an identified client (home page earlier 200; feed earlier 200) | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | **TERMS_UNCLEAR** → ask in writing; also note new 403 | Low |
| **Business Recorder** | RSS feeds (dry-run passed 2026-11-07) | Home page returned **HTTP 403** on this check; no terms read | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | **TERMS_UNCLEAR** | Low |
| **The News International** | RSS `/rss/1/8` stale since May 2026; index not located | Home page loaded; no terms/copyright link found in page | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | **TERMS_UNCLEAR** | Low |
| **Profit (Pakistan Today)** | No feed found (`/feed/` 404 earlier) | Home page loaded; no terms link found | — | — | — | **NOT_TECHNICALLY_AVAILABLE** (feed) / **TERMS_UNCLEAR** | Low |
| **Pakistan Today** (parent) | Not checked separately | Not checked | — | — | — | **NOT_ASSESSED** | — |
| **Mettis Global** (news) | No feed; **MG Link API** page `https://mettisglobal.news/MGAPIs`: "MG Link API serves our clients by meeting their data inte[gration needs]… real-time exchange data" | No public terms or prices found | Licensed product | Licensed product | By agreement | **LICENCE_REQUIRED** (API, price QUOTE_REQUIRED) | Medium |
| **Investify** | No feed or API | `https://www.investify.pk/terms`: "You may not use any robot, spider, scraper, crawler or other automated means to systematically copy, collect, store or monitor … including to build, supplement or feed a database… without the express written consent of Recube Technologies." New clause: "This does not restrict … artificial intelligence services retrieving or learning from publicly available pages, at a reasonable request rate … Content used in this way must be attributed to 'Investify (investify.pk)'." | Database storage prohibited without consent | Same | AI-retrieval clause **does not cover** building a database; scope UNCLEAR | **PROHIBITED** (database collection) / **WRITTEN_PERMISSION_REQUIRED** | High |
| **Nukta** | Domain did not respond (2026-11-07) | — | — | — | — | **NOT_ASSESSED** | — |
| **Sarmaaya** | No API documented | `/terms` returned 404 this check. The earlier review (PR #7) recorded prohibitions on bots and scraping. | — | — | — | **PROHIBITED** (per PR #7; re-check terms URL) | Medium |
| **Tribune Business** | Same publisher as Express Tribune | Same terms | — | — | — | **WRITTEN_PERMISSION_REQUIRED** | High |
| ProPakistani, The Nation, Arab News PK | Not checked | — | — | — | — | **NOT_ASSESSED** | — |

## Findings
- **No Pakistani publisher has verified permission for automated storage or LLM processing.**
- Express Tribune's terms expressly require written consent for reuse, and prohibit redistribution and
  derived works.
- Dawn and Business Recorder now return HTTP 403 to this client, and their terms couldn't be read.
- The other publishers have no readable terms.
- **Most practical route:** written permission or a licence from 2–3 core publishers (Dawn, Business
  Recorder, Express Tribune). The request should name the exact rights: headline/link/timestamp
  storage, internal search, LLM extraction of facts, retention of derived facts, and no
  redistribution. Alternatively, use a licensed aggregator (Mettis MG Link; quote required).
