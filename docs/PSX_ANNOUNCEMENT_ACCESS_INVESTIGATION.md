# PSX corporate announcements: access investigation

* **Date of review:** 2026-11-07
* **Scope:** feasibility investigation only. Nothing was enabled or activated, no announcement
  was collected or stored, nothing was purchased and no provider was contacted. PR #5 is not
  merged and Phase 3 has not started.
* **Method:** human-paced requests (about 2 seconds apart, descriptive User-Agent) to public
  pages, robots.txt files, terms pages and publicly documented API documentation. No
  undocumented endpoint was called and no announcement document was downloaded.
* Related: [INVESTIFY_SCS_TRADE_ASSESSMENT.md](INVESTIFY_SCS_TRADE_ASSESSMENT.md) and ADR-0005.

## 1. Summary

| Question | Answer |
|---|---|
| Can PSX's own pages be collected automatically, even one announcement at a time? | **No, not without PSX's prior written permission.** PSX's Terms of Use prohibit robots, spiders and agents and "systematic retrieval to create collections, compilations, databases or directories". Fetching announcements one by one with a program is still automated, systematic retrieval. |
| Is there an official PSX feed or API for individuals? | **None found.** No RSS, no documented API, no public alert sign-up. PSX's Downloads page points data requests to `marketdatarequest@psx.com.pk`, and licences come through PSX Data Services & Vending. |
| Is there an authorised, documented, near-real-time route? | **Yes, but only with a commercial agreement: Capital Stake.** Capital Stake is a PSX-authorised redistributor. Its public API documentation describes a "Corporate Announcements & Payouts" dataset ("a digital mirror of the PUCARS feed"), REST queries by symbol, type, sector and date range, and a `pucars` **webhook** channel that "push[es] data to your server as soon as it is published". Access is set up on request and pricing is not published. Mettis Global (MG Link API) is a second authorised redistributor offering an API. |
| What can we do today without permission? | Only **manual, owner-initiated** handling: the owner reads an announcement and records it. PSX's terms allow a single copy for personal, non-commercial use. Storing it in our database still needs confirmation (see §9). |

**Recommendation:** use **Capital Stake's PUCARS webhook plus its REST API**, subject to a
written agreement that covers private storage, retention, private dashboard display and LLM
processing. Ask Mettis Global for a competing quote, and ask PSX directly for a non-display or
internal-use licence as a third option. Keep the PSX collector disabled. Live collection and
historical backfill are designed as separate workflows (§5, §6), and each needs its own
permission.

## 2. Methods investigated, and the evidence

### A. Official PSX announcements pages
| Item | Finding | Evidence |
|---|---|---|
| Listing pages | `https://dps.psx.com.pk/announcements/{companies,psx,secp,cdc,nccpl}` and `https://www.psx.com.pk/psx/announcement/financial-announcements` exist. The Data Portal tables are filled by JavaScript; no announcement rows are present in the HTML. | Phase 2 review; page fetched 2026-11-07 (no `<table>` rows; script `/static/script.js`) |
| Individual documents | Each announcement has a PDF/image at a stable numeric address, e.g. `www.psx.com.pk/psx/file-attachment/288838.pdf`, shown on the home page. | home page links 2026-11-07 |
| Date / time | Shown on the pages in PKT. Publication time versus the effective date of the action is not distinguished. | page structure |
| Incremental exposure | No feed, no "since" parameter, no documented change notification. | no RSS / API found |
| Official access method | None documented for individuals. The Downloads page offers daily market files and a data-request e-mail (`marketdatarequest@psx.com.pk`). Licences are through Data Services & Vending. | `https://dps.psx.com.pk/downloads`; vending page |
| Anti-automation | reCAPTCHA scripts on the Data Portal and the financial-announcements page; PSX notice "Unauthorised use of PSX Proprietary Material in Social Media Channels". | page scripts; home-page PDF link (not downloaded) |
| robots.txt | `www.psx.com.pk`: allows all except `/cgi-bin/`. `dps.psx.com.pk`: no robots.txt (404). robots.txt does **not** override the Terms of Use. | Phase 2 review |
| Terms | Prohibits "spiders, robots, avatars, agents, tools or other devices … to navigate, search or determine the PSX Website" and "systematic retrieval to create collections, compilations, databases or directories" without prior written permission. Allows "a single … copy … for your personal, non-commercial use". | `https://www.psx.com.pk/psx/terms-of-use` |

### B. Individual announcement retrieval
* **Technically possible:** a single PDF has a stable URL.
* **Legally:** a *program* fetching each new PDF as it appears is still automated, systematic
  retrieval, so it is not permitted without written permission. Doing it more slowly, or one at a
  time, does not change that, and disguising it as browsing is excluded.
