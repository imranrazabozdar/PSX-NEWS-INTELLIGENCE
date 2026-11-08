# Stage 2: News Intelligence (architecture design)

Status: DESIGN ONLY (2026-11-08, main `a3724a0`). Nothing here is implemented beyond what already exists.
Implementation starts only when the owner authorises a component (§9).

## 1. Starting point: what already exists (verified in the repository)

Stage 2 is mostly **connecting live news to an intelligence substrate that already exists**, not building one.

| Need | Existing component | State |
|---|---|---|
| Raw news, provenance | `sources`, `source_items`, `source_item_versions` (0001/0006), RSS collector, `duplicate_of_item_id` | LIVE: 276 items, metadata only (title, link, times) |
| Canonical events | `events`, `event_revisions` (0002): type, status stage, verification state, direction, magnitude, novelty, horizon, confidence | schema live, **0 rows** |
| Article ↔ event, corroboration | `event_evidence` (claim, claim_type, relation, excerpt, `is_independent`), `story_clusters`, `story_cluster_members` (0007) | schema live, unused |
| Extraction provenance, AI audit | `event_extractions` (schema/prompt/model version, confidence, review flags), `llm_calls`, `engines/llm.py` gateway (kill switch, cost cap, prompt hashing) | gateway NOT CONNECTED (owner decision) |
| Taxonomy | `engines/schema.py`: 23 `EVENT_TYPES`, 14 status stages, claim types, entity types | implemented |
| Entity resolution | `engines/entity_resolution.py`, `company_identifiers`, `company_aliases` (company master: 51 seeded companies; aliases derived from legal names and tickers at load), `engines/news_tagging.py` (capital tickers, exact multi-word names, themes) | implemented; tags not stored |
| Exposure | `company_exposures` (documented facts), `exposure_candidates` (0008; levels direct/indirect; evidence status confirmed → unverified; origin rule/model; review), `engines/exposure_rules.py`, `exposure_taxonomy.py` | implemented (Phase 4); **no approved company-evidence source**, so no real exposures |
| Impact | `impact_assessments` (0009): mechanism T1–T9, separate direction / magnitude / horizon / 4 confidence dimensions, `impact_transmission_steps`, `impact_scenarios`, reviews, unclassified-company view | schema live; engine is Phase 5 (designed in `PHASE_5_*`) |
| Macro inputs | `commodity_prices`, `financial_metrics`, `sector_metrics` (0003) | empty; macro sources need approval (`MACROECONOMIC_DATA_SOURCE_REVIEW.md`) |
| Watchlist | `user_watchlist` (0004), `media_accounts` (0004, no authorised access) | exists |

**Central gap (verified):** the Phase 3 pipeline (`engines/pipeline.py`) only processes items with
`permitted_excerpt`, which no collector sets. So **0 of the live RSS items can reach the event layer**. Stage 2's
first job is a deterministic **headline path** into the existing tables.

## 2. Pipeline

```
 acquisition (unchanged, independent)          intelligence (new job; reads acquisition tables, never writes them)
 ─────────────────────────────────────         ────────────────────────────────────────────────────────────────
 RSS / official / SCS collectors                1 NORMALISE   item → canonical headline record (times, source, owner, tier)
   └─> source_items ──────────────────────────▶ 2 CLUSTER     exact dup (duplicate_of_item_id) → near-dup (similarity) →
       (+ duplicate_of_item_id)                               same-story cluster → event: new | update | repeat
                                                3 CLASSIFY    rules → EVENT_TYPES (+ secondary types); status stage
                                                4 ENTITIES    tickers / exact names → company_id (else unresolved);
                                                              regulators, commodities, countries, indicators
                                                5 CORROBORATE distinct owners & primary sources → verification_state
                                                6 EXPOSE      event × company → exposure_candidates (direct/indirect,
                                                              verified / inferred / unknown, review)
                                                7 IMPACT      T1–T9 transmission → impact_assessments (direction,
                                                              materiality, horizon, confidences, scenarios)
                                                8 PRESENT     Streamlit intelligence views (read-only, cached)
            optional AI (gateway, cost-capped, cached) assists 3/4/6 only for flagged ambiguous items → human review
```

