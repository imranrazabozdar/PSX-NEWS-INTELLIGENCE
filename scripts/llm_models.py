"""List the model ids each free-tier vendor actually offers for our keys. Prints no key.

Model names change and a wrong one answers HTTP 404, so this asks each vendor what it has rather than
trusting a name written months earlier. Read-only: it lists, it never completes a prompt.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

from engines import llm

VENDORS = (
    ("groq", "https://api.groq.com/openai/v1/models", llm.GROQ_KEY_VAR, "bearer"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models", llm.GEMINI_KEY_VAR, "goog"),
    ("openrouter", "https://openrouter.ai/api/v1/models", llm.OPENROUTER_KEY_VAR, "bearer"),
)


def _get(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - fixed https URLs
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URLs
        return json.loads(resp.read().decode("utf-8"))


def ids_from(payload: Any) -> list[str]:
    """Both shapes: OpenAI-style {"data":[{"id":...}]} and Gemini {"models":[{"name":...}]}."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [str(m.get("id", "")) for m in payload["data"] if m.get("id")]
    if isinstance(payload, dict) and isinstance(payload.get("models"), list):
        out = []
        for m in payload["models"]:
            name = str(m.get("name", "")).removeprefix("models/")
            methods = m.get("supportedGenerationMethods") or m.get("supportedActions") or []
            if name and (not methods or "generateContent" in methods):
                out.append(name)
        return out
    return []


def main() -> int:
    for vendor, url, key_var, scheme in VENDORS:
        keys = llm.keys_from_env(key_var)
        if not keys:
            print(f"\n== {vendor}: no key set")
            continue
        headers = ({"Authorization": f"Bearer {keys[0]}"} if scheme == "bearer"
                   else {"x-goog-api-key": keys[0]})
        headers["User-Agent"] = "PSX-NI/1.0 (private research)"
        try:
            ids = sorted(ids_from(_get(url, headers)))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200].replace("\n", " ")
            print(f"\n== {vendor}: listing failed HTTP {exc.code}: {body}")
            continue
        except Exception as exc:  # noqa: BLE001 - one vendor must not stop the others
            print(f"\n== {vendor}: listing failed ({type(exc).__name__})")
            continue
        free = [m for m in ids if ":free" in m]
        print(f"\n== {vendor}: {len(ids)} model(s)")
        for model in (free or ids)[:40]:
            print(f"   {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
