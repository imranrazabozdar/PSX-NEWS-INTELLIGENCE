# Company exposure mapping (Phase 4)

How a stored, verified event becomes evidence-backed exposure candidates for PSX-listed companies.
Code: `engines/entity_resolution.py`, `engines/exposure_taxonomy.py`, `engines/exposure_rules.py`
and `engines/exposure_mapping.py`. Schema: migration `0008_exposure_mapping.sql`.
Decision record: ADR-0007.

**Important:** no source is ACTIVE, and no company-specific evidence source (annual reports, company
websites, filings) has been approved. Every real-world mapping this engine produces today is
therefore a **candidate with evidence status `unverified`**. Statuses above `unverified` appear only in
tests that use synthetic fixtures, which are flagged `is_synthetic = 1`.

## 1. Entity resolution
| Step | Evidence | Result |
|---|---|---|
| 1 | PSX ticker written in capitals (`LUCK`), point-in-time via `company_identifiers` | resolved (0.97) |
| 2 | Exact alias valid at the event date: legal name (verified 0.95), short name (derived 0.80), former name (−0.10, always reviewed) | resolved |
| 3 | Mention that is only part of one or more names (for example "Engro") | **ambiguous**: candidates listed, none chosen |
| — | Nothing matches | **unresolved** |

Rules:
- Lower-case words never match tickers ("good luck" is not LUCK).
- A company is never created from a mention, and a symbol is never invented.
- **Delisted companies:** resolve as `historical` only for events dated before delisting. Later events
  are unresolved, with the recorded successor listed (FFBL → FFC) but never applied automatically.
- **Review:** matches below 0.85 confidence, and all former-name matches, need review.
- **Subsidiaries, associates and holding companies:** these live in `company_relationships`, with type,
  ownership, effective dates, evidence status, source and synthetic flag. A relationship can't be
  `confirmed` or `strongly_supported` without a cited source item and excerpt, and a company can't be
  its own subsidiary.

## 2. Exposure taxonomy
There are six categories, each with defined subtypes (`engines/exposure_taxonomy.py::TAXONOMY`):

- **operational:** production facilities, raw material procurement, imported inputs, export markets,
  supply chain, distribution, energy consumption, logistics.
- **financial:** FX debt, imported machinery, FX revenue, interest-rate sensitivity, working capital,
  borrowing costs, commodity-linked costs, government receivables.
- **regulatory:** government notification, taxes and duties, subsidies, tariffs, price controls,
  regulator decisions (OGRA, NEPRA, SBP, SECP), trade restrictions, environmental and industrial rules.
- **macroeconomic:** PKR exchange rate, inflation, interest rates, oil and gas prices, LNG and LPG prices,
  electricity tariffs, fiscal policy, IMF programme, government spending, demand growth.
- **geopolitical:** regional conflict, border closure, shipping disruption, sanctions, external trade
  restrictions, maritime risk, insurance and freight, international supply disruption.
- **sector:** sector development, competitor development, substitution, market share, industry capacity,
  demand shift.

**Levels:** `direct` or `indirect`.

**Directions** use the existing `event_companies.impact_direction` values. The owner's labels map
through `DIRECTION_LOOKUP`:

| Owner label | Stored value |
|---|---|
| POSITIVE | positive |
| NEGATIVE | negative |
| MIXED | mixed |
| UNCERTAIN | **unknown** |
| NEUTRAL | neutral |

`neutral` means the evidence says there is no material effect. `unknown` means the evidence can't
establish a direction.

## 3. Rules (`exposure-rules/1.0.0`)
| Rule | Driver | Company-specific links (sign of the effect when the driver rises) | Sector-level fallback |
|---|---|---|---|
| R-OIL-1 | crude oil price | buys crude: −; sells crude: +; consumes fuel: − (indirect) | refinery, OMC, E&P sectors |
| R-RATE-1 | policy rate | floating-rate borrowings: −; bank lending and deposits: **not signed** | commercial banks |
| R-PKR-1 | PKR depreciation | foreign-currency revenue: +; imported inputs: −; FX debt: − | none |
| R-GAS-1 | gas price | gas as feedstock or fuel: −; gas producer: + | fertiliser, power |
| R-DUTY-1 | tax, duty or tariff | only where the company's documented product or input appears in the event text | none |
| R-REL-1 | relationship | maps a parent indirectly through a documented subsidiary or associate | — |

**How a rule reaches a company:**
- Company-specific links act only on that company's own rows in `company_exposures`.
- Sector membership alone gives an **indirect, unknown-direction, unverified** candidate, with
  "sector membership alone is not proof" recorded as missing evidence.
- No rule says every OMC, exporter, bank or subsidy recipient is affected the same way.
- If the event text doesn't state which way the driver moved, the direction is `unknown`.
- A company with both negative and positive documented links under one rule is flagged as
  contradictory.

## 4. Evidence status (deterministic, never taken from model confidence)
| Status | Requirement |
|---|---|
| confirmed | strongly supported **and** accepted by a human reviewer (`review(... "accept")`) |
| strongly_supported | company-specific evidence, all cited sources ACTIVE with approved terms, event `corroborated` or `primary_confirmed`, no contradiction, any relationship confirmed or strongly supported, rule origin |
| potential | approved company-specific evidence, but the event is single-source, unverified or disputed, or there is a contradiction or an unverified relationship. LLM suggestions are capped here. |
| unverified | no company-specific evidence, or only evidence from sources that aren't approved |
| rejected | failed validation (LLM), or rejected by a reviewer |

