# Data acquisition action plan

Nothing in this plan is approved. Each step needs the owner's go-ahead. No provider has been
contacted.

## 1. Pursue immediately (no cost; owner approval needed)
1. **EIA Open Data:** read the API Terms of Service, then the owner registers a free key. Once
   approved, it becomes the first `APPROVED_AUTOMATION` source (energy prices).
2. **ADB:** identify the CC BY 3.0 IGO datasets and publications relevant to Pakistan; record the
   per-item licence.
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

## 3. Request quotes (no purchase)
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