* **Permitted today:** the owner opening one announcement in a browser, for personal use.
* **Metadata only** (symbol, title, time, URL) without downloading the PDF still requires reading
  the PSX listing automatically, so the same restriction applies.

### C. Official notification mechanisms
| Channel | Finding |
|---|---|
| PUCARS (`https://www.pucars.com/`) | PSX's Unified Corporate Action Reporting System, linked from the PSX home page; listed companies file announcements through it. The site's **TLS certificate had expired** when tested (`certificate has expired`). The connection was not forced, so the site's content and terms were **not verified**. |
| PSX e-mail / SMS alerts | None found on www.psx.com.pk or the Data Portal for individuals. |
| Public feed / documented API | None found. |
| Data licence | PSX Data Services & Vending: real-time and delayed feeds; commercial use of PSX data "without acquiring respective rights/license from the PSX is strictly prohibited". |

### D. Authorised data providers (PSX vending page, 2026-11-07)
PSX marks Capital Stake, Mettis Global and Sarmaaya Financials as "Authorized to redistribute PSX
market data subject to PSX's prior approval and license to the third party(s) or sub client(s)".
Recube Technologies (Investify) is a licensed client but **not** marked as a redistributor.

| Provider | Announcement offering | Automation position | Access / cost |
|---|---|---|---|
| **Capital Stake** | **Documented.** "Corporate Announcements & Payouts: a digital mirror of the PUCARS feed including dividends, notices, and the regulatory calendar"; endpoints listed: all announcements, by symbol, by type, by sector, by date range, board meetings, AGM/EOGM calendar, dividends, bonus, rights. **Webhooks:** channel `pucars`, "Corporate announcements filed on PSX through PUCARS", pushed as JSON on publication, with optional HMAC signature (`X-CS-Signature`) and retry attempt numbers. Also WebSocket and REST. | robots.txt allows documentation pages ("Allow: /docs/"). Terms page did not render without JavaScript, so it was **not verified**. Access is by agreement ("Webhooks are set up by the Capital Stake team. Request one the same way you request access to the REST and WebSocket APIs, through support at https://csapis.com"). | **Pricing not published.** "Request a Consultation". Contact: contact@capitalstake.com |
| **Mettis Global** | **Advertised:** "MG Link API … integration of financial market data … for internal or redistribution purposes", including "corporate calendars" and "real-time exchange data". Announcement endpoints not publicly documented. | robots.txt: allows all except /admin, /private. Terms not located. | Pricing not published. Contact: support@mettisglobal.com, +92-21-35241304-8 |
| **Sarmaaya Financials** | Website shows announcements (e.g. `/announcements?cat=payouts`). **No API documented.** | **Terms prohibit automation:** "Use bots, automated systems, or scraping techniques to extract data" is prohibited (§4.4(c), §6.3(b), §26.1.10). | Consumer plans: free; Pro PKR 4,000/month; Premium PKR 6,000/month (15-minute delayed data on free); Enterprise "Customise". These are personal plans, **not** a data licence. |
| **Investify (Recube)** | Announcements re-published from PSX (DPS document IDs). | Terms prohibit automated collection to "build, supplement or feed a database". API `/api/v1/` disallowed in robots.txt. | Not published. |
| Others on the PSX list (Al-Meezan, Finqalab, Insightswhiz, Sohail Farooq & Co., Zakheera, Movent, ORCA) | Not reviewed in this investigation. | — | — |

### E. Company-level alternatives
* Listed companies publish financial results and notices on their own investor-relations
  websites. Each company's site has its own terms, and timing is usually **later** than the
  PSX/PUCARS filing. Useful for **verifying** content and for annual/quarterly reports, not for
  first detection.
* Some companies offer e-mail alerts to investors. These are company-specific and need
  per-company sign-up and review of their terms. They are not covered in this investigation.

## 3. Technical feasibility comparison

| Method | Technical feasibility | Documentation | Authentication | Publication delay | Historical coverage | Reliability | Terms / licence | Written permission needed | Cost |
|---|---|---|---|---|---|---|---|---|---|
| PSX website, automated | Possible only via undocumented JS endpoints (excluded) | None | None (reCAPTCHA present) | Real-time on PSX | Archive on site | Fragile (undocumented) | **Prohibited** | **Yes, from PSX** | Unknown |
| PSX single PDF by URL, automated | Easy | None | None | Real-time | Per document | High | **Prohibited** (systematic retrieval) | **Yes, from PSX** | Unknown |
| Owner manual browsing | Easy | — | None | As fast as the owner | — | Manual | Personal single copy allowed | Storage in DB: confirm (§9) | None |
| PUCARS | Not verified (expired certificate) | Not verified | Not verified | — | — | — | Not verified | Assume yes | Unknown |
| PSX data licence | Yes (official) | On request | Licence | Per product | Per product | High | Licensed use | Licence agreement | Not published |
| **Capital Stake webhook + REST** | **Yes (documented)** | **Public docs** | Account / credentials; webhook to our HTTPS endpoint | "as soon as it is published" (actual latency not measured) | Date-range queries documented; depth not stated | High (retries, signatures) | By agreement; terms not verified | **Yes (agreement)** | Not published |
| Mettis Global MG Link API | Yes (advertised) | Not public | By agreement | Not stated | Not stated | Not verified | By agreement | Yes | Not published |
| Sarmaaya | Website only | No API docs | Account | 15-min delay on free plan | Not verified | — | **Automation prohibited** | Yes | Personal plans PKR 4,000–6,000/month; enterprise custom |
| Investify | Website only | No | — | — | — | — | **Automation prohibited** | Yes | Not published |
| Company IR sites | Varies | Varies | None | Usually later than PSX | Varies | Varies | Per company | Per company | None |

