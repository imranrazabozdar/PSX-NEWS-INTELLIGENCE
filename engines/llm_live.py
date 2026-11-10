"""Live OpenAI-compatible providers for the LLM gateway, with ordered fallback and free-tier quotas.

Ported under the owner-approved scoped exception in ADR-0001 (2026-11-09). Design rules:
* Every provider ships disabled. A provider is used only when `enabled` is true, `terms_reviewed_utc`
  is set by the owner and `model_verified` is true, and its key is present in the environment.
* Keys come only from environment variables named PSXNI_*_API_KEY. The config holds names, never values,
  and any secret-looking value in it is refused at load time.
* Keys are redacted from every error message.
* Quotas (calls and tokens per day) are read from the llm_calls ledger, so they survive restarts.
* Only the standard library is used for HTTP, so no new dependency is introduced.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engines.llm import Completion, LLMError, ProviderNotConnected, TransientProviderError

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "llm_providers.json"
REQUIRED = ("name", "base_url", "api_key_env", "model", "enabled", "max_calls_per_day", "max_tokens_per_day")
_ENV_NAME = re.compile(r"^PSXNI_[A-Z0-9_]*API_KEY$")
_SECRET_KEY = re.compile(r"(^|_)(secret|token|password|api_?key)$", re.I)  # whole name endings only
_SECRET_VALUE = re.compile(r"(gsk_|sk-|AIza|xox[bp]-)[A-Za-z0-9_\-]{10,}")
_TRANSIENT_STATUS = {429, 502, 503, 504}

Opener = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], str]]


class ConfigError(ValueError):
    """The provider configuration is invalid or contains a secret."""


def _scan(obj: Any, path: str = "$") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _SECRET_KEY.search(key) and key != "api_key_env":
                raise ConfigError(f"{path}.{key}: secret-like key; keep keys in the environment")
            _scan(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _scan(value, f"{path}[{i}]")
    elif isinstance(obj, str) and _SECRET_VALUE.search(obj):
        raise ConfigError(f"{path}: looks like a secret value; keep keys in the environment")


def load_config(path: Path | str = CONFIG_PATH) -> list[dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    _scan(raw)
    providers = raw.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ConfigError("providers must be a non-empty list")
    for p in providers:
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            raise ConfigError(f"{p.get('name', '?')}: missing {missing}")
        if not str(p["base_url"]).startswith("https://"):
            raise ConfigError(f"{p['name']}: base_url must be https")
        if not _ENV_NAME.match(p["api_key_env"]):
            raise ConfigError(f"{p['name']}: api_key_env must look like PSXNI_<NAME>_API_KEY")
    return providers


def usable(p: dict[str, Any], environ: Any = None) -> bool:
    """True only when the owner has enabled the provider, recorded the terms review and verified the model,
    and the key is present. Missing any one of these means the provider is never called."""
    env = os.environ if environ is None else environ
    return bool(p.get("enabled") and p.get("terms_reviewed_utc") and p.get("model_verified")
                and env.get(p["api_key_env"]))


def _redact(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    return text


def _default_opener(req: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only, checked at load
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TransientProviderError(f"network error: {type(exc).__name__}") from exc


class OpenAICompatProvider:
    """Any OpenAI-compatible chat-completions endpoint. Implements the gateway's Provider protocol."""

    def __init__(self, name: str, base_url: str, model: str, api_key_env: str, *,
                 max_output_tokens: int = 800,
                 timeout_s: float = 60, json_mode: bool = False, extra_headers: dict[str, str] | None = None,
                 extra_body: dict[str, Any] | None = None, opener: Opener | None = None,
                 environ: Any = None) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.json_mode = json_mode
        self.extra_headers = dict(extra_headers or {})
        self.extra_body = dict(extra_body or {})
        self._opener: Opener = opener or _default_opener
        self._environ = environ

    def _key(self) -> str:
        env = os.environ if self._environ is None else self._environ
        return env.get(self.api_key_env, "")

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        key = self._key()
        if not key:
            raise ProviderNotConnected(f"{self.api_key_env} is not set")
        body: dict[str, Any] = {
            "model": self.model, "temperature": 0,
            "max_tokens": min(max_output_tokens, self.max_output_tokens),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": "DOCUMENT (untrusted data):\n<<<\n" + user + "\n>>>"}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        for k, v in self.extra_body.items():
            body.setdefault(k, v)
        req = urllib.request.Request(  # noqa: S310 - base_url is https (checked at load)
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     **self.extra_headers})
        status, headers, text = self._opener(req, self.timeout_s)
        if status in (401, 403):
            raise ProviderNotConnected(f"HTTP {status}: key rejected or no access")
        if status in _TRANSIENT_STATUS:
            raise TransientProviderError(f"HTTP {status}: rate limited or upstream unavailable")
        if status >= 400:
            raise LLMError(_redact(f"HTTP {status} {text[:200]}", key).replace("\n", " "))
        try:
            payload = json.loads(text)
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected response shape") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("empty completion")
        usage = payload.get("usage") or {}
        return Completion(content, str(payload.get("model") or self.model),
                          int(usage.get("prompt_tokens") or (len(user) + len(system)) // 4),
                          int(usage.get("completion_tokens") or len(content) // 4))


@dataclass
class _Cooldown:
    until: float = 0.0


class FallbackChain:
    """Ordered providers. A transient failure cools that provider down and the next one is tried. A missing or
    rejected key skips it. Other errors are raised at once and recorded by the gateway."""

    def __init__(self, providers: list[Any], *, cooldown_s: float = 60.0,
                 now: Callable[[], float] = time.monotonic) -> None:
        if not providers:
            raise ValueError("FallbackChain needs at least one provider")
        self._providers = providers
        self._cooldown_s = cooldown_s
        self._now = now
        self._cool: dict[str, _Cooldown] = {}
        self._last: Any = providers[0]

    @property
    def name(self) -> str:
        return self._last.name

    @property
    def model(self) -> str:
        return self._last.model

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Completion:
        last_transient: str | None = None
        last_skip: str | None = None
        for provider in self._providers:
            cool = self._cool.get(provider.name, _Cooldown())
            if self._now() < cool.until:
                last_skip = f"{provider.name} cooling down"
                continue
            try:
                result = provider.complete(system=system, user=user, json_schema=json_schema,
                                           max_output_tokens=max_output_tokens)
            except TransientProviderError as exc:
                self._cool[provider.name] = _Cooldown(self._now() + self._cooldown_s)
                last_transient = f"{provider.name}: {exc}"
                continue
            except ProviderNotConnected as exc:
                last_skip = f"{provider.name}: {exc}"
                continue
            self._last = provider
            return result
        if last_transient:
            raise TransientProviderError(last_transient)
        raise ProviderNotConnected(last_skip or "no provider is enabled and connected")


def _today_usage(db: Any, provider: str) -> tuple[int, int]:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    rows = db.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens "
                      "FROM llm_calls WHERE provider = ? AND called_at_utc >= ?", (provider, day))
    return int(rows[0]["calls"]), int(rows[0]["tokens"])


def build_chain(config: list[dict[str, Any]] | None = None, *, db: Any = None, opener: Opener | None = None,
                environ: Any = None, now: Callable[[], float] = time.monotonic) -> FallbackChain | None:
    """Usable providers in config order, skipping any whose daily call or token quota is spent.
    Returns None when nothing is usable, so the caller can refuse cleanly."""
    providers: list[OpenAICompatProvider] = []
    for p in (load_config() if config is None else config):
        if not usable(p, environ):
            continue
        if db is not None:
            calls, tokens = _today_usage(db, p["name"])
            if calls >= int(p["max_calls_per_day"]) or tokens >= int(p["max_tokens_per_day"]):
                continue
        providers.append(OpenAICompatProvider(
            p["name"], p["base_url"], p["model"], p["api_key_env"],
            max_output_tokens=int(p.get("max_output_tokens", 800)), timeout_s=float(p.get("timeout_s", 60)),
            json_mode=bool(p.get("json_mode", False)), extra_headers=p.get("extra_headers"),
            extra_body=p.get("extra_body"), opener=opener, environ=environ))
    return FallbackChain(providers, now=now) if providers else None