Every stage is **idempotent and re-runnable**. It is keyed by `source_item_id` and the ruleset or schema
version; reprocessing appends new extraction or revision rows and never overwrites.

## 3. Components and design decisions

### A. Normalisation and deduplication
* **Input:** non-duplicate `source_items` (`duplicate_of_item_id IS NULL`).
  * Times: `published_at_utc` (status `known` / `date_only` / `unknown`) and `collected_at_utc`. Both are kept, and
    their uncertainty is recorded.
  * **Headline only:** the excerpt is the verbatim title. That's permitted metadata, and `event_evidence.excerpt`
    accepts 1–1000 characters.
* **Dedup layers:**
  1. Exact cross-feed duplicates are already marked at collection.
  2. Near-duplicates: `engines/similarity.py` on normalised titles, within a time window (e.g. 72 h), giving
     `story_cluster_members.is_near_duplicate`.
  3. Same story, new facts: same cluster, but with a new number, status stage or entity. The event gets
     `novelty = update` and a new `event_revisions` row. Otherwise the item is evidence with `novelty = repeat`.
* **Corroboration never counts duplicates.** `event_evidence.is_independent = 1` only for the first item per
  distinct `sources.owner`. Syndicated copies and other feeds of the same publisher count as 0.

### B. Classification (no new taxonomy; reuse the 23 `EVENT_TYPES`)
* **Requested categories map to existing types**, for example:

  | Requested category | Existing type |
  |---|---|
  | Results / earnings | `corporate_result` |
  | Dividends / bonus | `corporate_dividend` |
  | Corporate actions, M&A | `corporate_action` |
  | Management / ownership | `management_change` |
  | Contracts / orders | `corporate_announcement` |
  | Regulation | `regulatory_action` |
  | Tax / fiscal | `tax_policy` / `fiscal_policy` |
  | Rates / banking | `monetary_policy` |
  | Inflation / FX | `economic_indicator` |
  | Oil, gas, commodities | `commodity_price` / `commodity_supply` |
  | Circular debt, power tariffs | `energy_policy` |
  | IMF | `imf_program` |
  | Privatisation, government | `fiscal_policy` / `political` |
  | War, sanctions, regional | `geopolitical` / `security_incident` |
  | Trade / exports | `trade_policy` |
  | Market-wide | `market_structure` |
  | Legal | `legal_court` |
  | Disruptions | `infrastructure` |

  The taxonomy is extended only by editing `schema.py`, which validates; no migration is needed.
* **Multiple classifications:** `events.event_type` stays the *primary* type. Secondary types go in
  `event_extractions.extracted_json.secondary_types`. A join table is deferred until a query needs it (§6).
* **Method:** deterministic first. Keyword and phrase rules extend `news_tagging.THEMES` into type rules, plus
  status-stage cues (e.g. "proposes", "approves", "notifies"). Anything not matched → `other` +
  `needs_human_review`, optionally sent to AI (§4).

### C. Entities
* **Companies:** only capitalised PSX tickers or exact multi-word legal/short names, confirmed by
  `entity_resolution.resolve` (existing safeguards: no single ambiguous words such as "Lucky" or "Engro").
  * Resolved companies → `event_companies` with `reviewer_status = pending`.
  * Ambiguous or unresolved mentions are recorded, never assigned.
* **Groups and subsidiaries:** `company_relationships` (0008), used only where a relationship row exists with
  evidence.
* **Other entities** (regulators, government bodies, institutions, countries, commodities, indicators) use the
  existing `ENTITY_TYPES`. They're stored in extraction JSON and drive the T1–T9 triggers.

