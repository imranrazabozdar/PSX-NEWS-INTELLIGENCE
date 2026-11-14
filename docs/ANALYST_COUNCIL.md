# The analyst council

Three specialist lenses read the same event, then the system compares them.

## Why three

A single model answers confidently and moves on. An oil-price rise reads as good news for a producer,
and a model asked once will say so. The macro lens may see a widening deficit, rupee pressure and higher
rates; the financial lens may see that the producer's gains sit in receivables that do not convert to
cash. **The council exists to surface that disagreement rather than accept the first answer.**

| Lens | Reads | Sees evidence of kind |
|---|---|---|
| News and event | the item itself: who, when, on whose authority | `news`, `announcement` |
| Financial and fundamental | the company's own filed accounts | `figure`, `ratio`, `note`, `kam` |
| Macro, economic and sector | policy, prices, currency, and the chain to connected sectors | `macro`, `commodity`, `policy`, `sector_rule` |

Each lens is shown only its own evidence, so a disagreement is a real difference of view and not an
artefact of one lens having seen more.

## The models do not own the facts

The data engine owns the facts. Statement figures come from extracted and reconciled reports. Ratios are
computed in Python (`engines/ratios.py`). News comes from permitted sources and official announcements.
Prices come from the separate technical system. **No model supplies a number.**

The system builds an evidence pack in Python and hands it over. Enforced in `_clean_assessments`:

- an assessment naming a company that is not in the pack is dropped;
- an assessment citing no evidence id from the pack is dropped;
- a direction outside `benefit | suffer | neutral | unclear` is dropped, never guessed at.

What a model is for: interpreting evidence, identifying relationships, explaining implications, and
challenging a conclusion another lens reached.

## Conflict detection is deterministic

`detect_conflicts` is plain Python. No model is asked whether a conflict exists, because a model that
overlooked one would hide exactly the case this design is built for. A conflict is one company that one
lens calls a benefit and another calls a loss. A neutral or unclear view never creates a conflict.

The orchestrator LLM only *explains* a comparison the system already made. It cannot overturn it: the
narrative's own `benefit` and `suffer` fields are discarded before the verdict is assembled. When no
model is reachable at all, the verdict is still produced from whichever lenses did answer.

## Provenance

Every finding carries its role, provider, model, prompt id, prompt version and UTC timestamp. Every
assessment carries the evidence ids it rests on and its own confidence.

## Free-tier accounts

Three Groq accounts, one Gemini, one OpenRouter, all free tier. Each lens *prefers its own Groq account*
(`provider_for_role`), so one quota does not carry the whole council, and a lens whose account is
exhausted still gets an answer from another account or vendor. With no key at all the gateway reports
`not_connected` and makes no call — nothing in this system depends on Claude.

## Running it

Manual, from the Actions tab ("Analyst council"), or:

```
python -m scripts.council_run --event "Oil prices rose sharply." --companies OGDC,PSO
```

Dry run by default: it prints the verdict as JSON and writes nothing. `--store` keeps it in
`council_verdict` in psx-library — one small JSON row per deliberation, never documents.

## What it does not do

No buy, sell or hold instruction. No target price. No scenario presented as a forecast. Financial
strength comes only from computed ratios.

## Free-tier quota: tracked, not assumed

Earlier, nothing stopped a run from exhausting a free account's daily allowance. The retry logic only
reacted to a 429 *after* wasting a call, and the cost-based daily budget never engages for a free
provider, since its price is $0. `engines/llm_quota.py` fixes this: our own record of calls attempted,
per vendor and per account, checked **before** a call is made.

**What is verified vs. assumed**, as of November 2026:

| Vendor | Reported limit | How solid |
|---|---|---|
| Groq | ~30 req/min, ~1,000 req/day, **per organization** | Third-party, consistent across sources. Adding a key under the *same* Groq account adds no capacity — only a separate signup does. |
| Gemini | 5–20 req/min, 100–1,500 req/day depending on source and date | Google publishes nothing authoritative; limits have been cut more than once in 2026. The default here (10 rpm / 150 rpd) is a conservative guess, not a confirmed number. |
| OpenRouter | 20 req/min, 50 req/day (1,000/day with $10+ lifetime credit ever added) | Vendor-documented, and checkable live: `GET /api/v1/key` returns the account's actual remaining count. `scripts/llm_quota_status.py` calls it. |

Override any default with `PSXNI_LLM_<VENDOR>_RPM` / `PSXNI_LLM_<VENDOR>_RPD` (`0` means explicitly
unlimited). Confirm the real number in each vendor's own dashboard — these move.

**How it is wired in.** `council.provider_for_role(role, environ, db=...)` wraps every leaf provider
with `QuotaGuardedProvider` when a database is supplied. `scripts/council_run.py` always supplies the
open psx-library connection, so a live council run is quota-aware by default. The wrapping reuses
`RotatingProvider`'s and `FallbackProvider`'s existing skip-on-`TransientProviderError` logic — an
exhausted account is just one more thing they already know how to skip past, with no new control flow.

**Check it**: `python -m scripts.llm_quota_status`, or the "LLM quota status" workflow.
