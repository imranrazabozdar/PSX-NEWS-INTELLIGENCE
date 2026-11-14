"""Report free-tier LLM usage: our own tracked counts, and OpenRouter's own live number.

Our tracked counts (engines/llm_quota.QuotaTracker) are what WE have attempted against each account,
read from psx-library when it is reachable. They are accurate for our own usage, but the configured
limits they are compared against are placeholders for Groq and Gemini, since neither vendor publishes
a reliable free-tier number; confirm them in each vendor's dashboard.

OpenRouter is the one vendor with a documented, checkable endpoint: GET /api/v1/key returns the
account's own view of its free-model daily allowance. That number is authoritative and is always
printed when a key is set, independent of anything we have tracked ourselves.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from engines import llm, llm_quota

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


def _get(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - fixed https URL
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def openrouter_live_status(key: str, *, get: Any = None) -> dict[str, Any] | None:
    """The vendor's own remaining count for this key, straight from its API. None when unreadable."""
    get = get or _get
    try:
        data = get(OPENROUTER_KEY_URL, {"Authorization": f"Bearer {key}"})
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
        return None
    free = inner.get("free_model_daily_requests") or inner.get("rate_limit")
    return free if isinstance(free, dict) else None


def report(environ: dict[str, str] | None = None, db: Any = None) -> int:
    env = os.environ if environ is None else environ
    tracker = llm_quota.QuotaTracker(db)
    for cls in (llm.GroqProvider, llm.GeminiProvider, llm.OpenRouterProvider):
        keys = llm.keys_from_env(cls.key_var, env)
        if not keys:
            print(f"\n== {cls.name}: no key set")
            continue
        limits = llm_quota.limits_for(cls.name, env)
        note = "" if cls.name == "openrouter" else " (placeholder, not vendor-confirmed)"
        print(f"\n== {cls.name}: limits rpm={limits.requests_per_minute} rpd={limits.requests_per_day}"
              f"{note}")
        for position, key in enumerate(keys, start=1):
            minute = tracker.calls_since(cls.name, position, llm_quota.MINUTE_SECONDS)
            day = tracker.calls_since(cls.name, position, llm_quota.DAY_SECONDS)
            ok, reason = tracker.available(cls.name, position, limits)
            state = "OK" if ok else f"AT LIMIT ({reason})"
            print(f"   #{position}: tracked {day} call(s) today, {minute} in the last minute -- {state}")
            if cls.name == "openrouter":
                live = openrouter_live_status(key)
                print(f"        vendor's own count: {live if live is not None else 'could not be read'}")
    return 0


def main() -> int:
    try:
        from engines import library_db

        conn = library_db.get_library_connection()
        print(f"library host: {conn.host}", file=sys.stderr)
        return report(db=conn.db)
    except Exception as exc:  # noqa: BLE001 - a missing library connection must not block the report
        print(f"(no psx-library connection: {exc}; showing this process's own tracking only)",
              file=sys.stderr)
        return report()


if __name__ == "__main__":
    sys.exit(main())
