# Master data-source register

Status: DESIGN (2026-11-08). The evidence comes from the repository's earlier reviews:
`SOURCE_ACCESS_REGISTER.md`, `DATA_AVAILABILITY_ASSESSMENT.md`, `MACROECONOMIC_DATA_SOURCE_REVIEW.md`,
`PSX_DATA_PROVIDER_REVIEW.md` and `SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`, and from the live collection on
2026-11-08.

**Verification marks:**

| Mark | Meaning |
|---|---|
| **V** | Verified: observed working, with terms reviewed or owner-authorised |
| **P** | Partially verified: reachable, but terms or coverage not confirmed |
| **B** | Blocked or restricted: refused, or terms prohibit automation |
| **R** | Research task: not yet checked; nothing assumed |

Nothing marked P, B or R may be collected automatically until its row is upgraded to V by an owner decision.

## 1. Register

| # | Source | Data | Status | Access / format | Update | History | Reliability | Restrictions | Cost | Automation | Gaps | Fallback | Mark |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **SCS Trade chart feed** | PSX OHLCV 1m/1h/4h/1d | Secondary (broker) | UDF JSON over HTTPS; honest requests | Intraday | 1m ≈ 5 days, 1h ≈ 90 d, 4h ≈ 1 y, 1d ≈ 5 y (observed) | Good; outages handled | Owner-authorised 2026-11-08; no published API terms | Free | **Yes** (active) | Corporate-action adjustment; index symbols unknown (R5) | Licensed redistributor (#13) | **V** |
| 2 | **RSS news** (Dawn ×3, Business Recorder ×3, Tribune ×3) | Headlines, links, timestamps | Secondary (media) | RSS | Minutes–hours | Feed window only | Good | Metadata only; no article text | Free | **Yes** (active) | No body text | More approved feeds | **V** |
| 3 | **PBS RSS** | Release notices (CPI, trade, LSM) | Official | RSS; releases as PDF/Excel | Monthly | Feed window; archives on site | High | Terms page not found | Free | Feed: yes (active). Release files: R2 | Values are inside files | Manual import of release files | **V** (feed) / **R** (files) |
| 4 | **Company IR websites** | Annual, quarterly and half-yearly reports (PDF); notices | Primary (issuer) | HTTPS PDF downloads | Quarterly | Typically several years on site (per company; R1) | Highest (audited) | Per-company robots and terms (R1); scanned PDFs for some | Free | Per company, after review (`collect_document`) | Format variety, OCR | Owner manual import | **R** (R1) |
| 5 | **PSX websites** (psx.com.pk, dps.psx.com.pk) | Listings, announcements, financial results, calendar | Primary (exchange) | HTML | Daily | Years | Highest | **Terms prohibit "spiders, robots… tools" (verified)** | Free to view | **No** | — | Licensed vending (#13) or manual reading (calendar done manually) | **B** |
| 6 | **SBP** | Policy rate, MPS, reserves, FX, BoP, monetary statistics, EasyData | Official | HTML / PDF / Excel; EasyData portal | Weekly–monthly | Long | Highest | **HTTP 403 to automated requests (2026-11-07)**; written permission for EasyData (R3) | Free | **No** (until permission) | — | Owner manual import of releases | **B** |
| 7 | **SECP** | Company registry, regulatory actions, insurance/NBFC data | Official | HTML / PDF | Irregular | — | High | **HTTP 403** | Free | No | — | Manual | **B** |
| 8 | **Ministry of Finance / Economic Survey** | Fiscal operations, debt, Economic Survey, budget documents | Official | PDF | Monthly / annual | Years | High | No terms link found | Free | R4 | Values are in PDFs | Manual import | **P** |
| 9 | **NEPRA / OGRA** | Tariff determinations, fuel prices, notifications | Official regulator | PDF / HTML | Monthly | Years | High | NEPRA "All Rights Reserved"; OGRA terms not found | Free | Metadata + link only, after review | Values are in PDFs | Manual | **P** |
| 10 | **EIA Open Data API** | Brent/WTI spot, Henry Hub, international energy | Official (US) | REST JSON; free key | Daily / weekly | Decades | High | Registration and ToS; 5,000 rows per call | Free | **Yes, after key + ToS** (U2) | No Pakistan-specific prices | World Bank Pink Sheet (#11) | **P** |
| 11 | **World Bank** (Indicators API, Pink Sheet) | Macro indicators; monthly commodity prices (coal, urea, LNG…) | Official (multilateral) | API (no key) / Excel | Monthly / annual | Decades | High | "Informational and non-commercial purposes" (verified wording) | Free | Yes, if terms accepted for private research (U2) | Lags; monthly | — | **P** |
| 12 | **IMF** (programme documents, data services) | Reviews, staff reports, IFS / WEO | Official | PDF / API | Per review | Years | High | Terms page returned HTTP 403 | Free | R6 | — | Manual reading of programme documents | **R** |
| 13 | **Licensed redistributors**: Capital Stake (csapis), Mettis (MG Link), PSX Data Services & Vending | Listings, announcements, financials, OHLCV, indices | Licensed | API (advertised; not re-verified) | Real-time / daily | Provider-dependent | Provider-dependent | Licence terms | **Quote required** (none published) | Yes, under licence | — | — | **R** (U1) |
| 14 | **Owner manual import** | Any document or dataset the owner obtains lawfully | Per document | CSV / PDF via `MANUAL_IMPORT_DESIGN.md` | Ad hoc | As supplied | Per source | Owner attests rights | — | Import is automated; acquisition is manual | Labour | — | **V** (mechanism exists) |
| 15 | **X (owner-supplied watchlist, 33 accounts + 2 pending)** | Posts: claims, opinions, predictions | Secondary (social) | Official X API only; registry `x_platform` is `licence_required` | Continuous | Plan-dependent | Low until corroborated | No scraping, login bypass or browser imitation; API terms, quotas and pricing to verify (R7) | API plan cost unverified; **no paid plan authorised** | **No.** Owner-attested manual import (`engines/x_watchlist.py`) | Automated monitoring | Manual import | **B** (automation) / **V** (manual import) |

**Research tasks (each a short, read-only check producing a register update):**

| Id | Task |
|---|---|
| R1 | Per-company IR review: URL, robots, terms, report formats and history depth (51 companies first; template in `SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`) |
| R2 | PBS release-file reuse terms |
| R3 | SBP EasyData written permission |
| R4 | Finance Division reuse terms |
| R5 | Whether SCS serves index symbols (KSE-100) and corporate-action-adjusted series |
| R6 | IMF data-service terms |
| R7 | X API: current plans, read quotas, terms for storing post metadata and excerpts, cost (decision needed before any automated access) |

## 2. Recommended minimal source set
1. **Already active:** SCS (#1), RSS (#2) and the PBS feed (#3).
2. **Add by milestone M1–M2:** company IR PDFs (#4) for the priority and covered universe after R1, plus owner
   manual import (#14) for anything unreachable. This is the only free, primary route to financial statements.
3. **Add by M6:** EIA (#10) for oil and gas benchmarks, World Bank Pink Sheet (#11) for other commodities, and
   manual import of SBP / MoF / PBS release values (#6, #8, #3).
4. **Decide at M1 (U1):** whether a licensed redistributor (#13) replaces manual work for listings,
   announcements and financials at scale. If not, coverage grows only as fast as IR reviews and manual
   imports.

## 3. Provenance rules (all sources)
* Every stored value links to a `source_items` row: URL, retrieval method, content hash and timestamps.
  Manual imports record the importer and the owner's rights attestation (`dataset_loads`).
* Official values keep their release date and **vintage**. A revised official figure is a new observation
  with the same reference period and a later vintage, never an overwrite.
