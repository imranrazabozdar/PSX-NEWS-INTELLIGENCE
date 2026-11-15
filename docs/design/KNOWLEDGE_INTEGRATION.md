# Knowledge integration: from 4,400 sourced rows to an analyst's brain

Status: PROPOSED design, 15 Nov 2026. No code written. Every new table is `CREATE TABLE IF NOT EXISTS` in
psx-library (`database/library/`), so `scripts/apply_library_migration.py` can apply it after owner approval.

> **Reconciliation, added after the design was written (15 Nov 2026).** The design and some code were produced
> in parallel, so three things here are already out of date:
> 1. **Migration numbers.** `0006` is taken by `video_dating` and `0005` by `video_source`, both applied. The
>    design's tables shift to `0007_source_dating`, `0008_knowledge_graph`, `0009_company_brief`.
> 2. **`video_dating` already exists** (engines/video_dating.py, 215 rows loaded) and holds the rank-bounded
>    estimates. Stage 1 generalises it: `source_dating` is backfilled from it (basis `rank_interpolated`,
>    `title_stated_date`, `title_stated_year`), then also covers filings and articles. The estimator keeps the
>    WIDER year rule (from 1 Jan of the year before the title's year), because a year in a title is the subject
>    year and nothing says how far it sits from the upload; the design's Jan-to-Dec rule is narrower than the
>    evidence supports.
> 3. **The numeric-aware near-duplicate fix is done** (scripts/prepare_transcript_capsule.py, tested, 30 lost
>    rows recovered and loaded). Still open from stage 1: `fact_restatement`, `order()`, the freshness
>    labels, and the leave-one-out anchor test.

**The owner's question.** When news, an announcement or a technical signal arrives, the analysis must carry
what an experienced PSX analyst already knows: each company's background, the macro factors, the sector
issues and how companies are linked.

**The answer in one paragraph.** `research_fact` stays as it is: the immutable record of sourced sentences.
Four thin derived layers go on top, and each can be rebuilt from the rows below it. (1) **Time**: a
per-source dating table that a real date can later override without touching any fact row. (2) **Tags**: each
fact row is tagged against a fixed list of 48 Pakistan factors and 9 link types. Python does the tagging
first; a cheap model handles only the rows Python cannot place, and every tag must quote the row's own words.
(3) **Graph**: `company_factor` and `company_link`, aggregated in Python from the tags. (4) **Brief**: an
analyst brief per company, assembled in Python as of a chosen date and fitted to a token budget. An incoming
event is matched to factors by regex, the factors lead to exposed companies, ranked by a score whose parts
are all shown, and their briefs then feed the existing council. Models interpret; they never date, never
link without a quote, and never supply a number.

## 0. What exists and what is reused

| Existing piece | What it offers | Decision |
|---|---|---|
| `research_fact` + `video_source` | 4,400 rows; rank 0 = newest | Keep immutable. All new layers reference `research_fact.id`. |
| `engines/exposure_mapping.py` + migrations 0002/0008 | `company_exposures`, `company_relationships` (append-only, `valid_from/to`), evidence-status ladder | **Not fed directly.** These tables live in the operational DB, and `company_exposures.source_item_id` is NOT NULL and must point to an approved `source_items` row. Writing research rows there would mean forging source items. **Reused instead**: its direction vocabulary, the `evidence_status` ladder, and the relationship types. |
| `engines/exposure_taxonomy.py` | 6 categories, ~40 subtypes | Each new factor maps to exactly one `(category, subtype)`, so a later bridge into `company_exposures` is a join, not a redesign. |
| `engines/exposure_rules.py` | trigger regexes plus `change_of()`, which reads up/down from text | Reused as the event-to-factor detector for the factors they already cover (oil, rate, PKR, gas, duty). |
| `engines/impact_intel.py` `MECHANISMS` T1-T9 | mechanism chains, offsets, invalidators | Every factor carries its T-code; the brief and the council show that mechanism's offsets and invalidators. |
| `engines/ratios.py` `compute_ratios` | Python ratios from reconciled statements | The only source for a brief's financial position. |
| `scripts/council_run.py` `build_pack` | `TOPIC_KIND` routing; `ORDER BY id DESC LIMIT 40` | Two flaws to fix. `id` is load order, not recency. `MACRO:PAKISTAN` is never pulled in, so a third of the brain is invisible to the council. Replaced by `build_pack_v2` (section 4); `TOPIC_KIND` stays as the fallback. |
| `absorb_sector_capsule.py` near-duplicate skip | word-bag overlap of 0.75 or more → skip | **Bug for "newest wins"**: "policy rate is 22%" and a later "policy rate is 11%" overlap heavily, so the newer figure is silently dropped. Fix: a row whose numeric tokens differ is never a near-duplicate. A true restatement is not dropped either; it is logged in `fact_restatement`, so a newer source refreshes freshness without adding a row. |

## 1. Dating model

A claim has two times, and they are never mixed:
- **said-time**: when the source said it. This is an interval with a basis label, held per *source* (video URL,
  filing, article), not per row.
- **about-period**: the era the claim describes (`research_fact.period`, e.g. "FY25"), and only when the
  speaker stated it.

```sql
-- 0006_source_dating.sql. Append-only. The effective dating is the best-basis, latest-recorded row.
CREATE TABLE IF NOT EXISTS source_dating (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL,            -- research_fact.source_url (video URL, filing URL); or 'name:'||source_name
  date_from TEXT NOT NULL,             -- ISO date, inclusive
  date_to   TEXT NOT NULL CHECK (date_to >= date_from),
  basis TEXT NOT NULL CHECK (basis IN ('api_published','owner_export','filed_statement','article_dateline',
        'title_stated_date','title_stated_year','rank_interpolated','capture_upper_bound')),
  basis_rank INTEGER NOT NULL,         -- 7..0 in the order above; a higher rank always wins
  estimator_version TEXT NOT NULL,     -- e.g. 'rank-interp/1', 'youtube-api', 'owner-export-2026-12'
  evidence TEXT NOT NULL,              -- e.g. 'anchors pos 12 (2025) and pos 31 (2024)'
  recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_restatement (   -- a later source repeating an existing fact
  fact_id INTEGER NOT NULL, source_key TEXT NOT NULL, recorded_at TEXT NOT NULL,
  PRIMARY KEY (fact_id, source_key));
CREATE VIEW IF NOT EXISTS v_source_time AS
  SELECT source_key, date_from, date_to, basis, basis_rank, estimator_version FROM (
    SELECT d.*, ROW_NUMBER() OVER (PARTITION BY source_key
           ORDER BY basis_rank DESC, recorded_at DESC, id DESC) AS rn FROM source_dating d) WHERE rn = 1;
```

**Real dates replace estimates with no row rewritten.** `scripts/date_sources.py --from-api` (or
`--from-export file.csv`) inserts a basis `api_published` row (rank 7). The view selects it at once. Every
fact row, tag and edge is untouched. Briefs whose input hash changes are rebuilt (section 2). Old brief
snapshots keep the `estimator_version` they used, so a past analysis can still be explained.

**Video estimator** (`engines/knowledge/dating.py`, pure Python):
`estimate_video_dates(positions: dict[str,int], anchors: list[Anchor], capture_date: str) -> list[SourceDating]`.
1. An anchor is a title that states a date (basis rank 4, interval = that day) or a year (rank 3, Jan 1 to
   Dec 31).
2. Monotonicity is enforced: position p must lie no later than any anchor with a higher position, and no
   earlier than any anchor with a lower one. That gives a hard interval: [date_from of the nearest
   older anchor, date_to of the nearest newer anchor, or `capture_date` for rows newer than every anchor].
   Basis is `rank_interpolated`. The interval is not narrowed by assuming an upload cadence; that would be
   an invented date.
3. If an anchor breaks monotonicity, the estimator refuses and names it. It does not guess.

**Certainty label** (derived, never stored): `exact` (width 0 days), `narrow` (up to 31), `wide` (up to 366),
`vague` (wider).

**Ordering two claims (the precise rule).** `order(a, b) -> 'a_newer' | 'b_newer' | 'unordered'`. The steps
are applied in sequence; the first that decides wins:
1. Different **slot** (defined below) → never compared.
2. Both have a parseable about-period and the periods differ → the later period is newer. A claim about
   FY25 supersedes one about FY23, whenever each was said.
3. Both come from the same ranked archive (`video_source`) → the lower `archive_position` is newer. The rank
   is exact, so it beats overlapping intervals.
4. The intervals are disjoint (`a.date_from > b.date_to`) → a is newer.
5. Otherwise the intervals overlap → **`unordered`**. Neither supersedes the other. Both stay current, carry
   the `order_basis='overlap'` badge, and are shown side by side. A midpoint sets display order only.

**Slot** (what "the same claim" means): either the same `(company, topic)`, or the same `(company, slot_id)`
where `slot_id = factor_id + '.' + aspect`, and aspect is one of
`level|direction|sensitivity|policy|guidance|capacity|valuation`, assigned by tagging (section 3). Two rows
that do not share a slot are both kept. Supersession is never inferred from loose similarity.

**Fact and view do not supersede each other.** A `fact` (a filed figure) supersedes only an older `fact`,
and an `analyst_view` only an older `analyst_view`. When a view and a fact in the same slot disagree, the
brief shows it as a **fact-versus-view tension**, which is exactly what a reader should see.

**Age and staleness** (computed at read time against `as_of`):
`age_days = (as_of - date_to, as_of - date_from)` and the display reads "said 5-14 months ago". Each topic
family has a half-life in days: `signal` 90, `macro` 180, `commentary` and `cost` and `cycle` and
`valuation` and `returns` and `tax` 365, `operations` and `strategy` and `competitors` 540, `capacity` 730,
`profile` 1095, `method` none.
Freshness:
- `fresh` if the maximum age is within the half-life;
- `ageing` if the minimum age is within it but the maximum age is past it;
- `stale` if the minimum age is past it;
- `timeless` for `method`;
- `undatable` if there is no dating row.
A restatement in `fact_restatement` resets said-time to that of the newest restating source.

**A year ago versus today.** Everything is a function of `as_of`. `build_brief('HUBC', as_of='2025-11-15')`
uses only claims with `date_from <= as_of`. A claim whose interval straddles `as_of` is included with the
badge `may_postdate`. Snapshots are stored and never overwritten:

```sql
-- 0009_company_brief.sql
CREATE TABLE IF NOT EXISTS company_brief (
  id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, as_of TEXT NOT NULL,
  builder_version TEXT NOT NULL, input_hash TEXT NOT NULL,  -- sha256 of sorted fact ids + dating rows + tags
  brief_json TEXT NOT NULL CHECK (length(brief_json) < 65536), created_at TEXT NOT NULL,
  UNIQUE (company, as_of, input_hash));
```
Each council verdict records the `company_brief.id` values it used.

## 2. The company brief

`engines/knowledge/brief.py`:
```python
def build_brief(db, company: str, *, as_of: str, ratios: list[dict] | None = None) -> Brief
def render_brief(brief: Brief, *, budget_tokens: int, sections: tuple[str, ...] | None = None) -> str
def store_brief(db, brief: Brief) -> int          # idempotent on (company, as_of, input_hash)
```

**Sections, and which rows feed each.** Routing is by topic family plus tag, done in Python.

| Section | Fed by | Notes |
|---|---|---|
| `business` | `profile.*`, `operations.*` | what it sells, to whom, plants |
| `segments` | `profile.*segment*`, `capacity.*` | capacity figures only as stored `value`/`unit` |
| `cost_drivers` | `cost.*` + `company_factor` with aspect `sensitivity` | e.g. coal share of cost |
| `financial_position` | **`ratios.py` output only**: leverage, liquidity, receivable days, finance-cost cover | Text rows about the balance sheet go into a `said_about_financials` sub-list, labelled "analyst says". If no ratios exist, the section reads `NOT COMPUTED: no reconciled statements`. |
| `management_strategy` | `strategy.*`, `commentary.*management*` | |
| `risks` / `catalysts` | `commentary.*`, `signal.*`, tagged risk/catalyst | |
| `valuation_approaches` | `valuation.*`, `method.*` tied to this company or its sector | methods only; no target price is ever produced |
| `sector_cycle` | `cycle.*` on `SECTOR:<X>` for the company's sector | the newest current claim per slot; phase words only as stated in the row |
| `macro_sensitivities` | `company_factor` rows (section 3) | factor, direction, mechanism T-code, evidence count, freshness |
| `links` | `company_link` rows | typed edges with fact ids |
| `coverage` | computed | rows, sources, distinct speakers, newest said-time, share undated, share `analyst_view` |

**One claim inside a section:**
```json
{"fact_id": 1874, "text": "...", "confidence": "analyst_view", "source": "ARN channel, '<title>'",
 "said": ["2024-01-01","2024-12-31"], "basis": "title_stated_year", "certainty": "wide",
 "period": "FY24", "freshness": "stale", "status": "current|superseded|unordered", "superseded_by": null,
 "value": 21.0, "unit": "%"}
```
**Assembly is deterministic:** select rows, compute status with `order()` within each slot, sort within each
section (current first, then by about-period descending, said-time descending, fact before view), and hash.

**Conflicts across time.** A superseded claim is kept, collapsed under its successor. The renderer prints
"earlier view (2023-24, rank 140): ... → current (2025): ...". A change of view is information, not noise.
Two `unordered` claims that disagree are shown as "UNRESOLVED ORDER" and are never merged.

**Context budget.** Tokens are estimated as `ceil(chars/3.5)` (the rows are English text with some names).
Groq's free tier is bound by tokens per minute, not by context length, so a lens call is held to about 4,000
input tokens. `render_brief` fills sections in priority order, which depends on the lens:
- financial lens: `financial_position`, `cost_drivers`, `business`, `risks`, `valuation_approaches`;
- macro lens: `macro_sensitivities`, `sector_cycle`, `cost_drivers`;
- news lens: `catalysts`, `risks`, `links`.

Within a section the renderer takes current claims newest first, at most 6 per section. It is truncated at a
whole claim, and the count left out is printed (e.g. `[+14 older claims not shown]`), so omission is visible.
Each company in the event gets about 1,000 tokens at full depth, for at most 3 companies; the rest are
rendered at "line depth" (top 3 factors plus coverage, about 120 tokens each).

## 3. Interlinkages and factors

```sql
-- 0007_knowledge_graph.sql
CREATE TABLE IF NOT EXISTS factor (               -- seeded from config/factors.json; fixed, versioned
  factor_id TEXT PRIMARY KEY, label TEXT NOT NULL, mechanism TEXT NOT NULL,  -- T1..T9
  exposure_category TEXT NOT NULL, exposure_subtype TEXT NOT NULL,          -- exposure_taxonomy pair
  up_means TEXT NOT NULL, keywords TEXT NOT NULL, macro_series TEXT, taxonomy_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fact_tag (             -- the per-row ledger; one row per (fact, factor) or link
  fact_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('factor','link','none')),
  factor_id TEXT, aspect TEXT, direction TEXT CHECK (direction IN ('up_good','up_bad','mixed','unsigned')),
  other_entity TEXT, relation TEXT, quote TEXT NOT NULL,     -- verbatim substring of fact_text
  tagger TEXT NOT NULL,                     -- 'python:kw/1' | 'model:<id>' | 'owner'
  prompt_version TEXT, status TEXT NOT NULL CHECK (status IN ('accepted','rejected','corroborated')),
  reject_reason TEXT, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS company_factor (       -- DERIVED; rebuilt by Python, never hand-edited
  company TEXT NOT NULL, factor_id TEXT NOT NULL, level TEXT NOT NULL CHECK (level IN ('direct','sector')),
  direction TEXT NOT NULL, n_rows INTEGER, n_sources INTEGER, has_fact INTEGER, ratio_backed INTEGER,
  newest_said_to TEXT, freshness TEXT, evidence_fact_ids TEXT NOT NULL, evidence_status TEXT NOT NULL,
  build_hash TEXT NOT NULL, PRIMARY KEY (company, factor_id, level));
CREATE TABLE IF NOT EXISTS company_link (         -- DERIVED
  src TEXT NOT NULL, dst TEXT NOT NULL, relation TEXT NOT NULL, mechanism TEXT,
  evidence_fact_ids TEXT NOT NULL, derived_by TEXT NOT NULL, evidence_status TEXT NOT NULL,
  build_hash TEXT NOT NULL, PRIMARY KEY (src, dst, relation), CHECK (src <> dst));
CREATE TABLE IF NOT EXISTS entity_alias (         -- folds ticker-less names; owner-confirmed
  name_key TEXT PRIMARY KEY, ticker TEXT, status TEXT NOT NULL CHECK (status IN ('confirmed','no_ticker','pending')));
CREATE TABLE IF NOT EXISTS company_sector (company TEXT PRIMARY KEY, sector TEXT NOT NULL, source TEXT NOT NULL);
```

**Fixed factor taxonomy** (`config/factors.json`, `taxonomy_version='pk-factors/1'`; 48 factors). The
T-code is the mechanism in `impact_intel.MECHANISMS`.

| Group | factor_id (T-code) |
|---|---|
| Monetary and external | `policy_rate`(T3) `t_bill_pib_yields`(T3) `private_credit_demand`(T3) `pkr_usd`(T4) `fx_reserves_current_account`(T9) `remittances`(T4) `cpi_inflation`(T5) `imf_programme`(T9) `sovereign_rating_external_debt`(T9) |
| Fiscal and tax | `budget_psdp_spending`(T9) `corporate_super_tax`(T5) `gst_fed_on_products`(T5) `customs_regulatory_duty`(T5) `investor_tax_cgt_dividend`(T5) `bank_adr_tax`(T5) `petroleum_levy`(T5) |
| Energy | `crude_oil`(T1) `refining_margins_policy`(T1) `omc_margins_deregulation`(T1) `coal_international`(T7) `coal_afghan_local`(T7) `gas_allocation_price`(T2) `rlng_supply_price`(T2) `lpg_price`(T2) `power_circular_debt`(T2) `gas_circular_debt`(T2) `grid_tariff`(T6) `ipp_contract_capacity_payments`(T6) `captive_power_levy`(T6) |
| Commodities and inputs | `steel_scrap_iron_ore`(T7) `cotton_yarn`(T7) `fertilizer_urea_dap_price_subsidy`(T2) `wheat_sugar_support_price`(T5) `palm_oil`(T7) `petchem_pta_polymer`(T7) |
| Demand and structure | `construction_housing_demand`(T9) `auto_financing_rules`(T3) `farm_income`(T5) `consumer_purchasing_power`(T5) `export_demand_textile`(T8) `pricing_discipline_competition`(T5) `regulated_returns_nepra_ogra`(T6) `drug_pricing_drap`(T5) `import_curbs_lc_margins`(T8) |
| Political and external | `political_stability_elections`(T9) `regional_geopolitics_borders`(T8) `shipping_freight`(T8) `privatisation_soe_reform`(T9) |

`up_means` defines the sign for each factor (e.g. `pkr_usd` up = PKR weaker). Market liquidity and FIPI are
left out on purpose: VISION records no source for them, so they would be a factor with no evidence.

**Link relations** (9): `competitor`, `supplier_of`, `customer_of`, `receivable_from` (the circular-debt
chain), `group_affiliate` (common sponsor), `subsidiary`, `associate`, `substitute`, `same_sector`. The middle
four reuse the `company_relationships` vocabulary.

**Derivation: which tier does what.** Every model step writes to `fact_tag` per `fact_id`, so a restart
resumes from the ledger.

| Step | Tier | What |
|---|---|---|
| D1 sector membership | Python | `company_sector` from the Investify profile; `video_source.sector_bucket` as fallback. `same_sector` edges come from this, with no model. |
| D2 alias folding | Python + owner | Fold names onto tickers using `entity_key()` against the Investify symbol list. Any remaining name becomes `pending`, for one owner pass (about 20 names). |
| D3 keyword tags | Python | Factor `keywords` regex over `topic` and `fact_text` (e.g. topic `macro.rate_cut_transmission` → `policy_rate`). Expected to place about 55-65% of rows. **Measure it; do not assume it.** |
| D4 competitor edges | Python | `competitors.*` rows (about 75-88): parse the names through `entity_alias`; an edge needs the name in `fact_text`. |
| D5 model tags | **Haiku** for the one-time backfill; a free Groq model for each new capsule *after it passes the same gate* | Only rows D3 left untagged, plus every row that names two or more entities. Batches of 40 rows. The output is per fact id: `factor_id` from the list, `aspect`, `direction`, `quote`; for links, `other_entity`, `relation`, `quote`. **The output schema has no numeric field.** |
| D6 aggregation | Python | `company_factor` and `company_link` from accepted tags. |
| D7 adjudication | **Opus**, rare | Only `company_factor` rows whose evidence directions conflict (`mixed`) for the 30 priority names. The output is a short note citing fact ids, stored as an `owner`-reviewable tag. It never changes a direction by itself. |
| Sonnet | only if Haiku fails the D5 gate on a batch | as with the 2 videos that needed Sonnet in the archive |

**Validation in `engines/knowledge/tag_validate.py`. A tag is rejected, with a reason, unless all of these
hold:**
1. `factor_id` is in `factor` for the current `taxonomy_version`, and `relation`, `aspect` and `direction`
   are in their enums.
2. `quote` is a verbatim, case-folded substring of the row's `fact_text`, at least 3 words long.
3. For a factor tag, the quote contains at least one of that factor's keywords or synonyms. Otherwise the
   status is `rejected: quote does not mention factor`, which blocks "the model thought rates matter".
4. For a link, `other_entity` resolves through `entity_alias` to a known company **and** its name or alias
   appears in `fact_text`. A row's own company can never be the `dst` of its own link.
5. A directed relation cannot appear in both directions (A `supplier_of` B and B `supplier_of` A) without
   owner review.
6. Gold check before a model is used: 80 rows hand-labelled (Opus drafts, owner corrects). A model needs
   factor precision ≥ 0.90 and recall ≥ 0.75 against the gold set, with zero invented links.
7. Corroboration: 10% of model tags are re-run on a second vendor. Agreement marks them `corroborated`.
   Disagreement keeps the tag `accepted` but excluded from ranking until it is reviewed.

**Aggregation** (`engines/knowledge/graph.py`):
`rebuild_graph(db) -> BuildReport` reads accepted tags plus `company_sector` and writes `company_factor` and
`company_link` with a `build_hash`. Running it twice gives the same hash.
- `level='direct'`: a tag on a row whose company is the ticker.
- `level='sector'`: a tag on a `SECTOR:<X>` row, inherited by every company in X and labelled as inherited.
- Direction: the newest current slot under `order()`. Unordered disagreement gives `mixed`.
- `ratio_backed=1` when a computed ratio supports the channel: `policy_rate` with net debt/equity above 0.5
  or finance cost/EBITDA above 0.2; `pkr_usd` with an FX gain/loss line present; the two circular-debt
  factors with trade receivable days above 120.
- `evidence_status` reuses the Phase 4 ladder: `potential` when the row is `fact` or ratio-backed,
  otherwise `unverified`; `confirmed` only after owner review.

## 4. Integration points

New package `engines/knowledge/`: `dating.py`, `tagging.py`, `tag_validate.py`, `graph.py`, `brief.py`, and
`transmission.py`. It reads psx-library (`library_db`) for knowledge, and the operational DB only through
existing read functions (`news_tagging.recent_news`, `announcement_routing.classify`, the ratio inputs).

**The deterministic event path** (`transmission.py`):
```python
@dataclass(frozen=True)
class FactorHit:  factor_id: str; change: int | None; matched: str; method: str   # 'regex' | 'model:<id>'
@dataclass(frozen=True)
class RankedExposure:
    company: str; factor_id: str; level: str; net_sign: int | None   # +1 benefit, -1 suffer, None unsigned
    score: float; components: dict[str, float]; fact_ids: tuple[int, ...]; freshness: str; via: str | None
def detect_factors(text: str) -> list[FactorHit]          # factor keywords + exposure_rules.change_of
def exposed_companies(db, hits: list[FactorHit], *, as_of: str, named: list[str],
                      limit: int = 8) -> list[RankedExposure]
def transmit(db, event_text: str, *, as_of: str, named: list[str] = ()) -> Transmission
```
1. `detect_factors`. A regex is tried first. If nothing matches, one free-model call classifies the text into
   at most 3 `factor_id`s from the fixed list, and each choice must quote the event text (validation rule 2).
   `change` comes from `exposure_rules.change_of`, otherwise it is `None` (the event is unsigned).
2. `exposed_companies`. The candidates are the companies named in the event (via `entity_resolution` /
   the news tagger), plus `company_factor` rows for each hit, plus one hop over `company_link`
   (`receivable_from`, `supplier_of`, `customer_of`, `group_affiliate`) with `via` set.
   `score = level_w × evidence_w × fresh_w × verify_w`, where:
   - `level_w`: named 3, direct 2.5, sector 1.5, one-hop 1;
   - `evidence_w = 1 + ln(1 + n_sources)`;
   - `fresh_w`: fresh 1, ageing 0.7, undatable 0.5, stale 0.4;
   - `verify_w`: ratio-backed 1.5, `fact` row present 1.2, otherwise 1.

   `net_sign = change × sign(direction)`, and it is `None` if either is unknown. The score ranks attention.
   It is not an impact size, and it is shown with all its `components`.
3. For each of the top `limit` companies: `build_brief(company, as_of)`, stored and reused if the
   `input_hash` is unchanged.
4. `build_pack_v2(event, transmission, briefs, db)` in `scripts/council_run.py`. It keeps the `Evidence` and
   `EvidencePack` contract, adds kind `exposure` to the macro lens's `ROLE_EVIDENCE`, and renders each
   section as items whose `id` is `f<fact_id>` (or `r<ratio_id>`, `x<company>:<factor>`). That keeps
   `_clean_assessments` working: a model can cite only pack ids. Each lens gets the sections in its
   priority order from section 2. `MACRO:PAKISTAN` rows enter **only** through the hit factors (by
   `fact_tag.factor_id`), at most 8 per factor. This ends the "never included" gap without flooding the
   lens with all ~1,000 rows.

| Consumer | Hook |
|---|---|
| (a) council | `council_run.py --event ... [--companies ...]`. Without `--companies` it calls `transmit()` to choose them. The verdict JSON gains `transmission` (hits, ranked exposures with components) and `brief_ids`. |
| (b) news | A new step `engines/knowledge/news_hook.py:annotate(item) -> Transmission` runs on items `recent_news` returns. It is Python only (regex factors, plus companies from the existing tagger), and the council is run only on items whose top score passes a threshold, so the free quota is spent where it matters. |
| (c) PSX announcements | `announcement_routing.classify` gives the kind. A results announcement → financial-lens pack with the new ratios against the brief's previous ratios. A board, dividend or capex announcement → brief plus one-hop links (subsidiary, associate, group, competitors), since a competitor's capacity expansion is news for its peers. |
| (d) technical signals | Computed **inside this project** from its own SCS OHLCV (`market_intel.daily_closes`), never from the owner's technical engine (ADR-0001). `explain_signal(db, ticker, signal, window_days=10) -> SignalContext` lists the factor hits from news in the window that touch this ticker's `company_factor`, recent announcements, and the brief's catalysts. Output: "possible fundamental context" or "no stored context found". It never confirms or recommends a trade. |
| (e) Streamlit | A "Brief" block in `app.py:_company_page`, read-only SELECT. It shows sections with freshness and certainty badges, superseded claims collapsed, a factor table (factor, direction, mechanism, evidence count, freshness, `ratio_backed`), links with their quotes, and the coverage panel. It is built only after stage 6 is TESTED (CLAUDE.md rule). |

## 5. Build order

Each stage stops at its acceptance gate for owner approval and updates `docs/STATUS.md`. Token figures are
estimates for the full 4,400 rows.

| # | Stage | Tier | Acceptance test | Cost |
|---|---|---|---|---|
| 1 | Dating: `source_dating`, `v_source_time`, estimator, `order()`, freshness; numeric-aware near-duplicate fix + `fact_restatement` | Python | Every `research_fact.source_url` has exactly one effective dating. Leave-one-out on the 13 year anchors: each held-out anchor falls inside its own estimated interval. An inserted `api_published` row wins with no other table changed. `order()` is tested on all 5 steps. A capsule with a changed number is written, not skipped. | 0 tokens |
| 2 | Entities and sectors: `entity_alias`, `company_sector` | Python + owner | Every distinct `company` resolves to `confirmed`/`no_ticker`/`pending`; the counts are reported. The `pending` list goes to the owner. | 0 tokens; about 20 owner decisions |
| 3 | Taxonomy and keyword tags: `config/factors.json`, D3, gold set | Python; Opus drafts the 80 gold labels once | Python tags score precision ≥ 0.90 on the gold set. Coverage per entity is printed, including the share of `MACRO:PAKISTAN` rows tagged. | about 15k in / 8k out on Opus, once |
| 4 | Model tags (D5): prove on one batch of 40 with Haiku, a Groq model and Sonnet, score them, then dispatch | Haiku default; Sonnet only on a failed batch | The gate in section 3, rule 6. The ledger shows every untagged fact id as `factor`/`link`/`none` with a status. Zero links without a verbatim quote. | about 2,000 rows × 90 in + 40 out ≈ 180k in / 80k out, about 50 calls; a Groq rerun fits one day's quota |
| 5 | Graph build: `rebuild_graph`; D7 adjudication | Python; Opus for at most 30 mixed rows | The build hash is identical on rerun. Every edge has ≥ 1 fact id whose text names both ends. The owner spot-checks 20 edges and 20 exposures (≥ 18/20 each correct). | Opus about 30 × 1.5k ≈ 45k in |
| 6 | Brief: `build_brief`, `render_brief`, `company_brief` | Python | A HUBC golden brief. `as_of=2025-01-01` excludes every claim with `date_from` after it. `financial_position` contains only ratio ids. Rendered output stays within budget, with an omission count. | 0 tokens |
| 7 | Transmission and council: `transmit`, `build_pack_v2`, news and announcement hooks | Python; free models at run time | Five replay events (oil spike, 100bp rate cut, PKR −5%, gas price notification, super-tax change) each give ranked exposures with components and fact ids. Every cited id resolves. Each council run uses ≤ 4 calls and ≤ 16k tokens. The existing council tests still pass. | about 16k tokens per council run on free quota |
| 8 | Streamlit Brief block and `explain_signal` | Python | AppTest renders HUBC. A company with no rows shows "no stored knowledge", not an empty table. | 0 |

## 6. Risks and limits, and how each is shown

| Limit | Why it stays wrong or thin | How the user sees it |
|---|---|---|
| One analyst channel is about 88% of the rows | The brief reflects one school of thought; agreement among its own videos is not independent corroboration | The coverage panel shows distinct speakers/sources and the share from the one channel. `n_sources` counts **source organisations**, not videos, for `evidence_w`. A single-source company gets the badge "single-source view". |
| Undated claims | Intervals can be wide; overlap leaves many pairs `unordered` | Certainty badges (`wide`, `vague`). An `unordered` disagreement prints "UNRESOLVED ORDER". The brief header shows the share of `vague` claims. |
| Rank errors | One wrong anchor would shift many intervals | The estimator refuses non-monotone anchors. The dating evidence string is shown on hover. |
| `MACRO:PAKISTAN` dilution | `method.*` rows are filed under macro; untagged macro rows never reach an event | `method` rows are treated as scope `method` in views (rows untouched). The untagged macro count is shown on the health page. Rows that stay `none` are listed, not hidden. |
| Ticker-less companies | Rows under a name split a profile until a ticker is confirmed | The `pending`/`no_ticker` counts in coverage, and a symbol page note: "N rows held under a name, awaiting a ticker". |
| Sector inheritance | Not every cement company has the same coal mix | `level='sector'` is always labelled "inherited from SECTOR:X", ranked below direct exposures, and never ratio-backed by another company's numbers. |
| Tagging errors that pass the quote check | A real quote can still be tagged with the wrong direction | Corroboration status; uncorroborated model tags are excluded from ranking; all tags can be traced to their quote in the UI. |
| No financials for most names | Only HUBC, NRL, PSO and the 3 regression names have filed statements | `financial_position: NOT COMPUTED`; `ratio_backed` is 0 and the score multiplier shows it. |
| Score is not impact | Attention ranking only | It is labelled "attention rank, not impact size". No buy/sell/hold wording; scenarios remain Phase 12. |
| Factor list misses an event type | 48 fixed factors | `detect_factors` returning nothing shows "no stored factor matches this event: council runs on named companies only". New factors are added by bumping `taxonomy_version`, never ad hoc. |
