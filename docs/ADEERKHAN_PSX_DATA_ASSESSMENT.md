# adeerkhan/PSX-data (`psx-data-api`): assessment

* **Date of review:** 2026-11-07
* **Repository:** https://github.com/adeerkhan/PSX-data, inspected at commit
  `5ffe8391904b4ddf3f3ceed3fa9dff88049910aa` (2026-11-06). npm package `psx-data-api` 0.4.0,
  MIT licence.
* **Method:** static source-code review of a read-only clone. **Nothing was executed:** no
  live PSX request, no package install, no data download. The repository's recorded fixtures
  were read only to understand the response structures. They were not used as data and nothing
  was stored. Issues and releases could not be read through this session's GitHub tools (the
  repository is not attached); git history and tags were reviewed instead.
* No source activated, production Turso untouched, PRs #5, #7 and #8 not merged, Phase 3 not
  started.

## 1. Recommendation: **DO NOT USE**

The library is well engineered, but it works by meeting PSX's access controls artificially:
* it extracts a rotating gate key from PSX pages;
* it sends a spoofed browser identity and an `X-Requested-With` header;
* it omits the `Origin` header;
* it refreshes the key when PSX refuses a request, and suggests "a different egress" when PSX
  still blocks it.

That is the kind of access-control workaround this project excludes. It is also automated
retrieval from PSX's Data Portal, which PSX's Terms of Use prohibit without prior written
permission. **The repository's own fixtures README quotes that prohibition.** The MIT licence
covers the code, not the PSX data. "USE WITH PERMISSION" would only apply if PSX itself granted
written permission for this access method, which is unlikely given that the method exists to
defeat PSX's gate. A licensed provider (Capital Stake, PR #8) is the proper route for the same
data.

## 2. Technical architecture
* TypeScript monorepo:
  * `packages/client`: the library, about 3,000 lines of source plus tests;
  * `packages/fixtures`: recorded PSX responses;
  * `scripts/`: `record-fixtures.mjs`, `verify-live.mjs`, `live-cache-check.mjs`.
* **Dependencies:** none at runtime. The client uses the global `fetch`. Dev tools are
  TypeScript, Vitest and @types/node. Node ≥ 20.19.
* **Modules:** `transport.ts` (HTTP and the gate), `client.ts` (public API), `parsers*.ts` (HTML
  and JSON parsing), `cache.ts`, `rate-limit.ts`, `errors.ts`, `types.ts`, `selectors.ts`.
* **History:** 19 commits between 2026-09-30 and 2026-11-06, a single author, tag `v0.2.0`, and
  CI and npm-release workflows.

## 3. Endpoints and access method (from source)
Hosts (`selectors.ts`): `dps.psx.com.pk` (gated) and `www.psx.com.pk` (ungated).

| Client method | PSX URL contacted | Kind |
|---|---|---|
| `marketWatch()` | `https://dps.psx.com.pk/market-watch` (HTML); falls back to `www.psx.com.pk/market-summary/` | gated, then ungated |
| `marketSummary()` | `https://www.psx.com.pk/market-summary/` (≈815 KB HTML) | ungated |
| `history(symbol)` | `https://dps.psx.com.pk/timeseries/eod/{SYMBOL}` (JSON) | gated, **undocumented** |
| `intraday(symbol)` | `https://dps.psx.com.pk/timeseries/int/{SYMBOL}` (JSON) | gated, **undocumented** |
| `symbols()` | `https://dps.psx.com.pk/symbols` (JSON) | gated, **undocumented** |
| `constituents(code)` | `https://dps.psx.com.pk/indices/{code}` | gated |
| `indices()` | `https://dps.psx.com.pk/indices` | gated |
| `sectorSummary()` | `https://dps.psx.com.pk/sector-summary/sectorwise` | gated |
| `company(symbol)` | `https://dps.psx.com.pk/company/{SYMBOL}` (HTML) | gated |
| `diagnostics()` | gate and egress checks | — |

