"""Live check of the free-tier LLM keys: one tiny call per key.

Prints vendor, key position, model and token counts. NEVER prints a key or any part of one. Runs only
where the keys are provided as environment variables (the GitHub Actions secret flow).

Exit code 0 when at least one key answered on every vendor that has keys; 1 when a vendor has keys but
none of them answered, or when no key is present at all.
"""

from __future__ import annotations

import sys

from engines import llm

PROMPT = llm.Prompt("smoke.ping", "1",
                    'You are a JSON API. Reply with exactly {"ok": true} and nothing else.')
VENDORS = ((llm.GroqProvider, llm.GROQ_MODEL_VAR), (llm.GeminiProvider, llm.GEMINI_MODEL_VAR),
           (llm.OpenRouterProvider, llm.OPENROUTER_MODEL_VAR))


def check_vendor(cls: type, model_var: str, environ: dict | None = None) -> tuple[int, int]:
    """Return (answered, total) for one vendor. Each key is tried once, independently."""
    import os

    env = os.environ if environ is None else environ
    keys = llm.keys_from_env(cls.key_var, env)
    if not keys:
        print(f"{cls.name}: no key set")
        return (0, 0)
    model = str(env.get(model_var, "") or "").strip() or None
    answered = 0
    for position, key in enumerate(keys, start=1):
        label = f"{cls.name}#{position}"
        try:
            out = cls(api_key=key, model=model).complete(
                system=PROMPT.text, user="ping", json_schema={}, max_output_tokens=32)
        except llm.ProviderNotConnected:
            print(f"{label}: not connected")
        except llm.LLMError as exc:
            print(f"{label}: FAILED ({type(exc).__name__}: {exc})")
        else:
            answered += 1
            print(f"{label}: ok model={out.model} in={out.input_tokens} out={out.output_tokens}")
    return (answered, len(keys))


def main() -> int:
    total_keys = 0
    broken_vendors = []
    for cls, model_var in VENDORS:
        answered, count = check_vendor(cls, model_var)
        total_keys += count
        if count and not answered:
            broken_vendors.append(cls.name)
    if not total_keys:
        print("smoke: no LLM key reached this run (check the secret names and the job's env block)")
        return 1
    if broken_vendors:
        print(f"smoke: these vendors have keys but none answered: {', '.join(broken_vendors)}")
        return 1
    print(f"smoke: every vendor with keys answered ({total_keys} key(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
