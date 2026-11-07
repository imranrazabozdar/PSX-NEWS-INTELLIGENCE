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