**Database guarantees:**
- `strongly_supported` and `confirmed` require non-empty company evidence.
- `confirmed` requires `review_status = 'accepted'`.
- Accepting anything weaker than strongly supported is refused in code.

**Confidence:**
- It is a 0–1 explanation aid. The base depends on the evidence basis (approved company evidence 0.75,
  unapproved 0.45, named in event 0.5, relationship 0.4, sector only 0.2, LLM 0.3).
- The base is scaled by event confidence and entity-match confidence, reduced for unverified
  relationships and contradictions, and explained in every candidate.
- **Confidence is not proof.**

**Human review is required for:**
- ambiguous or former-name identities;
- unverified subsidiaries;
- high-magnitude events from a single or unverified source;
- contradictory exposure evidence;
- rumours and disputed events;
- direct mappings without approved evidence;
- every LLM suggestion;
- every unverified candidate.

## 5. LLM assistance (optional, same Phase 3 gateway)
- `suggest_with_llm` uses `LLMGateway`, which applies the kill switch, cost and token limits, cache
  and ledger. It uses prompt `exposure_candidate_v1` and a strict JSON schema.
- **Validation:** every suggestion must resolve to a company, use a valid category, subtype, level and
  direction, and quote text found verbatim in stored event or company evidence.
- **Failures:** a failed suggestion is rejected. When the company resolves, an audit row is kept with
  `evidence_status = rejected`.
- **Status:** valid suggestions are stored with model and prompt version, capped at `potential`, and
  always need review.
- **No live LLM is connected:** with the Claude provider not connected, the call returns `not_connected`
  and produces nothing.

## 6. Persistence, integrity and audit (database-enforced)
Migration 0008 was revised before merge after the owner's database-integrity review. It had only ever
run on throwaway local and CI databases; production is still at 0005.

| Guarantee | Mechanism |
|---|---|
| Every candidate has revision 1 | an `AFTER INSERT` trigger writes it in the same statement; inserts must start at revision 1 |
| Every change is a new revision | updates must set `current_revision = old + 1` and carry `change_reason` and `changed_by`; an `AFTER UPDATE` trigger writes the revision |
| Revisions can't be forged or edited | a hand-inserted revision is refused unless it is the candidate's current one (which already exists); no update or delete |
| Identity is fixed | event, company, category, subtype, mechanism, origin, ruleset version, synthetic flag and creation time can't change |
| Evidence is real | `exposure_candidate_evidence` links use foreign keys to `event_evidence`, `company_exposures` or `company_relationships` (exactly one per row) plus the source item. Triggers check that the evidence belongs to the candidate's event, or to its company as owner or parent, and matches the source item. Links are append-only. |
| No status shortcut | candidates are inserted only as `unverified` or `rejected`. Moving to `potential` or higher needs at least one company-specific link, and every company-specific source must be ACTIVE with approved terms. `strongly_supported` also needs a corroborated or primary-confirmed event. |
| Human acceptance is real | `confirmed` is reachable only from `strongly_supported`, with `last_review_id` pointing to an `accept` review of this candidate. CHECK: confirmed ⇔ accepted. |
| Reviews are valid and immutable | reviewer (2 or more characters), notes and a UTC timestamp are required. The review records the candidate's actual status at the time, and only a strongly supported candidate can be accepted. No update or delete. |
| Decisions stick | an accepted or rejected candidate can only change through a new review; re-runs skip it |
| Synthetic data stays synthetic | `sources.is_synthetic` (additive column). Synthetic evidence can't be linked to a non-synthetic candidate or relationship. |
| `event_companies` can't be shortcut | an accepted link there requires a confirmed candidate |
| Atomicity | candidate, links and status assessment are written in one batch; a failure rolls back everything |
| Relationships keep history | `company_relationships` is append-only. Corrections are new rows with `supersedes_relationship_id` (each row superseded at most once, same parent and child). `current_company_relationships` shows the latest row. Rejected rows stay traceable. Self-links and direct A↔B cycles are refused by the database; deeper cycles are refused by `record_relationship`. |

Other behaviour:
- Re-running the same event is idempotent.
- Accepted, confirmed candidates are written to `event_companies` for Phase 5.
- No impact size, percentage or share-price effect is estimated. That is Phase 5.

## 7. Limitations
1. No approved company-specific evidence source exists yet, so real mappings stay unverified (see
   `docs/SOURCE_REVIEW_PROPOSAL_COMPANY_REPORTS.md`).
2. `company_exposures`, `company_segments` and `company_relationships` hold no real rows. They are
   populated only from approved sources after review.
3. The company master's business summaries come from PSX profile pages (licensing question D4) and
   are deliberately **not** used as exposure evidence.
4. There are five rules. Coverage of the full taxonomy (geopolitical, LPG, electricity tariffs,
   sector competition) needs more rules plus calibration on reviewed real events.
5. Entity resolution doesn't use fuzzy or spelling matching on purpose. Misspellings stay unresolved
   until a reviewed `misspelling` alias is added.
6. Ambiguous and unresolved mentions are returned in `MappingResult.unresolved_mentions` but not
   stored, because there is no company to attach them to.
7. Cycles deeper than a direct A↔B reversal are checked in application code, not in a trigger. A
   recursive CTE inside a trigger works on local SQLite 3.53, but it is unverified on Turso (SQLite 3.47).
8. Evidence links are append-only. If documented evidence stops being valid, the old link stays, and
   the status is re-assessed and downgraded on the next run. The database re-checks source approval
   whenever the status is `potential` or above.
9. The triggers are tested on SQLite only. Migration 0008 has not been run against Turso, deliberately:
   no production change.