## 4. Legal and access assessment
* Public accessibility is **not** permission. All three PSX surfaces (www, Data Portal,
  financial-announcements) fall under PSX's Terms of Use, which require prior written permission
  for automated or systematic retrieval and for compiling databases.
* PSX data obtained through a redistributor stays subject to PSX's licence: "PSX license and
  permission to use market data still applies to the third party(s) or sub client(s)". A
  redistributor agreement must therefore state that PSX's approval covers our use.
* Private internal use (our Turso database, private Streamlit, LLM processing) is still "use"
  under these licences and must be named explicitly in any agreement. Public redistribution is
  **not** needed and should be excluded, which should keep the licence narrower and cheaper.

## 5. Live announcement collection design (to build only after permission)

```
provider webhook (Capital Stake 'pucars')      polling fallback (REST "by date range", every N min)
                \                                 /
                 → verify signature (HMAC) → idempotent intake → announcements staging
                 → metadata capture (symbol, title, category, PSX publication time, provider id, document URL)
                 → authorised document retrieval (only if the agreement permits) → SHA-256 → metadata only in DB
                 → dedupe / revision detection → evidence storage (source_items + versions)
                 → [Phase 3] LLM extraction → company mapping → [Phase 4–5] impact assessment → priority alert
```

* **Identity:** `announcement_uid = provider:provider_announcement_id`, plus a fallback composite
  key (symbol, PSX publication time, normalised title). Each announcement is one `source_items`
  row; a revised document becomes a `source_item_versions` row (Phase 2 mechanism).
* **Times kept separately:**
  * PSX publication time: from the provider, with the raw string and offset (PKT).
  * Provider delivery time: the webhook timestamp header.
  * Our first-detection time (`collected_at_utc`).
  * The event's effective date: book closure, record date, meeting date. This is extracted later
    and never assumed equal to the publication date.
* **Duplicates and revisions:**
  * The same provider ID arriving twice is ignored.
  * Different IDs with the same symbol, time and title are linked as duplicates.
  * A changed document hash at the same ID or URL becomes a new version.
  * Corrections ("revised", "corrigendum") are flagged and linked to the original.
* **Recovery after missed runs:** a checkpoint records the last PSX publication time received. On
  restart, or after any gap of more than one interval, call "announcements by date range" from
  the checkpoint minus a safety overlap (e.g. 2 hours). Duplicates are absorbed by the
  idempotent intake.
* **Prioritisation:** the provider's category or type field gives an initial priority (§7), so
  high-priority items are processed first and alerted.
* **Permission controls:** the provider is a `sources` row that stays ACTIVE only with approved
  terms (Phase 2 trigger). Webhook intake refuses events from inactive sources, and the kill
  switch and database budgets still apply.
* **Hosting note:** webhooks need an HTTPS endpoint that is always reachable. GitHub Actions
  cannot receive webhooks. Options: a small serverless function that writes to Turso, or REST
  polling from GitHub Actions on a schedule. Polling every 15 minutes during market hours is
  within free Actions minutes for a public repo, at the cost of latency. Choose after pricing.

## 6. Historical backfill design (separate permission)
* **Separate workflow and separate approval.** A live-feed agreement does not automatically
  allow bulk history.
* Batches by **date window × company or category** (e.g. one month × KSE-30) through the
  provider's date-range endpoint, within the provider's rate limits and our Turso budgets.
  Batches resume from checkpoints.
* **Coverage ledger:** for each (period, symbol), record requested / received / count /
  provider-reported total / gaps, so missing periods are explicit and never assumed empty.
* Dry-run mode first, to measure volume and quota before writing.
* Retained fields are limited to what the agreement allows (metadata, links, hashes, excerpts).

## 7. Trading-intelligence categories (for later phases; no scores implemented)

