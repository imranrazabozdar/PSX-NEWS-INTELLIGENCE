# pypsx-toolkit and Capital Stake: provider assessment

* **Date of review:** 2026-11-07
* **Scope:** investigation only. Neither source was activated, the production database was not
  touched, no dependency was added, nothing was purchased and no provider was contacted. PR #5
  and PR #7 are not merged and Phase 3 has not started.
* Related: [INVESTIFY_SCS_TRADE_ASSESSMENT.md](INVESTIFY_SCS_TRADE_ASSESSMENT.md) and
  PR #7 (`PSX_ANNOUNCEMENT_ACCESS_INVESTIGATION.md`).

## 1. Conclusion

| | pypsx-toolkit | Capital Stake |
|---|---|---|
| Verdict | **Do not use.** | **Preferred candidate**, subject to a written agreement and pricing. |
| Why | It retrieves data by calling the **PSX Data Portal's internal endpoints directly** (`https://dps.psx.com.pk/...`). That is automated PSX retrieval, which PSX's Terms of Use prohibit without written permission. Its own licence also prohibits "use" without the PyPSX Team's written permission, and pyPSX is not on PSX's list of authorised data clients. | PSX-authorised redistributor (PSX vending page) with public, versioned API documentation (v3.0.0) covering OHLCV, standardised statements, ratios, announcements, payouts and a PUCARS webhook. Rights for our use (storage, retention, LLM processing, private display) still need written confirmation. |

**None of pypsx-toolkit's functions were run**, because running them would itself send
automated requests to PSX. Because neither provider was used, **no data-quality validation was
possible** (§6).

## 2. pypsx-toolkit: evidence

### 2.1 Package identity (from PyPI JSON metadata, `https://pypi.org/pypi/pypsx-toolkit/json`)
| Item | Value |
|---|---|
| Name / latest version | `pypsx-toolkit` 3.1.2 (uploaded 2026-09-25) |
| Releases | 6: 3.0.1 (2026-07-28), 3.0.2 (07-29), 3.0.4 (07-31), 3.1.0 (08-06), 3.1.1 (09-05), 3.1.2 (09-25) |
| Maintainer | "PyPSX Team" `pypsxofficial@gmail.com` (a free webmail address; no company name) |
| Project URLs | https://pypsx.com, https://markets.pypsx.com/docs, changelog |
| Licence | **Proprietary:** "Unauthorized copying, modification, distribution, sublicensing, **or use** of this Software, via any medium, is strictly prohibited without the prior written permission of PyPSX Team. No license … is granted." Classifier `License :: Other/Proprietary License`. |
| Distribution | Compiled wheels per Python version (≈1.8–13 MB each, Linux and Windows) plus a 24.7 KB sdist containing only stubs and constants. The implementation ships as compiled binaries, not readable Python. |
| sdist SHA-256 (3.1.2) | `1236a8af4ec1a6f9fec9bdfb7e79d0845e9df767ff9ef124f7332e8702542f0c` |
| Dependencies | `requests`, **`curl_cffi`** (a client that impersonates browser TLS fingerprints, commonly used to get past anti-bot protection), `beautifulsoup4`, `lxml` (HTML parsing), `pandas`, `numpy`, `loguru`, `tqdm` |

### 2.2 Where it gets its data (static inspection of the sdist; nothing executed)
`pypsx_toolkit/endpoints/constants.py` defines:
```
PSX_BASE_URL = "https://dps.psx.com.pk"
MARKET_WATCH_URL     = f"{PSX_BASE_URL}/market-watch"
SECTOR_SUMMARY_URL   = f"{PSX_BASE_URL}/sector-summary/sectorwise"
PERFORMERS_URL       = f"{PSX_BASE_URL}/performers"
TRADING_BOARD_URL    = f"{PSX_BASE_URL}/trading-board/REG/main"
INDICES_OVERVIEW_URL = f"{PSX_BASE_URL}/indices"
HISTORICAL_URL       = f"{PSX_BASE_URL}/historical"
get_index_url(code)            -> /indices/{code}
get_timeseries_intraday_url(s) -> /timeseries/int/{SYMBOL}
get_timeseries_eod_url(s)      -> /timeseries/eod/{SYMBOL}
get_company_url(s)             -> /company/{SYMBOL}
get_company_reports_url(s)     -> (company financial reports)
```
* The README claims "Built on a real API, not brittle HTML parsing" and "No account and no API
  key are required". The only data host in the package is the **PSX Data Portal**. No pyPSX data
  API host appears in the readable files.
