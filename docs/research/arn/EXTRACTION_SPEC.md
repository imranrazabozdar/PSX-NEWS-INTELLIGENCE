# Extraction spec: Abdul Rehman Najam transcript archive -> PSX brain

You are building the knowledge base ("brain") of a private Pakistan Stock Exchange research system.
Read the assigned work file and distil DURABLE, REUSABLE market intelligence into structured JSON.

The transcripts are Urdu speech auto-captioned into DEVANAGARI (Hindi) script. Read the Devanagari,
understand the Urdu, write output in ENGLISH. Auto-captions garble proper nouns: infer company names
from context and be careful.

Each video starts with `===== VIDEO =====` and a header (TITLE, VIDEO_ID, URL, SECTOR_BUCKET,
TICKERS_TAGGED, PUBLICATION_DATE: UNKNOWN).

## What to extract
- How a business actually makes money; cost structure, margins, competitive position, moat
- Sector economics: cost drivers, capacity/utilisation cycles, pricing dynamics, regulation
- Transmission rules: "X happens -> Y sector/company is affected because Z" (these are the most valuable)
- Company risks, catalysts, balance-sheet issues, management/governance quality
- Valuation approaches and rules of thumb the analyst uses
- Structural/technical facts (production inputs per unit, tax mechanics, policy mechanics)

Do NOT extract personal-finance coaching (SIP habits, retirement, budgeting, tax-filing how-tos,
motivational content) or channel/community announcements. A purely personal-finance video should
yield zero rows: that is a correct result, not a failure.

## The dating rule (critical)
The archive carries NO publication dates.
- PREFER durable/structural knowledge that stays true regardless of when it was said.
- A time-bound claim (a price, a rate, a result, an outlook) may be extracted ONLY IF the transcript
  states an ABSOLUTE period: a year ("2024"), a fiscal year ("FY25"), a quarter ("Q1 FY26"), or a
  named dated event ("Budget 2026", "the June 2025 hike"). Put that in `period`.
- A RELATIVE period is NOT acceptable: "last year", "recently", "the two years before the video",
  "currently", "these days". If that is all the transcript offers, either drop the claim, or keep it
  ONLY if it is structural and set `period` to null.
- When in doubt, drop it. An undated snapshot corrupts the brain by mixing eras. This matters more
  than volume.

## Output: ONE FILE PER VIDEO, written as you go
Your work file holds several videos (or parts of one long video). After you finish EACH video, immediately
write that video's rows to its own file in the output directory you are given:
  <OUTDIR>/<VIDEO_ID>.json            (or <OUTDIR>/<VIDEO_ID>__p<K>.json if its header says PART K)
Never batch videos into one write. If a video yields no durable market knowledge, write `[]` to its file:
an empty file records that you read it and found nothing, which is a valid result.

Each file is a JSON array. Each element has EXACTLY these keys:
{
  "company": "<entity, see below>",
  "topic": "<topic, see below>",
  "fact_text": "<ONE self-contained sentence, YOUR OWN WORDS, English, MAX 300 characters>",
  "value": <number or null>,
  "unit": "<PKR_per_ton, USD_per_ton, percent, PKR_billions, times, ... or null>",
  "period": "<absolute period as above, or null>",
  "source_name": "Abdul Rehman Najam, '<VIDEO TITLE>' (YouTube transcript, undated)",
  "source_url": "<URL from the header>",
  "video_id": "<the ORIGINAL VIDEO_ID from the header, without any __p suffix>",
  "confidence": "fact" | "analyst_view"
}

Two examples of the right style:
{"company":"SECTOR:POWER","topic":"signal.receivables_build","fact_text":"A rising net receivable per share can mean the government has not paid the IPP, or that the sponsor prefers not to distribute cash; the two readings call for different conclusions.","value":null,"unit":null,"period":null,"source_name":"Abdul Rehman Najam, 'BEST POWER SECTOR COMPANIES TO INVEST IN' (YouTube transcript, undated)","source_url":"https://www.youtube.com/watch?v=yDODF8Q_rTo","video_id":"yDODF8Q_rTo","confidence":"analyst_view"}
{"company":"SECTOR:CEMENT","topic":"cost.energy_share","fact_text":"Coal and power together make up over 70% of a cement maker's manufacturing cost, while limestone from owned leases is only about 5%.","value":70,"unit":"percent","period":null,"source_name":"Abdul Rehman Najam, 'Pakistan Cement Sector Explained' (YouTube transcript, undated)","source_url":"https://www.youtube.com/watch?v=P3f5BA7rJxQ","video_id":"P3f5BA7rJxQ","confidence":"fact"}