### D. Exposure and impact (reuse Phase 4/5 as designed)
* **Exposure levels:**

  | Level | Basis |
  |---|---|
  | Direct | Company named, or documented exposure (`company_exposures`, confidence `documented`) |
  | Indirect | Rule-derived from sector classification or relationship (`exposure_candidates.origin = rule`, evidence_status `potential`) |
  | Unknown | No basis; listed in `impact_unclassified_companies` |

  **Never invented:** a company without documented or derivable exposure is shown as unknown, not as
  unaffected.
* **Transmission:** T1 oil, T2 gas / circular debt, T3 rates, T4 PKR, T5 inflation / tax, T6 power tariffs,
  T7 commodities, T8 geopolitics / shipping, T9 fiscal / IMF, all in `PHASE_5_TRANSMISSION_FRAMEWORK.md`.
  * An event can trigger several mechanisms. Each (company, mechanism) gets its own assessment, so an oil rise
    can be + for E&P, mixed for refiners and OMCs, and − for fuel users at the same time.
* **Assessment fields** already exist in `impact_assessments`:
  * direction (positive / negative / mixed / neutral / unknown);
  * materiality (`magnitude_level` + `magnitude_basis` qualitative | quantified);
  * horizon (short / medium / long);
  * four separate confidences: evidence, exposure, direction, magnitude;
  * scenarios (`impact_scenarios`);
  * expiry policy.
* **Event status:** `events.status_stage` + `verification_state` (developing = rumour / discussion / proposal;
  confirmed = confirmed_fact / notification; superseded = later revision or amendment / reversal).
* **Never produced:** buy/sell signals, price targets or return predictions. Fundamentals, sector conditions,
  macro, sentiment and geopolitics stay separate, through the mechanism and the exposure category.

### E. Macro and geopolitical
* External events enter as events with no company. Their entities (Brent, PKR, policy rate, IMF, Strait of
  Hormuz…) trigger mechanisms, and companies are reached only through exposure.
* **No assumed correlation:** "US market fell" is a `market_structure` / sentiment event with **no**
  company impact unless a mechanism applies. Correlation is never treated as causation.
* Quantified magnitude needs sourced benchmark data (`commodity_prices` etc.). Until a macro source is
  approved, magnitude stays `qualitative` with low confidence.

### F. Source reliability
* **Source tiers** use the existing `sources.reliability_tier` and `source_type`:
  * primary: PSX, SBP, PBS, ministries, regulators;
  * reputable secondary: established newspapers and agencies;
  * unverified / opinion: claim types `analyst_interpretation`, `personal_opinion`, `rumour`.
* **Verification state:**

  | State | Rule |
  |---|---|
  | `single_source` | One independent owner |
  | `corroborated` | Two or more independent owners |
  | `primary_confirmed` | A primary source |
  | `disputed` | A `contradicts` relation exists |

* **Media accounts:** the `media_watchlist` entries have no authorised access and are not used until
  approved. Being on the watchlist does not make a source reliable.

## 4. AI versus deterministic
* **Deterministic (default, no cost):** normalisation, dedup, time handling, rule classification, exact
  entity matching, corroboration counts, verification state, confidence aggregation, exposure rules, impact
  direction tables.
* **AI (optional; only through `LLMGateway`):** headlines flagged ambiguous (no type rule, unresolved
  entity, conflicting evidence) and exposure explanations.
  * Inputs and outputs are schema-validated (`schema.py`), with prompt and model versions and cost recorded in
    `llm_calls`, and results cached by prompt hash.
  * Bounded by the daily cost cap and kill switch. Low-confidence results → human review.
