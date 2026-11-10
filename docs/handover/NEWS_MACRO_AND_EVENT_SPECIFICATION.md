# News, macro and event specification

Last verified: 2026-11-10.

## 1. Source policy (binding)
- Only sources with a verified permission may be collected. Current source register: 75 rows, 11 `verified_permitted`, 50 `unverified`, 6 `restricted`, 5 `blocked`, 3 `licence_required` [SRC `database/seed/sources.json`, counted 2026-11-10].
- All `verified_permitted` sources are `metadata_only`. Only headlines and metadata may be stored. No full text is fetched or sent to a model.
- Robots rules are respected. CAPTCHAs, WAFs, logins and paywalls are not bypassed. No free-tier account rotation. No quota circumvention.
- Restricted sources (for example the Investify listing) are stored as metadata only and must not feed any scoring.
- Owner permission overrides exist in the source permission log. Each override is the owner's risk acceptance, not a legal determination.
- X and YouTube: account lists are recorded; collection is not activated until access, terms and identity checks pass (spec Appendix A). Social content never establishes verified evidence on its own.

## 2. Event lifecycle
Each event carries: type, status stage (rumour, discussion, proposal, consultation, committee recommendation, approval, notification, implementation, amendment, delay, suspension, reversal, confirmed fact, not applicable), event date and precision, publication time and timezone, collection time, source, original URL, affected companies, direction, timing, evidence, confidence with explanation, contradictions, updates, and review status.

Timing rule: news published after market close or on a weekend or holiday must not be treated as affecting the previous trading session. `engines/market_calendar.py` holds the trading calendar.

## 3. Claim types and evidence
Claim types are assigned by Python from source and wording rules, not by the model: verified fact, official statement, news report, analyst interpretation, prediction, personal opinion, rumour, advertisement, model inference, unclear. Weights are in `engines/extraction.py`.

Evidence rules:
- A claim must be backed by a verbatim quote from the source item. The quote is checked against the stored text.
- Model inferences never become evidence.
- Numbers in a claim must appear in the quote.
- Headline-only items are labelled `headline_only`. Findings describe the headline, not the article.

## 4. Company exposure and entity resolution
- Direct: the company is named in the item (ticker, legal name, alias).
- Indirect: a documented relationship (subsidiary, associate, sector or commodity rule). Labelled with its rule and low confidence until verified.
- Unresolved or ambiguous mentions are never assigned to a company.
- Tickers are never invented. A ticker not in the master is refused.
- Sector membership alone is not proof of exposure. It is a hypothesis.
- Current master: 51 company records. Brand, subsidiary and segment rows are not yet populated (PR #66 reports this for the technical branch [REPORTED]).

Implementation: `engines/entity_resolution.py`, `engines/exposure_mapping.py`, `engines/exposure_rules.py`, `engines/exposure_taxonomy.py`, and on branch `feature/evaluation-harness` the direct scanner in `engines/evaluation.py`.

## 5. Relevance and deduplication
- Relevance pre-filter (`engines/relevance_prefilter.py`, `relevance@v2`): deterministic score before any model call, recorded reasons, entity points, keyword groups, ambiguous-ticker rule, context-only rule, foreign-noise penalty, source bonus. Threshold 2. Its tuning history is in the technical PR #64 [REPORTED].
- Exact duplicates are detected by fingerprint. Near-duplicates by shingles and title/entity similarity (`engines/similarity.py`). Reworded duplicates are not reliably detected (known gap, PR #66 [REPORTED]).

## 6. Financial transmission (spec section 9)
Each external change maps to a transmission path, for example: oil price → input cost → gross margin → PAT. Each step names its input, unit, lag and source. A quantified impact requires a sourced sensitivity or company disclosure. Without it, the output is qualitative only and labelled as such. The T1–T9 framework in `engines/impact_intel.py` implements qualitative mechanisms. It must not produce numbers without sourced inputs.

## 7. Macro intelligence
Series registry: `config/macro_series.json` (definitions only). Values must come from sourced official releases and carry vintage dates. Revisions must be stored as new vintages, not overwrite history (migration 0013).

## 8. Monitoring and scheduling (policy)
- Market-hours refresh intervals of 5–15 minutes are acceptable where justified. No constant one-minute polling.
- Turso resource conservation matters. Batch writes. Keep read budgets (`PSXNI_DB_MAX_*`).
- News, fundamentals and macro may run on separate schedules.

## 9. Not implemented
Source-specific collectors for policy, government, commodities, sector indicators, MUFAP, brokers, YouTube, X. Official PSX disclosure monitoring beyond the existing collectors. Event review UI beyond the existing tabs. Automated alerts.