**Access controls and how the code gets past them** (quoted from `transport.ts`):
1. **The gate key:** "PSX gates `dps.psx.com.pk` behind three requirements … `X-Req-Id` -- a value
   inlined in every page as `window.__ps._k`. This rotates". The code fetches the PSX root page,
   extracts the key with the pattern `window\.__ps\s*=\s*(\{[^}]+\})`, keeps it for 10 minutes
   (`KEY_TTL_MS`), and **re-discovers it on HTTP 403**.
2. **The `X-Requested-With: XMLHttpRequest` header:** "omit it and PSX returns 403".
3. **A spoofed browser User-Agent:** "`python-requests`, `curl`, `node-fetch` and Node's default
   `undici` UA all get 404". It sends `BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) …
   Chrome/128.0.0.0 Safari/537.36"`.
4. **The `Origin` header:** "sending an `Origin` other than `https://dps.psx.com.pk` gets 403.
   Omitting `Origin` works … which is what makes this usable from Node at all."
5. **When refused anyway,** its error text says: "PSX data endpoints have been measured to
   refuse datacenter egress … **try a different egress**, or read the ungated source."

**Assessment:** these are undocumented, access-controlled endpoints. The library defeats the
controls by impersonating PSX's own browser front end (key extraction plus header and identity
spoofing). That is circumvention of an access restriction, on top of being the "robots …
agents … systematic retrieval" that PSX's terms prohibit. robots.txt on `dps.psx.com.pk` is
absent, but that does not override the Terms of Use.

**Rate limiting and caching** (`rate-limit.ts`, `cache.ts`): a 15-second minimum interval per
key (symbol), described as "matching PSX's documented polling floor" (the source of that
"documented" floor is not cited). Requests are queued per key, and different symbols run in
parallel. Cache lifetimes follow the trading session (15 s during market hours, per the README).

**Error handling and validation:** typed errors (`PsxAuthError`, `PsxEdgeError`,
`PsxNotFoundError`, `PsxRateLimitError`, `PsxTimeoutError` and others). Parsers return `null`
for absent values rather than zero, which is good practice. Duplicate-key handling is noted in
the parsers.

## 4. Data coverage (from types, parsers and fixtures)
| Data | Supported? | Fields / notes |
|---|---|---|
| Live market watch | Yes | quotes for listed securities (the fallback page covers 589 symbols per the code comments) |
| Historical prices (EOD) | Yes | `Bar {time, open, high, low, close, volume}`, **`high` and `low` always `null`** (§5); depth "five years" per the README; not verified |
| OHLCV | **Partial** | EOD has open, close and volume only; intraday has price and volume only |
| Intraday | Yes | `[unix_ts, price, volume]` ticks (fixture); "last two sessions" per the README; not verified |
| Company directory | Yes | `/symbols` JSON (symbol, name, sector per the types) |
| Company profiles | Yes | name, sector, description, address, website, registrar, auditor, fiscal year end, share and fundamentals stat pairs (all nullable) |
| Indices | Yes | `/indices` and constituents (KSE-100 fixture) |
| Sector summaries | Yes | `/sector-summary/sectorwise` |
| Financial fundamentals | Profile stat pairs only | not standardised statements |
| Corporate announcements | **No** | no method, parser or type |
| Announcement PDFs | **No** | — |

## 5. Data limitations
* **High and low prices are missing from historical bars.** This is a limitation of the PSX
  endpoint it uses, not a parsing bug. The EOD JSON rows are `[ts, close, volume, open]` (four
  values; fixture `timeseries-eod-hbl.json`), and the parser hard-codes `high: null, low: null`.
  The README states "PSX publishes **no high/low** on this endpoint". High and low may appear in
  the market-watch snapshot (live), but **not in history**. They must never be filled in or
  estimated.
* The EOD `time` field is a Unix timestamp. Session-date mapping and corporate-action adjustment
  are **not** handled: prices are as published and unadjusted.
* Intraday data has no open, high or low; ticks carry price and volume only.
* No fiscal periods, consolidated/standalone flags or statement line items, so it is not a
  substitute for financial statements.