* **No dependency on AI:** the pipeline is complete without AI. AI only reduces the review queue. No provider is
  authorised (Claude is the owner's preferred option and is NOT CONNECTED). **Rough estimate, not measured:**
  roughly 100 headlines a day, about 20% flagged, at about 1–2k tokens each on a small model is cents per day.
  It needs owner approval and a key.

## 5. Investment universe
* **The priority universe is manual and stays manual.** Stage 2 reads `user_watchlist` or configuration to
  prioritise display and review. It is never filtered by liquidity.
* **Liquidity qualification is a separate, later concept:** 20 sessions, average daily volume of 100,000 or
  more, plus traded value. It's computed from stored `market_bars`, and only for technical context. It never
  removes priority stocks and never narrows news or event monitoring, which stays market-wide.
* No technical indicators are duplicated, and nothing connects to the technical-analysis project.

## 6. Database: reuse and the minimum change
* **First components need no migration:**

  | Data | Stored in |
  |---|---|
  | Events | `events`, `event_revisions` |
  | Article links | `event_evidence`, `story_cluster_members` |
  | Processing status | one `event_extractions` row per processed item (`model = 'deterministic'`, `schema_version = 'headline-v1'`) |
  | Companies | `event_companies` |
  | Exposure | `exposure_candidates` |
  | Impact | `impact_assessments` + steps / scenarios / reviews |

* **Deferred, possible later migrations** (only on demonstrated need):
  1. `event_classifications(event_id, event_type, rank)`, if secondary-type queries become frequent.
  2. An index on `source_items(collected_at_utc)` for the incremental scan, if its read cost grows. Measure it
     first.
* **Production isolation:**
  * The intelligence job runs **separately** from collection, with its own kill switch, its own per-run
    budget (same 5,000-row cap) and its own `collector_runs.job = 'intelligence'`.
  * It only reads acquisition tables.
  * Production activation is a separate owner approval. Migrations 0007–0009 are already in production, so
    activation needs no migration.

## 7. Streamlit (design only)
* **Intelligence home:** material events in the last 24 h / 7 d, ranked by materiality × verification ×
  priority-universe relevance.
  * Each shows its type, status stage, corroboration count (independent owners) and an "unverified" badge.
* **Event page:**
  * timeline of revisions;
  * evidence list with links and independence;
  * affected companies grouped by level (direct / indirect / unknown) and mechanism, with direction,
    horizon and the four confidences;
  * alternatives and missing information, from `missing_evidence_json` and the scenarios.
* **Company page:** events affecting it (direct versus via mechanism); positive / negative catalysts kept
  separate from long-term fundamentals.
* **Sector and macro pages:** sector aggregates (`impact_sector_aggregates_current`) and macro drivers by
  mechanism.
* **Review queue:** pending `event_companies`, `exposure_candidates` and flagged extractions.

## 8. Future-stage interfaces (not implemented)
* **Fundamentals and valuation** (Phases 8 and 12) feed `financial_metrics` / `company_exposures`, which raises
  exposure confidence and enables quantified magnitude.
* **Technical context:** a read-only market-data view (`market_bars_current`) only; no indicators copied from
  the technical project.
* **Event studies and calibration** (Phase 14): `market_outcomes` (0003) joins events to later price windows to
  calibrate confidence.

## 9. Implementation plan

| # | Component | Reuses | New code | Migration | Tests | Acceptance |
|---|---|---|---|---|---|---|
| **1** | **Headline event builder**: normalise, cluster, create or attach events, evidence, provenance | `news_tagging`, `similarity`, `repositories`, `events`, `event_evidence`, `story_clusters`, `event_extractions` | `engines/headline_events.py` + CLI (local / CI only) | **No** | dup / near-dup / update / repeat; independence by owner; idempotent rerun; budget; no writes to acquisition tables | Fixture headlines give correct events, 0 duplicate corroboration, rerun gives 0 new rows |
| 2 | Rule classification + status stage | `schema.EVENT_TYPES`, themes | type and stage rules | No | per-type fixtures; ambiguity goes to review | ≥ owner-agreed precision on a labelled sample |
| 3 | Company and entity mapping | `entity_resolution`, `event_companies` | entity persistence | No | false-match guards (Lucky, Engro); unresolved kept | 0 assignments from ambiguous names |
| 4 | Corroboration and verification state | `sources.owner`, `reliability_tier` | state rules | No | syndication, primary, contradiction | State matches the rules table |
| 5 | Exposure candidates from events | `exposure_rules`, 0008 | event → candidate rules | No | direct / indirect / unknown; no invented exposure | Every candidate cites an evidence or rule id |
| 6 | Impact (Phase 5 engine) | 0009, T1–T9 docs | mechanism engines | No | per `PHASE_5_TEST_STRATEGY.md` | Phase 5 acceptance |
| 7 | Intelligence dashboard | `app.py`, the 0009 views | read-only views | No | data functions | Shows only implemented data |
| 8 | Optional AI assist | `LLMGateway`, `llm_calls` | prompts / schemas | No | schema rejection, cache, cost cap | Owner approves provider and budget |
| 9 | Production activation | orchestration patterns | workflow step / job | No | dry run | Owner approval |
| 10 | Calibration | `market_outcomes` | event studies | Maybe | — | Later stage |

## 10. Recommended first coding task
**Component 1, the headline event builder, local and CI only.** It turns non-duplicate RSS headlines into
`events`, `event_evidence` (excerpt = verbatim title; claim_type `news_report`; independence by publisher owner)
and story clusters (new / update / repeat), with one `event_extractions` provenance row per item
(`model = 'deterministic'`). It is incremental, idempotent and budget-respecting, with a primary type from
the existing theme rules or `other` + review.

There is no AI, no migration and no production run. It unlocks Components 2–7.

## 11. Risks, limitations, open decisions
* **Headlines only:** event detail, figures and stage are often missing, so confidence must stay low and the
  missing information explicit. Richer text needs a permitted source (company filings / PSX notices). That's a
  separate source-approval track.
* **Clustering errors:** over-merging hides new developments, and under-merging inflates corroboration. Thresholds
  need a labelled sample (owner).
* Company master covers 51 companies; expanding it needs an approved company-list source.
* **Exposure is the binding constraint:** with no approved company-evidence source, most impacts stay indirect or
  unknown and low confidence. That's honest, but of limited use until fundamentals / filings are approved.
* **Open owner decisions:**
  * the AI provider and budget (or none);
  * the labelled evaluation sample and precision targets;
  * whether intelligence runs in the collection workflow (as a second job) or its own workflow (recommended:
    its own);
  * the ranking weights for the home view.

## 12. Implementation notes: batch 1 (Components 2–4)

`engines/event_intel.py` runs after the headline builder. It processes each built item once and records an
`event_extractions` row (`event-intel/1`, deterministic) in the same transaction as any event revision.

**Classification** (`engines/event_classification.py`)
* Contextual rules: a subject term, plus a context term where one is listed, plus a company mention for
  corporate result and announcement types. The primary type is the first matching rule in priority order.
  Court matters rank as `legal_court` ahead of policy types.
* Secondary types are kept in the per-item record and the revision snapshot. No new table.
* Status-stage cues map to the existing 14 stages. Claim nature (`news_report`, `rumour`,
  `personal_opinion`, `prediction`) is kept separate from the stage.

**Status and history**
* An event built only by the headline builder, with no `event-intel/1` record, is **Not assessed**:
  `classification_status()`. Its `not_applicable` stage must not be shown as an assessment.
* Changes are recorded only as new revisions: type out of `other`, a stage development (e.g.
  `proposal -> approval`), and verification state. Repeats cause no revision. A builder UPDATE on a figure
  without a unit is noted as not material.

**Entities**
* Companies come only from the existing exact-match resolver (capital tickers, exact multi-word names; 51
  seeded companies).
* Company-like names that aren't in the master, and ambiguous names, are kept with relation `unresolved` or
  `ambiguous` and flagged for review. They are never assigned.
* Regulators, government bodies, institutions, countries, commodities, indicators and PSX sectors come from
  exact phrases (relation `direct`). Implied entities (e.g. NEPRA → electricity tariff) have relation
  `context`. No company is ever inferred from a sector.

**Evidence**
* The publisher group is `sources.owner` when recorded; otherwise the registrable domain. The live sources
  have no owner, so feeds of one publisher share their domain.
* Independence is `not_independent` (a stored or near duplicate, or the same publisher group) or `unknown`.
  It is **never** `independent` from headlines, and different domains are not confirmation.
* Verification state:

  | State | When |
  |---|---|
  | `primary_confirmed` | Only for a `primary_official` source reporting it, and not a rumour |
  | `disputed` | A denial, or opposing stages from different publishers within 48 h |
  | `unverified` | Otherwise. Media repetition never reaches `corroborated` |

**Limitations / deferred**
* The rules are English keyword-and-context rules, untuned on a labelled sample.
* Single-word company names (e.g. "Engro") are never assigned.
* `event_evidence` is append-only, so independence assessed here lives in the processing record.
* Concurrent runs are safe per item but can interleave event revisions. Run one processor at a time.
* Not run on production data.

## 13. Implementation notes: batch 2 (Components 5–6)

**Exposure: existing Phase 4 engine, unchanged rules**
* `engines/impact_intel.py` calls `exposure_mapping.map_event` for every event that batch 1 assessed.
  `load_event` now also reads batch 1's directly resolved companies from `event-intel/1` records. Ambiguous
  and unresolved names are never passed on.
* Exposure levels:

  | Level | Source |
  |---|---|
  | Direct | A company named in the event; or a rule link to a **documented** `company_exposures` row |
  | Indirect | A documented subsidiary or associate relationship |
  | Contextual hypothesis | Phase 4 sector-level candidates (oil, gas and rate rules only), marked "sector membership alone is not proof", evidence status `unverified` |
  | None | Reported (`no_established_exposure`), never filled |

* Company-specific events never spread to sector peers.

**Impact: T1–T9 exactly as `PHASE_5_TRANSMISSION_FRAMEWORK.md`**
* **Which mechanisms apply:** a rule candidate gets its rule's mechanism (R-OIL→T1, R-GAS→T2, R-RATE→T3,
  R-PKR→T4, R-DUTY→T5). A named company gets only the mechanisms the event supports (`event_mechanisms`).
  T6–T9 therefore appear only for named or related companies, because no rules exist for them. An event
  with no supported mechanism is reported as "no demonstrable PSX transmission". A global event, such as US
  equities, needs a mechanism; oil and commodities have one.