Be thorough: extract EVERY distinct durable claim, mechanic and transmission rule, not just the headline
points. A dense analysis typically gives one row per 500-700 characters of English-equivalent content.

## Entities (`company`)
- Listed company: PSX ticker in CAPS (LUCK, FFC, OGDC, PSO, MEBL, UBL, SYS, INDU, SAZEW, MTL, HCAR,
  MARI, PPL, POL, EPCL, LOTCHEM, FATIMA, EFERT, FCCL, MLCF, DGKC, HUBC, ILP, PTC, THCCL, NRL, ATRL,
  PRL, CNERGY, AIRLINK, OGDC...). Use a ticker ONLY when you are confident it is right.
- Company you cannot confidently ticker: its common name in Title Case ("Ghani Dairies").
- Sector: SECTOR:CEMENT, SECTOR:BANKS, SECTOR:AUTOS, SECTOR:OIL_GAS, SECTOR:FERTILIZER, SECTOR:POWER,
  SECTOR:TEXTILE, SECTOR:PHARMA, SECTOR:CHEMICALS, SECTOR:TECH, SECTOR:TELECOM, SECTOR:FOOD,
  SECTOR:TOBACCO, SECTOR:REFINERY, SECTOR:AIRLINES, SECTOR:STEEL, SECTOR:INSURANCE
- Economy-wide: MACRO:PAKISTAN

## Topics (the prefix decides which analyst reads it later - choose deliberately)
- Company analysis -> profile.business, profile.management, profile.segments, commentary.thesis,
  commentary.risk, commentary.catalyst, commentary.financials, commentary.valuation,
  commentary.outlook, competitors.position
- Sector economics -> cost.<slug>, cycle.<slug>, capacity.<slug>, operations.<slug>, valuation.<slug>,
  strategy.<slug>, returns.<slug>, signal.<slug>
- Economy / policy / transmission -> macro.<slug>
- Analytical method or rule of thumb -> method.<slug>
Slugs are short and lowercase: cost.energy_share, macro.rate_cut_transmission, method.oil_gas_valuation.

## Confidence
- "fact": structural/technical/mechanical data that is checkable and uncontroversial (inputs per unit
  of production, how a tariff or tax works, a regulatory mechanism).
- "analyst_view": EVERYTHING else - valuations, outlooks, judgements, projections, preferences.
  When in doubt, analyst_view.

## Hard rules
- fact_text <= 300 characters, your own words, self-contained. Never copy transcript text.
- NEVER produce buy/sell/hold instructions or target prices. Rephrase "I would buy X" as the
  analyst's reasoning, e.g. "The analyst considered X attractive because of its low leverage."
- Never invent a number, date, company or claim that is not in the transcript.
- Deduplicate within your file: one repeated point -> ONE row, attributed to the clearest video.
- Quality over volume. A dense company analysis may give 15-40 rows; personal finance gives 0.

Reply with ONE line only: the number of files written and total rows. Nothing else.

## DENSITY TARGET (important: earlier runs extracted only about half of what was there)
Long files get skimmed. Counter that deliberately:
1. Work through the transcript in order, in sections of roughly 8,000 characters. After EACH section, write
   down every distinct claim, mechanic, number, comparison, example, historical analogy, rule of thumb and
   causal chain you can find in it BEFORE moving on. Do not wait until the end.
2. TARGET: at least ONE row per 700 characters of transcript (a 45,000-character video should give 60+
   rows when it is market content). Personal-finance stretches are exempt.
3. Before writing your files, count your rows. If you are under target, make a SECOND SWEEP over the
   transcript looking only for what you skipped (numbers, comparisons, examples, "because" chains, named
   companies), and add those rows. Then write.
