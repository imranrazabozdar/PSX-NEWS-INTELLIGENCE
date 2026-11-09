# PSX Terminal: provider assessment

* **Date of review:** 2026-11-07
* **Scope:** investigation only.
  * No package was installed and no API endpoint was called (not even `/api/status`).
  * No data was downloaded, stored or integrated, and nothing was purchased.
  * The provider was not contacted.
  * Only public web pages (robots.txt, sitemap, Terms, About, Services) and the public GitHub
    repository were read, at human pace.
* No source activated, production Turso untouched, PRs #5, #7, #8 and #9 not merged, Phase 3 not
  started.

## 1. Executive summary
* The supplied repository `mumtazkahn/psx-terminal` is **not publicly accessible**. A
  documentation repository with the same history exists at **`kaleemlab/psx-terminal`**, with
  every commit authored by `mumtazkahn`.
* The platform is operated by **RUNTIME TECHNOLOGIES (SMC-PRIVATE) LIMITED** (Islamabad).
* The REST/WebSocket API documented in that repository (v1.0.0, July 2025) has been **closed**.
  The live robots.txt says: "The closed public API: other sites still call it … should not fetch
  it".
* The current Terms of Service prohibit accessing the service "through automated means beyond
  normal use" and scraping or reselling its data "at scale without permission".
* The upstream data source is described only as "publicly available market data and company
  filings". Runtime Technologies is **not** on PSX's list of authorised data clients. The upstream
  licence is therefore **UNKNOWN**.

**Recommendation: DO NOT USE** (§14).

## 2. Repository identity and ownership
| Item | Finding | Evidence |
|---|---|---|
| `mumtazkahn/psx-terminal` | Not publicly readable: anonymous `git ls-remote` was refused ("could not read Username"), which is GitHub's response for a missing or private repository. A rename would normally redirect. The GitHub user `mumtazkahn` exists. | git ls-remote, GitHub user search (2026-11-07) |
| `kaleemlab/psx-terminal` | Public; repository created 2025-07-08; 4 commits from 2025-06-25 to 2025-07-08 (HEAD `8db5c56`), **all authored by `mumtazkahn <mumtazz1993@gmail.com>`**; single branch `main`; 5 stars. README badges and SECURITY.md still link to `github.com/mumtazkahn/psx-terminal`. | read-only clone |
| Relationship | Same project: identical history and author, so most likely transferred to, or re-published under, `kaleemlab`. **Not verified** who controls `kaleemlab`. | — |
| Other similarly named repositories | `nordixsoft/psx-terminal` (a different CLI terminal, 2026-04), `Zainulabid138/PSX-terminal`, and others. **Unrelated.** The owner's own `imranrazabozdar/PSX-TERMINAL` was not touched. | GitHub repository search |
| Contents | **Documentation only:** `API.md`, `ARCHITECTURE.md`, README, CHANGELOG (v1.0.0, 2025-07-01), examples (Python clients), screenshots. **No server code**, so the data pipeline cannot be inspected. | file listing |
| Licence | MIT for the "Software" (the docs and examples), plus a "Market Data Disclaimer: Educational and Informational Use Only … should NOT be used for … investment advice … commercial trading strategies". | `LICENSE` |
| Operator of psxterminal.com | **RUNTIME TECHNOLOGIES (SMC-PRIVATE) LIMITED**, Islamabad; "Registered with the SECP (CUIN 0340194) · NTN J218511"; runtimetech.pk; contact@psxterminal.com, contact@runtimetech.pk | psxterminal.com/terms, /about, /services |
| Developer ↔ operator link | **Not verified.** The repository points to the live site, but the repository's author and the operating company are not linked by any public statement found. | — |
| Docs ↔ current service | **Do not correspond.** The documented REST API is now closed (§3). | psxterminal.com/robots.txt |

## 3. API architecture (documented July 2025) and current status
* **Documented:** base URL `https://psxterminal.com`, WebSocket `wss://psxterminal.com/`. REST
  timestamps are Unix seconds and WebSocket timestamps Unix milliseconds. No authentication is
  documented for these endpoints ("Token-based authentication for premium API access" is
  mentioned in ARCHITECTURE.md). The backend is described as Node.js, PostgreSQL and Redis, fed
  by an ingestion service using unnamed "multiple market data sources".