* **Direction:**
  * the documented candidate sign;
  * otherwise the framework's sector roles: T1 E&P +, refiners and OMCs mixed; T2 fertiliser feedstock −;
    T3 banks unknown;
  * otherwise `unknown`.

  Any unstated change also gives `unknown`. Opposite signs aggregate to `mixed` and are never netted.
* **Magnitude:** qualitative only. `low` for indirect or sector-level; `not_assessable` without a documented
  share. Thresholds A and B are not configured, so nothing is quantified.
* **Horizon:** per framework §5 (T1 and T4 short; T2, T3 and T5–T7 medium; T8 unknown; T9 long).
* **Confidences** are kept separate:

  | Dimension | Value |
  |---|---|
  | Evidence | `medium` only for `primary_confirmed`, else `low` |
  | Exposure | From the candidate's effective status |
  | Direction | `low` unless both direction and exposure are established |
  | Magnitude | Always `low` |

* **Status:** every assessment is created `scenario_only`, or `needs_review` / `event_disputed`. Nothing is
  upgraded here, so weak exposure never becomes a provisional or confirmed impact.
* **Fundamentals versus market pressure:** each assessment records separate `impact_layers` (fundamental,
  operational, financial, valuation, market sentiment). Fundamental and valuation are "not assessed" without
  sourced `financial_metrics`. Geopolitical and market-wide events are recorded as possible risk-premium
  pressure, "not evidence of a change in fundamentals".
