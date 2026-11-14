"""Provider-independent LLM adapter with prompt versioning, usage metering and cost controls.

The engine talks to a ``Provider``. Phase 3 ships two:

* ``FixtureProvider`` returns recorded responses keyed by input hash. It is for tests and
  offline runs, and its results are never presented as live model output.
* ``ClaudeProvider`` is the preferred live provider (owner decision C2). It is NOT CONNECTED:
  no API key has been issued and the official ``anthropic`` SDK is not yet an approved
  dependency. Calling it raises ``ProviderNotConnected``. Nothing is ever faked.

``LLMGateway`` wraps any provider. It enforces the kill switch, a daily cost limit, per-call
token limits and retries, caches by (prompt, model, input) hash, and writes every attempt to
the append-only ``llm_calls`` ledger when a database is supplied.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from database.canonical import now_utc

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class LLMError(RuntimeError):
    """Base class for gateway failures."""


class ProviderNotConnected(LLMError):
    """The provider has no approved credentials or dependency yet."""


class BudgetExceeded(LLMError):
    """A cost or token limit would be exceeded."""


class KillSwitchActive(LLMError):
    """PSXNI_KILL_SWITCH is on."""


class TransientProviderError(LLMError):
    """Retryable failure (rate limit, overload, network)."""


@dataclass(frozen=True)
class Prompt:
    prompt_id: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def load_prompt(name: str) -> Prompt:
    """Load a versioned prompt file. The header must state PROMPT_ID and PROMPT_VERSION."""
    raw = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    header, sep, body = raw.partition("\n---\n")
    if not sep:
        raise ValueError(f"prompt {name} has no header separator")
    meta = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
    if not meta.get("PROMPT_ID") or not meta.get("PROMPT_VERSION"):
        raise ValueError(f"prompt {name} must declare PROMPT_ID and PROMPT_VERSION")
    return Prompt(meta["PROMPT_ID"], meta["PROMPT_VERSION"], body.strip())


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str
    model: str

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        ...


@dataclass(frozen=True)
class Pricing:
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000


def input_hash(prompt: Prompt, model: str, user: str) -> str:
    return hashlib.sha256(f"{prompt.sha256}\n{model}\n{user}".encode()).hexdigest()


class FixtureProvider:
    """Offline provider: returns recorded JSON for known inputs, raises for unknown ones."""

    name = "fixture"

    def __init__(self, responses: dict[str, Any], *, model: str = "fixture-model",
                 fail_first: int = 0):
        self.model = model
        self._responses = responses  # key: substring identifying the item, value: payload or raw str
        self._fail_first = fail_first
        self.calls = 0

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        self.calls += 1
        if self.calls <= self._fail_first:
            raise TransientProviderError("simulated overload")
        for key, payload in self._responses.items():
            if key in user:
                text = payload if isinstance(payload, str) else json.dumps(payload)
                return Completion(text, self.model, len(system + user) // 4, len(text) // 4)
        raise LLMError("fixture has no recorded response for this input")


class ClaudeProvider:
    """Preferred live provider. NOT CONNECTED until the owner approves the key and SDK."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5"):
        self.model = model

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        raise ProviderNotConnected(
            "Claude provider is not connected: PSXNI_ANTHROPIC_API_KEY and the official SDK "
            "dependency need owner approval (see docs/adr/0006-intelligence-engine.md)")


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

GROQ_KEY_VAR = "PSXNI_GROQ_API_KEY"  # noqa: S105 - a variable name, not a secret
GEMINI_KEY_VAR = "PSXNI_GEMINI_API_KEY"  # noqa: S105 - a variable name, not a secret
OPENROUTER_KEY_VAR = "PSXNI_OPENROUTER_API_KEY"  # noqa: S105 - a variable name, not a secret
GROQ_MODEL_VAR = "PSXNI_LLM_GROQ_MODEL"
GEMINI_MODEL_VAR = "PSXNI_LLM_GEMINI_MODEL"
OPENROUTER_MODEL_VAR = "PSXNI_LLM_OPENROUTER_MODEL"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3.5-lightning:free"

