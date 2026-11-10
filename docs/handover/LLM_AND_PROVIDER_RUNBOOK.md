# LLM and provider runbook

Last verified: 2026-11-10. No provider was called during this package. Model availability is therefore [UNKNOWN] today.

## 1. Role of the model
The model is an assistant to deterministic analysis, never the source of truth. It may propose a structured extraction. Python assigns claim types, checks quotes against the stored text, parses every number, and decides eligibility. A model output is a candidate, and only a human review can promote it.

## 2. Providers
| Provider | Config (news, branch PR #57) | Model id in config | Free-tier limits in config | Enabled | Notes |
|---|---|---|---|---|---|
| Groq | `config/llm_providers.json` | `openai/gpt-oss-20b` | 100 calls/day, 150,000 tokens/day | no | Id was confirmed by a live call in the technical project [REPORTED] |
| Google Gemini | same | `gemini-3.5-flash-lite` | 100 calls/day, 150,000 tokens/day | no | Listing alone was shown not to prove usability [REPORTED, PR #64] |
| OpenRouter | same | `google/gemma-4-26b-a4b-it:free` | 40 calls/day, 80,000 tokens/day | no | Free routes are third-party served [REPORTED] |
| Anthropic (Claude) | `engines/llm.py` `ClaudeProvider` | — | — | never connected | Refuses. Needs owner approval: SDK, key, budget |

The config is copied as a starting point from the technical project. Every model id, limit and term must be verified for this project before enabling.

## 3. Enablement gate (all must hold) [SRC `engines/llm_live.py` `usable`]
1. `enabled` is true in the config.
2. `terms_reviewed_utc` is set by the owner for this project. The technical project's attestation (dated 2026-11-09) does not transfer.
3. `model_verified` is true, after a real call that the owner accepts.
4. The provider's key is present in the environment under its `PSXNI_*_API_KEY` name.
5. Its daily call and token quotas are not spent (read from the `llm_calls` ledger).
6. `PSXNI_KILL_SWITCH` is not on.

Current state: all three providers fail gate 1, 2 and 3. No live extraction is possible in the news repository.

## 4. Routing and failure handling [SRC `engines/llm_live.py`]
- Ordered fallback in config order. A transient failure (rate limit, overload, network) cools that provider down for 60 s by default and the next provider is tried.
- A missing key or a rejected key (401/403) skips the provider without cooldown.
- Any other error is raised at once. The gateway records it. It is not retried on another provider.
- Keys are redacted from every error message.
- Retry-After and daily limits must be respected. Do not bypass limits by rotating accounts.

## 5. Budgets and logging
- Gateway: `engines/llm.py` `Limits` and `LLMGateway`. Daily cost limit `PSXNI_LLM_DAILY_COST_USD`. Every call is written to `llm_calls` with provider, model, prompt id and version, input hash, tokens, cost, attempts and outcome.
- Content-hash cache: identical inputs with the same prompt and model are not re-sent.
- Kill switch: `PSXNI_KILL_SWITCH` set to 1, true, yes or on stops all calls.

## 6. Eligibility of input text
Only public text from `verified_permitted` sources may be sent. Restricted-source documents (for example PSX filings in the manual vault) must never be sent to any provider. Source metadata for the Investify rows is restricted. Enforcement: the extraction path skips `restricted` and `unavailable` items [SRC `engines/extraction.py`]. Documents must be checked by the owner before any provider sees them.

## 7. Legacy and historical calls
- The technical project made live calls (Groq) on 2026-11-09. 15 `llm_calls` and 15 extraction candidates exist in the news database [REPORTED]. They are legacy, unreviewed, and quarantined at read time by `engines/quarantine.py` on branch PR #59.
- Their cost and token totals are counted in the ledger. Current totals [UNKNOWN].

## 8. Prohibited
- Using the model to produce numbers, tickers or relationships that the Python checks do not support.
- Storing provider keys in the database, the repository, a file or a chat.
- Sending restricted text.
- Live calls in production without the owner's approval and the gate above.
- Treating the provider's terms attestation from another project as valid here.

## 9. Verification steps before enabling a provider (owner or agent with approval)
1. Read the provider's current terms and data-use policy. Record the date and the reviewer's name in the config, only if the owner asks.
2. Confirm the model id on the provider's current model list, and make one small real call with a non-sensitive prompt.
3. Confirm quotas and the free-tier limits.
4. Set `enabled` and `model_verified`. Keep `terms_reviewed_utc` owner-set.
5. Run `python -m pytest tests/test_llm_live.py` and the full suite.
