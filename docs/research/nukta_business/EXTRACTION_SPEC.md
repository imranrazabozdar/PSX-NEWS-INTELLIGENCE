# Extraction spec: Nukta Business (@NuktaBusiness) transcripts -> PSX brain

You are building the knowledge base ("brain") of a private Pakistan Stock Exchange research system.
Read the assigned work file and distil DURABLE, REUSABLE market intelligence into structured JSON.

The transcripts are Urdu speech auto-captioned into DEVANAGARI (Hindi) script. Read the Devanagari,
understand the Urdu, write output in ENGLISH. Auto-captions garble proper nouns: infer company names
from context and be careful.

Each video starts with `===== VIDEO =====` and a header (TITLE, VIDEO_ID, URL,
PUBLICATION_DATE (verified, YYYY-MM-DD)).

## What to extract
This channel is a business-news and interview channel (part of a TV news network): news explainers, economy and
policy reports, interviews with executives, officials and analysts, real-estate and IPO coverage, and stock
market segments. The speaker is often a GUEST or a reporter, so write views as "an interviewee said", "the
reporter noted" or "the company's CEO said", never as the channel's own view; state facts as reported.
Capture BOTH kinds of knowledge:
- DATED news and data: policy and regulatory decisions, budget and tax measures, IMF and SBP actions, prices,
  index moves, IPOs, results, dividends, buybacks, corporate deals, government announcements, trade and
  energy data, each tied to the video's PUBLICATION_DATE.
- DURABLE knowledge: how a business or sector works, cost structures, regulation, transmission rules
  ("X happens -> Y is affected because Z"), company strategy as stated by its own management, risks.
- Interview content: what an executive says about their own company (strategy, capacity, expansion, margins,
  outlook) is valuable: attribute it to the company's management, with the figures they gave.

Do NOT extract personal-finance coaching, generic investing advice for beginners, ads or channel
announcements (personal-finance coaching shows, lifestyle or tech-gadget content, account opening, app downloads, WhatsApp groups). A video of only that yields zero rows.

## The dating rule (this channel is DATED)
Every video header carries PUBLICATION_DATE (verified). So a time-bound claim IS allowed, but:
- Put the date it refers to in `period` as an absolute date ("2026-10-09"), a month ("Oct 2026"), a fiscal
  year ("FY26") or a quarter ("Q1 FY27"). For a snapshot said in the video, use the PUBLICATION_DATE.
- NEVER leave a relative time word in fact_text: today, yesterday, tomorrow, this week, last week, this
  month, last month, this year, last year, recently, currently, now, these days, nowadays, so far, the
  other day, last session, next session. Rewrite with the absolute date computed from PUBLICATION_DATE
  ("On 9 Oct 2026 the KSE-100 closed ..."), or with the named period, or drop the time word.
- If you cannot tell WHEN something happened, either keep it only if it is structural (period null) or drop
  it. When in doubt, drop it.

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
  "source_name": "Nukta Business, '<VIDEO TITLE>' (YouTube, <PUBLICATION_DATE>)",
  "source_url": "<URL from the header>",
  "video_id": "<the ORIGINAL VIDEO_ID from the header, without any __p suffix>",
  "confidence": "fact" | "analyst_view"
}

Two examples of the right style:
{"company":"SECTOR:POWER","topic":"signal.receivables_build","fact_text":"A rising net receivable per share can mean the government has not paid the IPP, or that the sponsor prefers not to distribute cash; the two readings call for different conclusions.","value":null,"unit":null,"period":null,"source_name":"Nukta Business, 'EXAMPLE TITLE' (YouTube, 2026-10-09)","source_url":"https://www.youtube.com/watch?v=yDODF8Q_rTo","video_id":"yDODF8Q_rTo","confidence":"analyst_view"}
{"company":"SECTOR:CEMENT","topic":"cost.energy_share","fact_text":"Coal and power together make up over 70% of a cement maker's manufacturing cost, while limestone from owned leases is only about 5%.","value":70,"unit":"percent","period":null,"source_name":"Nukta Business, 'EXAMPLE TITLE' (YouTube, 2026-10-09)","source_url":"https://www.youtube.com/watch?v=P3f5BA7rJxQ","video_id":"P3f5BA7rJxQ","confidence":"fact"}