* The README says pyPSX "is distinct from the PSX exchange itself".
* **Data source:** PSX's Data Portal, accessed without a PSX licence. It is **not** a licensed
  vendor feed.
* **Not done:** the compiled binaries were not decompiled or run. The licence forbids use and
  modification, and running them would send automated requests to PSX. Whether the binaries also
  contact pyPSX servers is therefore **not verified**.
* **`docs.pypsx.com`:** not reviewed (host not in the environment allow-list). The package's own
  README and type stubs were used instead.

### 2.3 Functions requested (from the package's type stubs; NOT executed)
| Function | Documented signature / return | Status |
|---|---|---|
| `download(symbols, period="1y", interval="1d", …)` | periods "1d"…"10y","ytd","max"; single symbol → DataFrame `[Open, High, Low, Close, Volume, Change%]` | Not run |
| `get_historical(symbol, start_date, end_date, max_workers=…)` | DataFrame `[Date, Open, High, Low, Close, Volume, Change%]`; **parallel HTTP workers** | Not run |
| `get_company_fundamentals(symbol)` | keys `pe_ratio, eps, book_value, dividend_yield, roe, roa, debt_to_equity, current_ratio, market_cap, shares_outstanding` (no fiscal period, statement basis or source) | Not run |
| `get_dividend_history(symbol)` | DataFrame `[Date, Type, Rate, Face_Value, Announcement_Date]` | Not run |
| `get_dividend_info(symbol)` | last dividend rate, type, ex-date, payment date | Not run |
| `Ticker(symbol).announcements()` | DataFrame `[Date, Category, Subject, Description]`: **no document link, no time, no announcement ID** | Not run |

**Sample test (OGDC, UBL, NETSOL, BOP) was not performed.** Rate limits, reliability, failure
behaviour and update frequency are therefore **not verified**.

### 2.4 Assessment
* **Legal:** using the library means our system sends automated requests to PSX, which PSX's
  terms prohibit without permission. The library's licence adds a second restriction.
* **Security / supply chain:** closed-source compiled binaries, an anonymous webmail maintainer,
  browser-impersonation tooling, and releases about three months old. The library is not suitable
  for this project's independence and dependency controls (ADR-0001: every dependency must be
  reviewed).
* **Data quality:** fundamentals have no fiscal period, consolidated/standalone flag or units, and
  announcements have no document or timestamp. Even if it were permitted, it would not meet the
  spec's provenance requirements (§11.1).

## 3. Capital Stake: evidence (public documentation, https://www.capitalstake.com/docs/)

### 3.1 General
| Item | Documented |
|---|---|
| Version | Capital Stake API v3.0.0 ("Last Updated: July 2026") |
| Base URLs | Production `https://csapis.com`; UAT `https://uat.csapis.com` |
| Authentication | `Authorization: Bearer YOUR_API_TOKEN` on all endpoints |
| Response envelope | `{"status": "ok"\|"error", "message": "", "data": …, "count"?: n}`; paginated: `offset`, `count`, `total` |
| Errors | 200 with `status:error` (e.g. "no `symbol` provided", "unable to fulfill request"); 403 `unauthorized_request` / `invalid_method`; 404 `not_found`; 500 |
| Rate limits / quotas | "Please contact support for information about rate limits and usage quotas." **Not published.** |
| Delivery | REST, WebSocket, Webhooks |
| Status | PSX-authorised redistributor (PSX Data Services & Vending page, 2026-11-07) |