* **Current (robots.txt, 2026-11-07):**
  ```
  # The closed public API: other sites still call it, and crawlers rendering
  # those sites should not fetch it. Our own pages use /api/news, /api/klines
  # and /api/init, which stay allowed.
  Disallow: /api/ticks  /api/stats  /api/companies  /api/fundamentals  /api/financials
            /api/dividends  /api/announcements  /api/towatch  /api/mutual-funds  /api/market-data
  ```
  The public API is described as **closed**. The remaining `/api/news`, `/api/klines` and
  `/api/init` serve the site's own pages. They are internal and undocumented, and must not be
  used as a workaround.

## 4. Endpoint inventory (as documented; NOT tested; now closed)
| Endpoint | Method / params | Documented response fields | Notes |
|---|---|---|---|
| `/api/status` | GET | status, timestamp, uptime | — |
| `/api/market-data` | GET `market` = REG / FUT / IDX / ODL / BNB | per symbol: market, st (PRE/OPN/SUS/CLS), price, change, changePercent, volume, trades, value, high, low, bid, ask, bidVol, askVol, timestamp (s) | sample shows bid/ask 0 |
| `/api/stats` | GET `type` = REG / IDX / BNB / ODL / FUT / breadth / sectors | totals, gainers/losers, top lists, breadth ratios, sector aggregates | — |
| `/api/symbols` | GET | `[{symbol, market}]` | — |
| `/api/yields/{symbol}` | GET | symbol, sector (code e.g. "0821"), listedIn (index codes), marketCap ("41.0B" string), price, changePercent, yearChange, peRatio, dividendYield, freeFloat ("308.3M" string), volume30Avg, isNonCompliant, timestamp (ISO) | strings for numbers |
| `/api/company/{symbol}` | GET | symbol, **`scrapedAt`**, financialStats {marketCap, shares, freeFloat, freeFloatPercent: {raw, numeric}}, businessDescription, keyPeople[], error | `scrapedAt` indicates collection by scraping (§6) |
| WebSocket `subscribe` marketData | `{marketType, symbol}` | `tickUpdate` {s, m, st, c, ch, pch, v, tr, val, h, l, bp, ap, bv, av, t (ms)} | — |
| WebSocket `klines` | `{symbol, timeframe: 1m/5m/15m/1h/4h/1d}` | open, high, low, close, volume, quoteVolume, trades, timestamp | history depth not stated |
| WebSocket stats / symbolList / getSymbols / symbolDetails | — | — | — |
| Limits | — | 5 WebSocket connections per IP; 20 subscriptions per connection; "Message rate: No specific limit enforced"; ping every 30 s | — |
| Errors | — | HTTP 200/400/404/500; WS `{type:"error", message}` | — |

**Not offered in the documented API:** announcements, announcement PDFs, financial statements,
dividends or corporate actions, adjusted prices, or a historical archive. "Historical Data" is an
unchecked roadmap item in the README. The live site's menus show Financials, Dividends, Notices
("PSX corporate disclosures") and News pages, but those are website features, not a documented
or licensed API.

## 5. Data coverage and limitations
| Category | Documented API | Website (not API) | Verified? |
|---|---|---|---|
| Live market watch, quotes, volume/value, bid/ask | Yes (closed) | Yes | No (not tested) |
| Market summary, sectors, indices, FUT / ODL / BNB segments | Yes (closed) | Yes | No |
| Daily OHLCV / intraday candles | WebSocket klines | Charts | No; history depth unknown |
| Adjusted / unadjusted prices, dividend and split adjustments | Not documented | — | No |
| Missing sessions, symbol changes | Not documented | — | No |
| Company profile, shares, free float | Yes (closed) | Yes | No |
| Financial statements, EPS, BVPS, ratios | Not documented (P/E only) | "Financials" pages | No |
| Dividends, bonus, rights, splits | Not documented | "Dividends" page | No |
| Announcements, PDFs, revision timestamps | Not documented | "Notices" page | No |
| Streaming | WebSocket (no auth documented) | — | No |