| Category | Initial priority | Why it moves prices | Later-phase outputs |
|---|---|---|---|
| Financial results | P1 | earnings surprise, payout | EPS/profit vs history; direction; confidence; evidence |
| Dividend / bonus / right shares | P1 | payout, dilution, entitlement dates | amounts, book closure, ex-date; effective date ≠ publication |
| Material information | P1 | unknown until read | extracted claim; affected companies / sectors |
| Major contracts / orders | P1 | revenue visibility | size vs revenue if sourced; otherwise qualitative |
| Mergers / acquisitions / schemes | P1 | valuation, swap ratios | parties, ratio, stage (proposal ≠ approval ≠ sanction) |
| Debt default / restructuring | P1 | solvency | instrument, amount, counterparties |
| Production shutdown / operational developments | P1 | volume / cost | plant, duration, capacity share if sourced |
| Regulatory action (SECP / PSX notices, suspensions) | P1 | trading risk | action, scope, duration |
| Unusual price and volume notices (PSX queries and replies) | P1 | signals undisclosed information | link to the company's reply |
| Management changes | P2 | governance | role, effective date |
| Board meeting notices | P2 | upcoming catalyst (results, payout) | meeting date → catalyst calendar |
| AGM / EOGM, routine notices, transfers of shares by directors | P3 | low, or context-dependent | — |

For each announcement, the future engine (Phase 3+) estimates potential financial significance,
affected companies and sectors, direction, confidence and evidence. **No impact score is
implemented in this investigation.**

## 8. Unresolved questions and costs
* **Costs:** none published by Capital Stake, Mettis Global or PSX (data licence). Sarmaaya's
  consumer plans (PKR 4,000–6,000 per month) are not data licences. All costs need provider
  quotes, and no spend is proposed until quotes are presented.
* **PUCARS:** its content, terms and any subscriber or notification options could not be verified
  because of the expired certificate. Check again later, or ask PSX.
* **Latency:** the actual delay from PSX publication to webhook delivery is not measured. A trial
  is needed.
* **History depth:** how far back Capital Stake's and Mettis' announcement archives go is not
  stated.
* **Capital Stake's terms of service:** not verified, because the page needs JavaScript.

## 9. Exact permissions needed

**From a redistributor (Capital Stake first, Mettis Global as alternative). Nothing has been sent.**
1. Access to corporate announcements: REST (by date range, symbol, type) and the `pucars` webhook
   channel, with document links and PSX publication timestamps.
2. Written confirmation that our use is covered, including PSX's approval where PSX data is
   involved:
   * storing announcement metadata, links and hashes in our **private** Turso database;
   * **historical retention** indefinitely;
   * **retrieving the original documents** for analysis (or confirming that the links only may be
     stored);
   * display in a **private, authenticated** Streamlit dashboard for the owner only;
   * **LLM processing** of announcement text for extraction and summaries, with no model training;
   * **historical backfill** to a stated depth.
3. **No public redistribution.** State this explicitly.
4. Price, rate limits, delivery-latency commitments, and the termination and data-deletion terms.

**From PSX (alternative or in addition), via Data Services & Vending / marketdatarequest@psx.com.pk**
1. Written permission or a licence for automated retrieval of company announcements and their
   documents from PSX websites for a private, non-redistributed research database. Alternatively,
   the licence product that covers this, and its price.
2. Whether PUCARS offers a subscriber notification or feed, and on what terms.
3. Confirmation of whether the Phase 1 company master, compiled once from 51 Data Portal profile
   pages, requires a licence or should be rebuilt from a licensed source.

## 10. Source-register findings (not activations)
These findings are recorded here. The registry itself lives in PR #5 (`database/seed/sources.json`
and the generated `docs/SOURCE_ACCESS_REGISTER.md`), which must not be modified until it is
approved. Once PR #5 is merged, add or update these entries, **none of them ACTIVE**:

| Source ID (proposed) | Lifecycle | Terms | Licensing | Notes |
|---|---|---|---|---|
| `psx`, `psx_dps` (existing) | RESTRICTED | prohibits_automation | permission_required | Unchanged; add: reCAPTCHA present; data requests via marketdatarequest@psx.com.pk |
| `pucars` (new) | REVIEWED | not_reviewed | unknown | TLS certificate expired on 2026-11-07; not verified |
| `capitalstake` (new) | LICENCE REQUIRED | not_found (needs JS) | licence_required | Documented REST, WebSocket and webhook APIs incl. `pucars` announcements channel; PSX-authorised redistributor |
| `mettis` (existing) | LICENCE REQUIRED for data | not_found | licence_required | MG Link API for internal or redistribution use; PSX-authorised redistributor |
| `sarmaaya` (new) | RESTRICTED | prohibits_automation | personal_non_commercial | PSX-authorised redistributor; no API documented |
| `investify` (existing) | RESTRICTED | prohibits_automation | permission_required | See INVESTIFY_SCS_TRADE_ASSESSMENT.md |