* Fragility: it depends on PSX page markup and a rotating key. The fixtures README says three
  earlier Python reference implementations "silently rotted".

## 6. Security assessment
* **Supply chain:** zero runtime dependencies, readable source and tests. Low risk *as code*.
* **Operational and legal risk: high.**
  * Running it makes our system impersonate a browser to get past PSX's gate. That could get the
    egress IP blocked: PSX "reserves the right to block an IP address", as cited in its own
    rate-limit notes.
  * It would breach the project's rule against circumventing access controls.
* **Data hygiene:** the repository commits recorded PSX responses (fixtures) to a public
  repository. We must not copy them into our project.

## 7. Licensing and access concerns
* MIT licence: the **software** may be reused. It grants no rights over PSX data.
* PSX Terms of Use: automated or systematic retrieval prohibited without prior written
  permission. PSX's legal notice: commercial use of PSX market data requires a licence.
* Our private, internal use (database, dashboard, LLM processing) is still use of PSX data and
  needs a licence or permission.
* Because the method is a workaround of PSX's gate, written permission from PSX would normally
  come with an official channel (a licence or feed) instead, not with permission to use this
  workaround.

## 8. Comparison with our project and providers
| Need | adeerkhan/PSX-data | Capital Stake (PR #8) | Mettis MG Link | Company IR sites | Phase 2 registry |
|---|---|---|---|---|---|
| EOD history with high and low | **No high/low** | Documented EOD adjusted and unadjusted (fields include high and low) | Advertised | — | `psx`/`psx_dps` RESTRICTED |
| Intraday | Ticks (price, volume) | 1-, 5- and 15-minute OHLCV | Advertised | — | — |
| Company directory / profiles | Yes | Yes | Yes | Per company | Phase 1 master (PSX-sourced, licence question open) |
| Statements / ratios | No | Documented | Advertised | Reports (authoritative) | — |
| Announcements / live | **No** | REST + PUCARS webhook | Not documented | Notices | — |
| Licensing | **Circumvents PSX gate; not permitted** | Agreement required | Agreement required | Per-company terms | Enforced by ACTIVE gate |

There is no **useful supplementary dataset** that a licensed provider would not cover better.
Its only unique value is free access, and that comes from circumventing PSX's controls.

## 9. Potential integration design (not recommended; recorded for completeness)
If PSX ever grants written permission for automated Data Portal access, the existing Phase 2
engine would be used (a Python adapter, not this Node package):
* a `sources` row with `terms_status=approved` and `retention=metadata_only` or as licensed;
* our own descriptive User-Agent, obeying any PSX-specified rate limit;
* `null` kept for absent fields;
* raw EOD stored unadjusted, with adjustments derived separately from corporate actions.

This library would **not** be used even then, because its transport is built around
impersonation.

## 10. Data-quality validation plan (for any future PSX-licensed or provider data)
1. **Closing prices:** compare against an independently authorised source (for example Capital
   Stake unadjusted EOD) for sample symbols (OGDC, UBL, NETSOL, BOP) over 5 years. Report every
   mismatch, never correcting it silently.
2. **Completeness:** build the PSX trading calendar (provider market-holidays endpoint) and list
   missing dates and duplicate dates per symbol.
3. **OHLCV completeness:** count `null` per field. Never substitute or estimate missing high or
   low values.
4. **Symbol changes:** check against `company_status_history` (e.g. renames, mergers such as
   FFBL into FFC).
5. **Sectors:** compare provider sectors with the PSX classification stored in Phase 1.
6. **Corporate actions:** check that adjusted series reconcile with dividends, bonus and right
   issues and splits. Store raw and adjusted separately.
7. **Null versus zero:** test that zero volume (no trades) is distinguished from missing volume.

## 11. Live test that would be needed (NOT requested and NOT recommended)
No live test is proposed. Any live call through this library involves the gate workaround (§3),
so it cannot be made compliant by limiting its size. The data categories it covers should be
evaluated through a licensed provider's trial instead (PR #8, §6).