Be thorough: extract EVERY distinct durable claim, mechanic and transmission rule, not just the headline
points. A dense analysis typically gives one row per 500-700 characters of English-equivalent content.

## Entities (`company`)
- Listed company: PSX ticker in CAPS (LUCK, FFC, OGDC, PSO, MEBL, UBL, SYS, INDU, SAZEW, MTL, HCAR,
  MARI, PPL, POL, EPCL, LOTCHEM, FATIMA, EFERT, FCCL, MLCF, DGKC, HUBC, ILP, PTC, THCCL, NRL, ATRL,
  PRL, CNERGY, AIRLINK, OGDC...). Use a ticker ONLY when you are confident it is right.
- Company you cannot confidently ticker: its common name in Title Case ("Ghani Dairies").
- Sector: SECTOR:CEMENT, SECTOR:BANKS, SECTOR:AUTOS, SECTOR:OIL_GAS, SECTOR:FERTILIZER, SECTOR:POWER,
  SECTOR:TEXTILE, SECTOR:PHARMA, SECTOR:CHEMICALS, SECTOR:TECH, SECTOR:TELECOM, SECTOR:FOOD,
  SECTOR:TOBACCO, SECTOR:REFINERY, SECTOR:AIRLINES, SECTOR:STEEL, SECTOR:INSURANCE,
  SECTOR:REAL_ESTATE (property market, housing schemes, REITs as a class), SECTOR:AGRICULTURE, SECTOR:EXPORTS
- Economy-wide: MACRO:PAKISTAN

## Topics (the prefix decides which analyst reads it later - choose deliberately)
- Company analysis -> profile.business, profile.management, profile.segments, commentary.thesis,
  commentary.risk, commentary.catalyst, commentary.financials, commentary.valuation,
  commentary.outlook, competitors.position
- Sector economics -> cost.<slug>, cycle.<slug>, capacity.<slug>, operations.<slug>, valuation.<slug>,
  strategy.<slug>, returns.<slug>, signal.<slug>
- Economy / policy / transmission -> macro.<slug>
- Analytical method or rule of thumb -> method.<slug>
- Dated market data and moves -> market.<slug>  (market.kse100_move, market.oil_price, market.foreign_flows)
- Dated company/economy events -> news.<slug>  (news.ipo, news.buyback, news.dividend, news.results, news.policy)
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

## Dated rows: extra rules
- A reported number (index level, price, dividend, payout, ratio) goes in `value`/`unit` AND in fact_text,
  and must appear in the transcript. Speech-to-text garbles numbers: if a figure looks implausible or two
  readings are possible, drop the figure rather than guess.
- Reported events and figures are "fact"; the analyst's reasons, outlook and judgements are "analyst_view".
- Give the entity the right owner: a company event -> its ticker; a sector point -> SECTOR:X; index, oil,
  rupee, rates, flows, budget, IMF -> MACRO:PAKISTAN.

## FIGURES SWEEP (mandatory second pass; earlier runs lost about half of the figures)
Numbers are the most valuable part of a dated video, and they are the easiest to skip. After you finish the
first pass over a video, make a SECOND pass reading ONLY for figures, and make sure every distinct one is in
a row:
- every price, level, rate, percentage, amount, per-unit figure, count, ratio and multiple;
- BOTH sides of a comparison ("EPS 5.70 against 3.60 a year earlier" is two figures, keep both);
- breakdowns and steps (quarterly payouts 0.40 -> 0.50 -> 0.54 -> 0.63 -> 0.66 are each worth keeping);
- spoken numbers in Devanagari words ("साढ़े", "सवा", "डेढ़", "हज़ार", "लाख", "करोड़", "अरब") - convert them;
- alternative readings the speaker mentions ("399 or 398"), and levies, taxes, margins and spreads.
Several figures about one subject may share ONE row if the sentence stays under 300 characters.
Count the distinct figures in the transcript and in your rows before writing; add rows for any you missed.
Also avoid relative counts such as "the last two quarters": name the quarters or fiscal year.