### 3.2 Endpoints relevant to us (exact paths as documented)
| Category | Endpoint | Parameters | Notes |
|---|---|---|---|
| EOD OHLCV, adjusted | `GET /3.0/market/eod-adj` | `symbol` (req), `date_from`, `date_to` | dividend- and split-adjusted |
| EOD OHLCV, unadjusted | documented page "end-of-day-stocks-unadjusted" | — | path not captured in this review |
| Intraday | pages for 1-, 5- and 15-minute charts | — | paths not captured |
| Quarterly income statement | `GET /3.0/company/financials/income/quarterly` | `symbol` | |
| Annual income / balance / cash flow; quarterly balance / cash flow | documented pages | `symbol` | same structure as quarterly income |
| Financial ratios (annual, incl. TTM) | `GET /3.0/company/financials/fundamentals/annual` | `symbol` | each ratio carries a description, a LaTeX formula and a unit |
| Key metrics (annual / quarterly), company profile, shareholder pattern | documented pages | `symbol` | |
| Announcements by date range | `GET /3.0/announcements/date-range` | `date_from`, `date_to` (req), `offset` | paginated; sample shows `total: 9733` |
| Announcements by symbol | `GET /3.0/announcements/symbol` | `symbol`, `offset` | |
| Announcements by type / by sector / all / board meetings / AGM-EOGM | documented pages | — | |
| Dividends | `GET /3.0/payouts/dividends` | `symbol` | "**over the latest 5 years**" |
| Bonus / rights / splits / payouts by symbol / by date range | documented pages | — | |
| PUCARS webhook | channel `pucars` (POST to our HTTPS endpoint) | set up by Capital Stake | see §3.4 |

### 3.3 Sample response structures (copied from the documentation; illustrative values)
**EOD adjusted:**
```json
{"status":"ok","message":"","count":15,"data":[
  {"time":1545998400,"open":37822.29,"high":37891.19,"low":36918.66,"close":37167.02,"volume":132828200}]}
```
`time` is Unix seconds (UTC). The sample values look like index levels and the sample times are
not at midnight, so the documentation samples are illustrative, not real records.

**Quarterly income statement:**
```json
{"status":"ok","message":"","data":{
  "symbol":"DGKC","created":"2025-08-28T10:37:32.056Z","interval":"quarterly","consolidated":false,"type":"income",
  "periods":[{"year":"2025","quarter":"Q3","period_end":"2025-03-31","year_end_diff":3},
             {"year":"2025","quarter":"Q2","period_end":"2024-12-31","year_end_diff":3}],
  "fields":[{"label":"Sales","values":[16776337,18125324],"is_heading":false,"key":"sales"},
            {"label":"Cost of sales","values":[-11437686,-13403767],"is_heading":false,"key":"cos"}, …]}}
```
* There is an explicit **`consolidated`** flag, fiscal `year`/`quarter` with `period_end`, and a
  `created` timestamp, which is useful provenance.
* **Units are not stated** in the sample (likely PKR thousands, but this must be confirmed).
* `year_end_diff` is documented as "Month difference from year end". Whether figures are
  discrete-quarter or cumulative (for example 9-month) must be confirmed.

**Financial ratios (annual):**
```json
{"data":{"symbol":"DGKC","created":"2025-06-24T07:06:08.127Z","interval":"annual","consolidated":false,"type":"fundamentals",
  "periods":[{"year":"TTM","period_end":"2025-03-31","period_start":"2024-12-31","year_end_diff":9},
             {"year":"2024","period_end":"2024-06-30","year_end_diff":12}],
  "fields":[{"label":"Gross Profit Margin","values":[0.2012,0.1594],"unit":"%",
             "latex":"$$Gross\\ Profit\\ Margin= \\frac {Gross\\ Profit}{Sales}$$","key":"gpm"}, …]}}
```
The `unit` is "%" while the values are fractions (0.20 = 20%), a unit convention to handle
explicitly. Ratios must be **recalculated** from the statements, not trusted as given.

**Announcements (by symbol):**
```json
{"status":"ok","offset":0,"count":50,"total":9733,"data":[
  {"id":"278228","status":1,"category":"C","sector_code":"0807","form_type":"MISV001","symbol":"BOP",
   "title":"NEWSPAPER ADVERTISEMENTS FOR BOOK CLOSURE OF BOP ADT-1 CAPITAL TFC - 2022 (PERPETUAL) BOPTFC2",
   "quarter":"","date":"2026-06-05T09:32:08Z","last_action":"2026-06-05T09:39:05Z","is_revised":false,
   "pdf":"278228.pdf","docs":["278228.pdf"],"images":["278228-1.gif"],
   "period_ended":null,"meeting":null,"results":null,"payouts":null}]}
```
* Fields: notice ID, `date` (publication, ISO 8601) and `last_action` (separate),
  `is_revised`, document **file names**, and structured `payouts`/`meeting`/`results` blocks.
