# ADR-0006: Phase 3 intelligence engine (event extraction and verification)

Status: Proposed (Phase 3, awaiting owner review)
Depends on: Phase 2 (PR #5, merged in 992e4b0).

## Context
Spec §14 Phase 3 requires a strict, structured LLM schema with evidence excerpts, source
confidence, status stages, conflicting claims and model/prompt versioning. Its acceptance test is:
malformed JSON rejected; every claim cites a source item; unknown stays unknown.
The owner directive also requires that the engine never depends on PSX website data, never lets the
LLM invent data, and keeps all calculations in deterministic Python.

## Decision
1. **The LLM interprets text and nothing else.** `prompts/event_extraction_v1.txt` (versioned,
   SHA-256 recorded per call) forbids outside knowledge, invented figures and buy/sell views.
2. **Strict schema** (`engines/schema.py`, `event-extraction/1`). Unknown or missing keys, wrong
   types, values outside the controlled vocabularies and non-ISO dates make the whole output
   invalid. Invalid output is recorded with a review flag and is never repaired or partially stored.
3. **Evidence checks in Python** (`engines/extraction.py`). Every entity, indicator and claim
   must carry a verbatim quote found in the item text. Indicator values must appear in their quote.
   Anything unsupported is removed and listed in the review reasons. Company mentions resolve only
   through the company-master aliases. Ambiguous or unknown companies are flagged and never linked.
4. **Deterministic scoring.** Relevance pre-filter, importance, confidence, near-duplicate
   detection, clustering (`engines/similarity.py`), corroboration and contradiction, credibility
   and timelines (`engines/verification.py`) are pure Python with explanations.
5. **Independence of evidence.** Near-duplicates (shingle Jaccard ≥ 0.80) and items from the same
   owner count as one source. A primary official source gives `primary_confirmed`. Two or more
   independent media give `corroborated`. Any conflict gives `disputed` and a review flag.
6. **Provider-independent gateway** (`engines/llm.py`). It enforces the kill switch, a daily cost
   limit (`PSXNI_LLM_DAILY_COST_USD`, default 1.0), input/output token limits, retries with
   backoff, caching by prompt + model + input hash, and writes every attempt (including refusals)
   to the append-only `llm_calls` ledger.
7. **Claude is the preferred provider but is NOT CONNECTED.** `ClaudeProvider` raises
   `ProviderNotConnected`. Connecting it needs (a) owner approval to add the official `anthropic`
   SDK as a dependency and (b) a `PSXNI_ANTHROPIC_API_KEY` supplied through the environment's
   secret store. No cost is incurred until then.
8. **Persistence** (migration `0007`, additive). `llm_calls` and `event_extractions` are append-only.
   Each extraction stores schema, prompt and model versions, confidence explanation, review reasons
   and a provenance record. The record holds provider, original source, URL, retrieval method,
   publication and retrieval timestamps, timezone, publication-time status, access, licence and
   data status. Events go through the Phase 1 repository, so every change is a new revision.
   `story_clusters` link items that report the same story.
9. **Source gating.** The pipeline processes only items with a permitted excerpt from sources not
   marked restricted, blocked or licence-required. The PSX-sourced company-master records are therefore
   never sent to an LLM.

## Consequences
- The engine is fully testable offline with recorded fixture responses. Those tests prove the
  deterministic logic only. They are not evidence that a live model integration works.
- No live extraction runs until the owner approves the provider, the dependency and a budget.
- Thresholds (0.80, 0.30, 72h, review confidence 0.55) are initial values to calibrate against
  reviewed real items in later phases.