* **Scenarios:** base, optimistic and adverse, each with assumptions, `strengthened_by`, `invalidated_by`
  and "not a forecast or price". No prices, targets or recommendations.
* **Safety:** each assessment and its inputs, steps and scenarios is one transaction, with a unique key per
  (event, company, mechanism, kind, version). Re-runs are no-ops. A later event revision is reported
  `stale`; revalidation is deferred to a reviewed step. Synthetic and real data are never mixed (the
  `synthetic` flag). Run one processor at a time.

**Limitations / deferred**
* No T6–T9 rules, so there are no sector hypotheses for tariffs, coal, routes or fiscal measures.
* Change detection is Phase 4's (e.g. "imposes" is not read as an increase).
* No approved company-evidence source, so every exposure is `unverified` and every confidence `low`.
* Revalidation of stale assessments and the review workflow are not implemented.
* Not run on production data.

## 14. Implementation notes: final batch (Components 7–10)

* **Dashboard** (`engines/dashboard_views.py`, tabs in `app.py`):
  * **Tabs:** Intelligence (macro filter, paginated events, event detail: evidence, history, mechanisms,
    exposure, assessments, unresolved companies, conflicts), Company report, Sector report, Review queue,
    Validation, Readiness.
  * **Caching:** reads are cached for 5 minutes with their timestamp shown.
  * **Failures:** a database failure shows an error, never an empty or successful state.
  * **Not assessed:** events not yet classified show "Not assessed".