## 6. Upstream data source: **UNKNOWN**
* **Platform statement:** "Built from publicly available market data and company filings,
  processed and structured for analysis" (/about). No vendor, feed or licence is named.
* **PSX authorised data clients** (PSX Data Services & Vending page, 2026-11-07): Al-Meezan,
  Capital Stake*, Finqalab, Insightswhiz, Mettis Global*, Recube Technologies (Investify),
  Sarmaaya*, Sohail Farooq & Co., Zakheera, Movent, ORCA. **Runtime Technologies / PSX Terminal is
  not listed.**
* **Indicators of the method** (evidence, not proof):
  * the documented company endpoint returns a `scrapedAt` timestamp;
  * its raw fields (market cap "37,412,515.64", shares, free float) match the PSX Data Portal
    company-page format;
  * the yields fields (`sector` code, `listedIn` index codes, `isNonCompliant`) match PSX Data
    Portal fields.
* **Conclusion:** licensed directly from PSX, licensed through a redistributor, or independently
  collected? **Cannot be established. UNKNOWN.** Using this data would not resolve the PSX
  licensing question and might simply move it one step away.

## 7. Legal and licensing assessment
**Terms of Service** (psxterminal.com/terms, "Last updated: July 2026"), quoted:
* "owned and operated by RUNTIME TECHNOLOGIES (SMC-PRIVATE) LIMITED, a company registered in
  Islamabad, Pakistan."
* "You agree not to misuse the Service, including by attempting to disrupt it, **scrape or resell
  its data at scale without permission, access it through automated means beyond normal use**, or
  use it for any unlawful purpose."
* "Data displayed on PSX Terminal is provided for informational purposes only and may be delayed
  or subject to errors. We make no guarantee of the accuracy, completeness or timeliness."
* "Most PSX Terminal features are free. Certain features are offered as paid plans … Our order
  process and payments are conducted by our online reseller Paddle.com".

Privacy Policy and refund policy pages exist but were not material to this assessment. There are
**no API terms**, because the API is closed.

| Intended use | Position |
|---|---|
| 1. Automated API collection | **Not available**: API closed; automated access "beyond normal use" prohibited |
| 2. Scheduled GitHub Actions collection | Not permitted (as 1) |
| 3. Storage in private Turso | Not addressed: **written permission required** |
| 4. Long-term retention | Not addressed: written permission required |
| 5. Private Streamlit display | Not addressed: written permission required |
| 6. Internal investment research | Website: "informational and educational purposes" |
| 7. LLM processing | Not addressed: written permission required |
| 8. Backtesting | Not addressed: written permission required |
| 9. Company impact analysis | Not addressed: written permission required |
| 10. Private individual, no redistribution | Personal website use is fine. Automated or database use still needs written permission, and PSX's licence position is unknown upstream |

**Contact for permission and pricing:** contact@psxterminal.com (platform) and
contact@runtimetech.pk (custom data and software services). No contact has been made.

## 8. Cost and free-tier assessment
* **Website:** core features free, optional paid plans via Paddle. Prices are shown only on
  purchase pages, which were not reviewed. **No API plan, developer key or trial is offered** (the
  API is closed).
* **Custom work:** Runtime Technologies offers custom "market data systems" (/services). The price
  is unknown and would need a quote.
* A free account or personal plan does **not** imply database-retention or automation rights.

## 9. Data-quality validation plan (for any future authorised trial)
1. **Prices:** compare daily close, high, low and volume for OGDC, UBL, NETSOL, BOP and HUBC
   against an independently authorised source (e.g. Capital Stake unadjusted EOD) over a fixed
   window. Log every difference.
2. **Calendar:** build the PSX trading calendar and report missing and duplicate trading dates.
3. **Adjustments:** reconcile adjusted against unadjusted series with dividends, bonus and rights
   issues and splits from the original filings.
4. **Financial statements:** compare against company-published reports, standalone and
   consolidated separately, with units and fiscal periods checked and restatements recorded.
5. **Corporate actions and announcements:** compare against the original filings. Detect revised
   and withdrawn items.