* The sample shows `total: 9733` for both the symbol and the date-range examples, so the samples
  are illustrative.

**Dividends:**
```json
{"status":"ok","message":"","data":[{"id":"WAFI_20241115","symbol":"WAFI","title":"Dividend Announcement",
  "date":"2024-11-15","ex_date":"2024-11-10","book_closure_from":"2024-11-12","book_closure_to":"2024-11-14",
  "entitlement_date":"2024-11-09","dividend":2.50}]}
```
Only the **last 5 years** are documented for this endpoint. Longer history would come from
announcements by date range, if the archive goes back further.

### 3.4 PUCARS webhook (documented at `/docs/webhooks/intro` and `/docs/webhooks/pucars`)
* "Delivers every corporate announcement filed on the Pakistan Stock Exchange through PUCARS …
  as soon as it is published or revoked. The payload is the PUCARS announcement **exactly as the
  exchange sends it**."
* **Common fields:**
  * `AnnouncementAction` (`PUBLISH` or `REVOKE`)
  * `AnnouncementType` (e.g. `BMV1001`, `INTDISC001`)
  * `AnnouncementId` (`WAS-`/`FAS-` prefix)
  * `SymbolCode` (`EXCHANGE`, `OPENFUND` for non-company notices)
  * `AnnouncementTitle`, `PostingDate`, `PostingTime`, `ActionTimestamp`
  * `Enclosure`, `Attachment` (`|`-separated)
  * `Revised` (`Y`/`N`), `OriginalAnnouncementId`, `companyName`
  * type-specific fields (e.g. board meeting `Held-Date`, `Period-Ended`; insider `RECORDS[]`).
* **Documents:** "The file itself is not delivered". Only file names arrive, and the
  documentation does not give a base URL for retrieving files. **Retrieving the PDFs is
  therefore an open question.** If the files must come from PSX's site, PSX's permission applies.
* **Delivery:** HTTP POST of JSON to our HTTPS endpoint. Headers include the attempt number, a
  timestamp and an optional HMAC signature (`X-CS-Signature: sha256=…`). Our endpoint's
  authentication can be None, Basic, Bearer or a custom header. "Webhooks are set up by the
  Capital Stake team. Request one the same way you request access to the REST and WebSocket
  APIs."
* **Times:** `PostingDate` and `PostingTime` have **no timezone** (presumably PKT, to be
  confirmed). We would store the raw strings and the PKT assumption flag, and never guess
  silently (canonical.to_utc already refuses zoneless times without an explicit zone).

