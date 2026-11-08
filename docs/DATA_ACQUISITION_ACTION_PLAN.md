# Data acquisition action plan

Nothing in this plan is approved. Each step needs the owner's go-ahead. No provider has been
contacted.

## 1. Pursue immediately (no cost; owner approval needed)
1. **EIA Open Data (candidate):** read the API Terms of Service and record the attribution wording.
   Only after **explicit owner approval** does the owner register a free key and EIA become eligible to
   be classified `APPROVED_AUTOMATION`.
2. **ADB (candidate):** identify the CC BY 3.0 IGO datasets and publications relevant to Pakistan,
   and record each item's licence and attribution. Joint and "All Rights Reserved" items are excluded
   unless separately cleared. Approval is for the owner.
3. **World Bank:** check per-dataset licences for the indicators needed (reserves, GDP, inflation,
   Pink Sheet commodities).

## 2. Request written permission (letters drafted for owner review; not sent)
| Recipient | Ask |
|---|---|
| Express Tribune, Dawn, Business Recorder | Store headline, link, timestamp and short summary; internal search; LLM extraction of facts; keep derived facts; no redistribution; retention period |
| PSX (`marketdatarequest@psx.com.pk`) | Private storage and LLM extraction of manually downloaded documents; licence options for delayed/EOD prices, history, announcements; status of the company master compiled from profile pages |
| SBP | Permitted automated access (EasyData/API) for reserves, FX, rates, remittances |
| FBR, NEPRA, OGRA, PBS, Finance Division | Automated metadata collection and private storage of notifications and releases |
| Standard Capital (SCS Trade) | Whether any data product or licence exists; storage rights |

## 3. Request quotes (only after owner approval; no purchase; nothing sent in this review)
Capital Stake and Mettis are **unverified candidates**. A quote alone is not enough: each provider must
also confirm its authority to license the underlying PSX data and every right in the resolution's §7
checklist. If it can't, the route stays unresolved and is not activated.

- **Capital Stake:** delayed/EOD prices, history depth, adjusted prices, indices, PUCARS webhook,
  financials; rights to store, retain, process with an LLM and display privately; PSX approval scope.
- **Mettis Global MG Link:** the same list.
- **PSX Data Services & Vending:** delayed or EOD licence for internal, non-display use.

## 4. Avoid
- PSX website automation.
- Investify and Sarmaaya automation.
- Scraper packages (pypsx, adeerkhan/PSX-data).
- PSX Terminal.
- Any bypass of 403, robots.txt or CAPTCHA.
- Reuters without a licence.

## 5. Order of work
1. EIA ToS and key (free).
2. ADB and World Bank licence checks.
3. Send permission letters (owner).
4. Request quotes (owner).
5. Decide between Strategies A and B on the quotes.
6. Implement the rights record (§6 of the resolution) as a separate, approved change.
7. Activate sources one at a time.