# Model names are verified against each vendor's own listing (scripts/llm_models.py), not from memory:
# the names written here earlier had been retired and every call answered HTTP 404. Override with the
# PSXNI_LLM_*_MODEL variables when a vendor retires one again.
# A key may be set under the bare name or numbered, so several free-tier accounts can share the load.
KEY_SUFFIXES = ("", "_ONE", "_TWO", "_THREE", "_FOUR", "_FIVE", "_SIX", "_SEVEN", "_EIGHT", "_NINE", "_TEN",
                "_1", "_2", "_3", "_4", "_5", "_6", "_7", "_8", "_9")


def keys_from_env(base: str, environ: Any = None) -> list[str]:
    """Every distinct key set under `base` or `base` plus a number suffix, in declaration order.

    Returns values, so a caller must never log the result. An empty list means the vendor is not connected.
    """
    env = os.environ if environ is None else environ
    found: list[str] = []
    for suffix in KEY_SUFFIXES:
        value = str(env.get(base + suffix, "") or "").strip()
        if value and value not in found:
            found.append(value)
    return found


def _http_post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Real transport. Maps overload, rate-limit and network answers to TransientProviderError."""
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")  # noqa: S310 - https only
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The body says WHICH model or route was rejected. It carries no key, so it is safe to surface.
        try:
            detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ")
        except Exception:  # noqa: BLE001 - diagnosis must never mask the original failure
            detail = ""
        where = f"HTTP {exc.code}" + (f": {detail}" if detail else "")
        if exc.code in (408, 409, 429, 500, 502, 503, 504):
            raise TransientProviderError(where) from exc
        raise LLMError(where) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransientProviderError(f"network error: {type(exc).__name__}") from exc


class _ChatCompletionsProvider:
    """Shared base for OpenAI-compatible chat APIs (Groq, OpenRouter).

    The key is read from the environment only, travels in the Authorization header, and is never logged.
    JSON output is requested and the temperature is fixed at 0, so a given input gives a stable answer.
    """

    name = "chat"
    url = ""
    key_var = ""
    model_var = ""
    default_model = ""

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 post: Any = None, timeout: float = 30.0, extra_headers: dict[str, str] | None = None):
        if api_key is not None:
            self._key = api_key.strip()
        else:
            keys = keys_from_env(self.key_var)
            self._key = keys[0] if keys else ""
        self.model = model or os.environ.get(self.model_var, "").strip() or self.default_model
        self._post = post or _http_post
        self._timeout = timeout
        self._extra_headers = extra_headers or {}

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        if not self._key:
            raise ProviderNotConnected(
                f"{self.name} is not connected: set {self.key_var} through the secret flow")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                   "User-Agent": "PSX-NI/1.0 (private research)", **self._extra_headers}
        data = self._post(self.url, headers, body, self._timeout)
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"{self.name} response has an unexpected shape") from exc
        if not str(text or "").strip():
            raise TransientProviderError(f"{self.name} returned an empty answer")
        return Completion(text, self.model, int(usage.get("prompt_tokens", 0) or 0),
                          int(usage.get("completion_tokens", 0) or 0))


class GroqProvider(_ChatCompletionsProvider):
    """Groq free tier: the fastest provider, preferred for macro and news work."""

    name = "groq"
    url = GROQ_URL
    key_var = GROQ_KEY_VAR
    model_var = GROQ_MODEL_VAR
    default_model = DEFAULT_GROQ_MODEL


class OpenRouterProvider(_ChatCompletionsProvider):
    """OpenRouter free tier: the last resort in the chain."""

    name = "openrouter"
    url = OPENROUTER_URL
    key_var = OPENROUTER_KEY_VAR
    model_var = OPENROUTER_MODEL_VAR
    default_model = DEFAULT_OPENROUTER_MODEL


class GeminiProvider:
    """Gemini API free tier. The key travels in the x-goog-api-key header, never in the URL."""

    name = "gemini"
    key_var = GEMINI_KEY_VAR

    def __init__(self, *, api_key: str | None = None, model: str | None = None,
                 post: Any = None, timeout: float = 30.0):
        if api_key is not None:
            self._key = api_key.strip()
        else:
            keys = keys_from_env(GEMINI_KEY_VAR)
            self._key = keys[0] if keys else ""
        self.model = model or os.environ.get(GEMINI_MODEL_VAR, "").strip() or DEFAULT_GEMINI_MODEL
        self._post = post or _http_post
        self._timeout = timeout

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        if not self._key:
            raise ProviderNotConnected(
                f"gemini is not connected: set {GEMINI_KEY_VAR} through the secret flow")
        url = f"{GEMINI_URL_BASE}/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_output_tokens,
                                 "responseMimeType": "application/json"},
        }
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json",
                   "User-Agent": "PSX-NI/1.0 (private research)"}
        data = self._post(url, headers, body, self._timeout)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            usage = data.get("usageMetadata", {})
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("gemini response has an unexpected shape") from exc
        if not str(text or "").strip():
            raise TransientProviderError("gemini returned an empty answer")
        return Completion(text, self.model, int(usage.get("promptTokenCount", 0) or 0),
                          int(usage.get("candidatesTokenCount", 0) or 0))


class RotatingProvider:
    """Several accounts of ONE vendor, used round robin so no single free-tier quota carries every call.

    Each call starts at the next account and walks the rest, so a rate-limited or unconnected key costs one
    attempt and the call still succeeds. Raises TransientProviderError only when every account refused.
    """

    def __init__(self, providers: list[Any]):
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self.name = providers[0].name
        self.model = providers[0].model
        self.last_used = ""
        self._next = 0

    @property
    def key_count(self) -> int:
        return len(self._providers)

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        total = len(self._providers)
        start = self._next % total
        self._next = (start + 1) % total
        problems: list[str] = []
        for step in range(total):
            index = (start + step) % total
            try:
                out = self._providers[index].complete(system=system, user=user, json_schema=json_schema,
                                                      max_output_tokens=max_output_tokens)
            except (ProviderNotConnected, TransientProviderError) as exc:
                problems.append(f"{self.name}#{index + 1}: {exc}")
                continue
            self.last_used = f"{self.name}#{index + 1}"
            return out
        raise TransientProviderError("; ".join(problems))


class FallbackProvider:
    """Tries each vendor in order. Moves on when one is not connected or is transiently failing."""

    name = "fallback"

    def __init__(self, providers: list[Any]):
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self.model = providers[0].model
        self.last_used = ""

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        problems: list[str] = []
        for provider in self._providers:
            try:
                out = provider.complete(system=system, user=user, json_schema=json_schema,
                                        max_output_tokens=max_output_tokens)
            except (ProviderNotConnected, TransientProviderError) as exc:
                problems.append(f"{provider.name}: {exc}")
                continue
            self.last_used = getattr(provider, "last_used", "") or provider.name
            return out
        raise TransientProviderError("no provider answered: " + "; ".join(problems))


def _vendor(cls: Any, environ: Any, model_var: str) -> Any | None:
    """One vendor, rotating over however many keys it has. None when the vendor has no key."""
    env = os.environ if environ is None else environ
    keys = keys_from_env(cls.key_var, env)
    if not keys:
        return None
    model = str(env.get(model_var, "") or "").strip() or None
    built = [cls(api_key=key, model=model) for key in keys]
    return built[0] if len(built) == 1 else RotatingProvider(built)


def provider_from_env(environ: Any = None) -> Any:
    """Groq first (rotating over its keys), then Gemini, then OpenRouter.

    Nothing depends on Claude: with no free-tier key at all the gateway reports not_connected and makes
    no call. Every vendor accepts numbered keys, so several free accounts share one vendor's load.
    """
    env = os.environ if environ is None else environ
    chain = [
        _vendor(GroqProvider, env, GROQ_MODEL_VAR),
        _vendor(GeminiProvider, env, GEMINI_MODEL_VAR),
        _vendor(OpenRouterProvider, env, OPENROUTER_MODEL_VAR),
    ]
    live = [p for p in chain if p is not None]
    if not live:
        return ClaudeProvider()
    return live[0] if len(live) == 1 else FallbackProvider(live)


@dataclass
class Limits:
    daily_cost_usd: float = 1.0
    max_input_tokens: int = 8_000
    max_output_tokens: int = 2_000
    max_attempts: int = 3
    backoff_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> Limits:
        def num(name: str, default: float) -> float:
            raw = os.environ.get(f"PSXNI_LLM_{name}")
            return float(raw) if raw else default

        return cls(daily_cost_usd=num("DAILY_COST_USD", 1.0),
                   max_input_tokens=int(num("MAX_INPUT_TOKENS", 8_000)),
                   max_output_tokens=int(num("MAX_OUTPUT_TOKENS", 2_000)))


@dataclass
class GatewayResult:
    text: str | None
    outcome: str
    model: str
    call_id: int | None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


@dataclass
class LLMGateway:
    provider: Any
    pricing: Pricing
    limits: Limits = field(default_factory=Limits)
    db: Any = None
    sleep: Any = time.sleep
    _cache: dict[str, GatewayResult] = field(default_factory=dict)
    _spent_today: float = 0.0

    def _kill_switch(self) -> bool:
        return os.environ.get("PSXNI_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}

    def spent_today(self) -> float:
        if self.db is None:
            return self._spent_today
        rows = self.db.execute("SELECT COALESCE(SUM(cost_usd),0) c FROM llm_calls "
                               "WHERE called_at_utc >= ?", (now_utc()[:10],))
        return float(rows[0]["c"])

    def _log(self, prompt: Prompt, ihash: str, res: GatewayResult, attempts: int) -> int | None:
        self._spent_today += res.cost_usd
        if self.db is None:
            return None
        self.db.execute(
            """INSERT INTO llm_calls(called_at_utc, provider, model, prompt_id, prompt_version,
                   prompt_sha256, input_sha256, input_tokens, output_tokens, cost_usd, attempts,
                   outcome, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now_utc(), self.provider.name, res.model, prompt.prompt_id, prompt.version, prompt.sha256,
             ihash, res.input_tokens, res.output_tokens, res.cost_usd, attempts, res.outcome,
             res.error))
        return self.db.execute("SELECT MAX(call_id) id FROM llm_calls")[0]["id"]

    def complete(self, prompt: Prompt, user: str, schema: dict) -> GatewayResult:
        model = self.provider.model
        ihash = input_hash(prompt, model, user)
        if ihash in self._cache:
            cached = self._cache[ihash]
            res = GatewayResult(cached.text, "cached", model, None)
            res.call_id = self._log(prompt, ihash, res, 1)
            return res

        def refuse(outcome: str, msg: str) -> GatewayResult:
            res = GatewayResult(None, outcome, model, None, error=msg)
            res.call_id = self._log(prompt, ihash, res, 1)
            return res

        if self._kill_switch():
            return refuse("refused_kill_switch", "PSXNI_KILL_SWITCH is on")
        est_in = (len(prompt.text) + len(user)) // 4 + 1
        if est_in > self.limits.max_input_tokens:
            return refuse("refused_budget", f"input ~{est_in} tokens exceeds {self.limits.max_input_tokens}")
        worst = self.pricing.cost(est_in, self.limits.max_output_tokens)
        if self.spent_today() + worst > self.limits.daily_cost_usd:
            return refuse("refused_budget", "daily LLM cost limit would be exceeded")

        attempts, last = 0, ""
        while attempts < self.limits.max_attempts:
            attempts += 1
            try:
                c = self.provider.complete(system=prompt.text, user=user, json_schema=schema,
                                           max_output_tokens=self.limits.max_output_tokens)
            except ProviderNotConnected as exc:
                res = GatewayResult(None, "not_connected", model, None, error=str(exc))
                res.call_id = self._log(prompt, ihash, res, attempts)
                return res
            except TransientProviderError as exc:
                last = str(exc)
                if attempts < self.limits.max_attempts:
                    self.sleep(self.limits.backoff_seconds * 2 ** (attempts - 1))
                continue
            except LLMError as exc:
                last = str(exc)
                break
            res = GatewayResult(c.text, "ok", c.model, None, c.input_tokens, c.output_tokens,
                                self.pricing.cost(c.input_tokens, c.output_tokens))
            res.call_id = self._log(prompt, ihash, res, attempts)
            self._cache[ihash] = res
            return res
        res = GatewayResult(None, "error", model, None, error=last)
        res.call_id = self._log(prompt, ihash, res, attempts)
        return res
