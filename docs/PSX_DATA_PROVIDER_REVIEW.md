# PSX data and provider review

Checked 2026-11-07 (UTC). Builds on PR #7 (announcements) and PR #8 (Capital Stake), which are open.
No PSX or provider data endpoint was accessed.

## 1. PSX official terms (primary)
`https://www.psx.com.pk/psx/terms-of-use` (loaded 2026-11-07):
- "…spiders, robots, avatars, agents, tools or other devices or mechanisms to navigate, search or
  determine the PSX Website is strictly prohibited."
- "You may print or download a single, unaltered, permanent copy or one temporary copy in a single
  computer's memory of any Content for your personal, non-commercial use only…"
- "Use for any other purpose is expressly prohibited by law…"
- It prohibits "…systematic retrieval to create collections, compilations, databases or
  directories…" and transferring content to others, including within your organisation.

| Right | Status |
|---|---|
| Viewing | Permitted |
| Individual manual download | **Single copy, personal, non-commercial** |
| Automated retrieval (any rate) | **PROHIBITED** |
| Persistent database storage | **PROHIBITED** without permission (compilations and databases clause) → WRITTEN_PERMISSION_REQUIRED |
| Historical bulk backfill | **PROHIBITED** |
| Internal analytical use | Beyond "personal, non-commercial" → WRITTEN_PERMISSION_REQUIRED |
| LLM extraction | Not addressed; covered by "any other purpose" → WRITTEN_PERMISSION_REQUIRED |
| Redistribution | PROHIBITED (not proposed) |

This applies to every PSX data category: announcements, results, notices, daily summaries,
historical prices, profiles, indices, sectors, corporate actions, dividends and OHLCV.

## 2. Licensed providers
| Provider | Official API | OHLCV history | Delayed / real-time | Announcements | Financials | Indices / sectors | Bulk | Docs | Price | Storage / internal / LLM / derived | PSX authority |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Capital Stake** | Yes, per PR #8 (`csapis.com` docs: REST, WebSocket, `pucars` webhook). `csapis.com` is **not reachable from this session**, so those claims are **not re-verified today**. Home page (loaded) advertises "Stocks Data From real-time market data and company financials to corporate actions", "PSX Data", commodities, PKR FX and "Economic Indicators", with "View Documentation" links. | Documented per PR #8 (EOD adjusted and unadjusted, intraday bars); depth not stated | Real-time advertised; delayed UNCONFIRMED | Yes per PR #8 (PUCARS mirror, webhook) | Yes (advertised) | Yes (advertised) | Date-range queries | Yes (PR #8) | **QUOTE_REQUIRED** (none published) | All UNCONFIRMED; must be in a written agreement | Listed by PSX as an authorised redistributor (PR #7, 2026-11-07); scope "subject to PSX's prior approval and license" |
| **Mettis Global** | **MG Link API** (`https://mettisglobal.news/MGAPIs`): "real-time exchange data", "corporate calendars" | UNCONFIRMED | Real-time advertised | Calendars advertised | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | Not public | **QUOTE_REQUIRED** | UNCONFIRMED | Listed by PSX as an authorised redistributor (PR #7) |
| **SCS Trade (Standard Capital Securities)** | None found. The site shows price data, historical prices and indices, plus links to "Online Trading Terms" and "SLA From Software Vendor". | Displayed on site only | — | Displayed | Displayed | Displayed | No | No | — | **No permission found**. The PR #6 finding of no published reuse terms stands. An existing trading account does **not** grant automated access or storage rights. | Not shown as a redistributor |
| **Sarmaaya** | No API | — | 15-minute delayed on free plan (PR #7) | Site | — | — | — | — | Consumer plans are not data licences (PR #7) | Prohibited (PR #7) | Listed as a redistributor, but no API product |
| **PSX Data Services & Vending** | Licensed feeds (real-time and delayed) | On request | Both | — | — | Yes | Per product | On request | **QUOTE_REQUIRED** | By licence | Owner of the data |

## 3. Historical OHLCV and market data
- **No free, lawful route was verified in this review** to historical PSX OHLCV, adjusted prices,
  indices or market breadth for a database. PSX's own websites are excluded by its **verified** Terms of
  Use. Other free sources were not exhaustively searched.
- **Cheapest credible delayed prices:** QUOTE_REQUIRED from Capital Stake, Mettis or PSX vending. None
  publish prices. A delayed or EOD-only licence is likely the narrowest product to ask for
  (UNCONFIRMED).
- **Cheapest credible history:** QUOTE_REQUIRED. Ask each provider for depth (years), adjustment
  method, CSV export, and storage, retention and LLM rights.
- **Manual download for a private database:** only after PSX confirms in writing. The terms permit a
  personal single copy only.

**Approval gate:** Capital Stake and Mettis remain **unverified candidates**. Before either is
selected or activated, it must confirm in writing its authority to license the underlying PSX data,
and every right in `DATA_ACQUISITION_RESOLUTION.md` §7:
- automated retrieval, current and historical data, corporate announcements and actions;
- storage, retention, internal display, LLM processing, derived facts and deletion obligations.

Otherwise the route stays unresolved and is not activated.

## 4. Rejected routes
- pypsx and adeerkhan/PSX-data (scrape the PSX Data Portal; PRs #8 and #9).
- PSX Terminal (closed API, unknown upstream; PR #10).
- Any reverse-engineered PSX endpoint.
