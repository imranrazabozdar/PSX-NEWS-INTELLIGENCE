"""Live check that the free-tier LLM keys work. Prints provider, model and token counts, never a key.

Runs only where the keys are provided as environment variables (the GitHub Actions secret flow).
"""

from __future__ import annotations

import sys

from engines import llm

PROMPT = llm.Prompt("smoke.ping", "1", 'Reply with the JSON object {"ok": true}.')


def main() -> int:
    providers = []
    if llm.GroqProvider(api_key=None)._key:
        providers.append(llm.GroqProvider())
    if llm.GeminiProvider(api_key=None)._key:
        providers.append(llm.GeminiProvider())
    if not providers:
        print("smoke: no LLM key present in this run (secret not passed to the job)")
        return 1
    failed = 0
    for provider in providers:
        try:
            out = provider.complete(system=PROMPT.text, user="ping", json_schema={}, max_output_tokens=32)
            print(f"smoke: {provider.name} ok model={out.model} "
                  f"in={out.input_tokens} out={out.output_tokens}")
        except llm.LLMError as exc:
            failed += 1
            print(f"smoke: {provider.name} FAILED: {type(exc).__name__}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