### 3.5 Licensing, pricing and rights
* **Terms of service:** not readable without JavaScript, so **not verified**.
* **Pricing:** not published ("Request a Consultation"). Rate limits and quotas: not published.
* **Rights for our use** (private Turso storage, retention, LLM processing, private Streamlit
  display, historical backfill, document retrieval): **not stated in public documentation**.
  They need written confirmation, including that PSX's licence approval covers our use
  ("PSX license and permission to use market data still applies to the third party(s) or sub
  client(s)", PSX vending page).

## 4. Comparison with our architecture

| Requirement | pypsx-toolkit | Capital Stake |
|---|---|---|
| Historical OHLCV | Claimed (`download`, up to "max"); source is the PSX Data Portal (**not permitted**) | Documented: EOD adjusted and unadjusted, 1-, 5- and 15-minute bars; history depth not stated |
| Financial statements | Not offered (fundamentals snapshot only) | Documented: annual and quarterly income, balance and cash flow, with `consolidated` flag and periods |
| Financial ratios | Snapshot keys, no periods or formulas | Documented: annual + TTM, with formula and unit; recalculate before use |
| Dividend history | Claimed `[Date, Type, Rate, Face_Value, Announcement_Date]` | Documented: dividends (last 5 years), bonus, rights, splits, payouts by date range |
| Corporate announcements | `[Date, Category, Subject, Description]` only | Documented: ID, publication time, last action, revised flag, category, form type, structured payouts / meeting / results |
| Live announcements | None (polling PSX) | **PUCARS webhook** (publish and revoke), signed, retried |
| Announcement PDFs | No | File **names** only; files not delivered (**open question**) |
| Historical backfill | Not permitted (PSX) | Date-range endpoint with pagination; archive depth not stated |
| Turso compatibility | n/a | Good: JSON maps onto `source_items`, versions and revisions; webhook needs an always-on HTTPS endpoint (GitHub Actions cannot receive webhooks) |
| Licensing clarity | **Clear prohibition** (own licence + PSX terms) | **Unclear until agreement:** terms not readable; rights must be confirmed in writing |
| Cost | Free package, but use not licensed | **Not published** (quote required) |

### Recommended source per data category (all subject to written agreements)
| Data category | Recommended | Fallback / verification |
|---|---|---|
| Live announcements | Capital Stake `pucars` webhook | Capital Stake REST date-range polling (for recovery) |
| Historical announcements | Capital Stake REST date range | Mettis Global (quote) |
| Announcement documents (PDF) | To be confirmed with Capital Stake / PSX | Owner manual retrieval (personal copy) |
| EOD prices (history) | Capital Stake EOD unadjusted (store raw) and adjusted (derived) | PSX licence |
| Financial statements | Capital Stake standardised statements | **Verify** against the company's own published reports |
| Ratios | **Compute ourselves** from statements | Use Capital Stake ratios only as a cross-check |
| Dividends / corporate actions | Capital Stake payouts + announcements | Company notices |
| pypsx-toolkit | **Not used** for any category | — |

## 5. Integration design notes (for later, after approval)
* Each provider becomes a `sources` entry (Phase 2 registry) with `terms_status`, licensing and
  retention set from the signed agreement. It stays non-ACTIVE until then.
* Provider IDs (`AnnouncementId` such as `WAS-285844`, or the REST `id`) become `external_id`.
  `PUBLISH` creates an item, `REVOKE` and `Revised=Y` create linked revisions, and
  `OriginalAnnouncementId` links to the original.
* Statements are stored as reported, with `consolidated`, `period_end`, `interval`, unit and the
  provider's `created` timestamp as provenance. Values that are absent stay absent and are never
  stored as zero.
* No new runtime dependency is needed: the Phase 2 HTTP client and JSON adapter can call
  `csapis.com` with a `PSXNI_`-prefixed token supplied through the network-secret proxy.

## 6. Data-quality validation: not performed
No data was obtained from either provider. pypsx-toolkit was not run (§2), and Capital Stake
needs an account and token. None of these were therefore possible:
* comparison against company annual and quarterly reports;
* checks of fiscal periods and units, restatements and missing quarters;
* standalone versus consolidated reconciliation;
* recalculation of ratios.

**Plan once a trial token exists**, for OGDC, UBL, NETSOL and BOP:
1. Fetch the last 8 quarters and 5 years.
2. Compare sales, gross profit, profit after tax and EPS with the companies' own published
   accounts, separately for standalone and consolidated.
3. Record every difference, including restatements.
4. List missing quarters.
5. Recompute ratios from the statements and compare.
6. Check announcement IDs and times against the PSX notice (by manual owner check).

## 7. Open questions for Capital Stake (owner to ask; nothing has been sent)
1. Price and plan for: announcements (REST + `pucars` webhook), EOD history, standardised
   financials, payouts. Is there a trial token for evaluation?
2. Rate limits and quotas; history depth for announcements, EOD prices and financial statements.
3. How to obtain the announcement documents named in `Enclosure`/`Attachment`, and under what
   rights.
4. Units of statement values; whether quarterly values are discrete or cumulative; restatement
   handling (are earlier periods revised in place?).
5. The timezone of `PostingDate`/`PostingTime` (PKT?) and typical webhook delivery latency.
6. Written rights for private database storage, indefinite retention, LLM processing (no
   training), private dashboard display, with no public redistribution. Confirmation that PSX's
   approval covers this.
7. Terms of service (as a document), termination and data-deletion obligations.