6. **Symbols:** check symbol changes and delistings against `company_status_history`.
7. **Missing values:** keep them as `NULL`, never zero. Track a null count per field.
8. **Timestamps:** keep the provider timestamp, the source publication timestamp and our
   retrieval timestamp separately, with timezone (PKT) handling explicit.
9. **Operations:** measure latency (provider time to our receipt) and record failures in
   `collector_runs` and `source_health`.
10. **Discrepancy log:** one record per discrepancy, with provider, item, field, provider value,
    reference value, reference source, detected time, status (open / explained / provider-corrected
    / unresolved) and resolution note. Values are never overwritten silently.

## 10. Comparison with existing providers
| Requirement | PSX Terminal | Capital Stake (PR #8) | Mettis (PR #7) | Company IR |
|---|---|---|---|---|
| Live market data | Website only (API closed) | Documented REST and WebSocket | Advertised (MG Link) | — |
| Historical OHLCV | Not documented | Documented EOD adjusted and unadjusted | Advertised | — |
| Intraday | Website charts | Documented 1-, 5- and 15-minute bars | Not verified | — |
| Financial statements | Not documented | Documented (consolidated flag, periods) | Not verified | Original reports |
| Dividends / corporate actions | Not documented | Documented | Not verified | Original notices |
| Corporate announcements | Website "Notices" only | Documented REST | Not verified | Own notices |
| Announcement PDFs | Unknown | File names only | Unknown | Yes (own) |
| Live PUCARS alerts | No | Documented webhook | Not verified | No |
| API documentation | Outdated (API closed) | Public, versioned | Not public | — |
| Written reuse rights | Not available | Needs agreement | Needs agreement | Per company |
| Pricing | Not published for data | Not published | Not published | Free |
| PSX-authorised | **Not listed** | Yes (redistributor) | Yes (redistributor) | n/a |

Investify (PR #6): automated collection prohibited. SCS Trade: terms absent. Direct PSX licence:
on request.

## 11. Integration architecture (applies to any approved provider)
No change to the existing plan:
* one **provider adapter** per source behind the Phase 2 engine;
* source provenance, raw provider identifiers and timestamps, permitted raw responses;
* normalised tables, duplicate and revision detection, provider health in `source_health`;
* data-quality validation (§9) before activation;
* failover to a second authorised provider;
* status labels **LIVE / DELAYED / HISTORICAL / UNAVAILABLE / UNVERIFIED** on every value shown.

No provider becomes a hard dependency. PSX Terminal would only be considered if Runtime
Technologies documents an upstream PSX licence and grants written rights.

## 12. Unresolved questions (owner to ask; nothing sent)
1. Runtime Technologies: what is your upstream source for prices, financials and notices, and
   under which PSX licence or redistributor agreement?
2. Is any API or data feed available to third parties now that the public API is closed? Price?
3. Would you grant written rights for private storage, retention, private display and LLM
   processing, with no redistribution? Does your upstream licence allow that?
4. What is the relationship between `mumtazkahn`, `kaleemlab` and Runtime Technologies?

## 13. Evidence and source links
* https://github.com/kaleemlab/psx-terminal (HEAD `8db5c56`): `API.md`, `ARCHITECTURE.md`,
  `LICENSE`, `README.md`, `CHANGELOG.md`, `SECURITY.md`
* `git ls-remote https://github.com/mumtazkahn/psx-terminal`: refused (not public)
* https://psxterminal.com/robots.txt (closed public API notice and Disallow list)
* https://psxterminal.com/terms ("Last updated: July 2026")
* https://psxterminal.com/about (operator, SECP CUIN, NTN, data-sources statement)
* https://psxterminal.com/services (custom software, contact@runtimetech.pk)
* https://www.psx.com.pk/psx/product-and-services/data-services-vending (authorised clients list)

## 14. Recommendation
**DO NOT USE.** The documented API is closed. The Terms prohibit automated access beyond normal
use. The upstream data licence is unknown, and the operator is not a PSX-authorised data client.
Using PSX Terminal would not provide an authorised source of PSX data. If Runtime Technologies
later offers a licensed feed with documented upstream rights, this assessment can be reopened.