* **Reports** (`engines/research.py`):
  * The company report has the 12 requested sections; the sector report shows differing impacts per company.
  * Financials, valuation, prices and technical indicators always show "Not assessed — supporting data
    unavailable.".
  * Each report carries its data timestamp. Assessments are labelled `current` or `historical` (event
    revised since).
  * Export is Markdown (no new dependency). PDF is deferred.
* **Revalidation** (`engines/review_revalidation.py`):

  | Situation | Result |
  |---|---|
  | Result unchanged | Moves to the new event revision (`revalidated`), with steps and scenarios recorded again |
  | Event now disputed | `needs_review` |
  | Result would change | `needs_revalidation` (`evidence_superseded`); the proposal is in the change reason and the earlier conclusion is kept, because 0009 needs a human review for any substantive change |

  It is idempotent and runs one transaction per assessment.
* **Review:**
  * `review_queue()` is read-only. It lists what needs review, why, what a decision would change, and the
    previous actor.
  * Decisions are recorded only through `record_impact_review` or `record_exposure_review`, with a named
    reviewer and notes. 0009 and 0008 enforce one review per transition, newest review only, and accept only
    from provisional.
  * Classification and entity corrections are recorded as human labels, never as rewrites of append-only
    records.
* **Validation** (`engines/validation.py`):
  * Ground truth is `data/validation/labels.json` (human labels only; currently empty).
  * The pipeline runs on the labelled headlines in an isolated in-memory database.
  * Metrics: classification accuracy; entity and exposure precision and recall; independence accuracy;
    impact-direction accuracy and coverage; calibration per confidence level. Each needs **≥ 30** labels, or
    it reports `insufficient_labelled_data` with no score.
  * False positives and false negatives are listed per item with reasons.
  * Market-outcome checks are `not_evaluable`: no KSE-100 benchmark is stored, and a later price move alone
    proves nothing.
* **Readiness** (`engines/intel_pipeline.py`):
  * `run_all()` runs every stage under a single-writer lease (`collector_runs`, job `intelligence`, claim
    token read back; abandoned leases are recovered). Failures are recorded as `failed`.
  * `readiness()` reports backlogs, unclassified events, stale assessments, the review backlog, the last run
    and its errors, and the single-writer state.
  * Activation runbook: `docs/INTELLIGENCE_ACTIVATION.md`.
