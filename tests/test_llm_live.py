"""Live LLM providers (ported under ADR-0001's owner-approved exception).

Fake HTTP opener only: no network."""

from __future__ import annotations

import json

import pytest

from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import llm_live as live
from engines.llm import (
    LLMError,
    LLMGateway,
    Pricing,
    ProviderNotConnected,
    TransientProviderError,
    load_prompt,
)

KEY = "PSXNI_TEST_KEY_abcdef1234567890"
ENV = {"PSXNI_GROQ_API_KEY": KEY, "PSXNI_GEMINI_API_KEY": KEY, "PSXNI_OPENROUTER_API_KEY": KEY}


def _enabled(name: str, env_name: str) -> dict:
    return {"name": name, "base_url": "https://example.test/v1", "api_key_env": env_name,
            "model": f"{name}-m",
            "model_verified": True, "enabled": True, "terms_reviewed_utc": "2026-11-10",
            "max_calls_per_day": 100, "max_tokens_per_day": 10_000, "json_mode": True}


def _opener(status: int, body: dict | str | None = None, headers: dict | None = None,
            seen: list | None = None):
    def run(req, timeout):
        if seen is not None:
            seen.append((req, json.loads(req.data.decode())))
        text = body if isinstance(body, str) else json.dumps(body or {})
        return status, headers or {}, text
    return run


OK_BODY = {"model": "served-m", "choices": [{"message": {"content": '{"is_relevant": false}'}}],
           "usage": {"prompt_tokens": 11, "completion_tokens": 5}}


# ----- governance: shipped config is inert
def test_shipped_config_is_loaded_and_every_provider_is_disabled():
    providers = live.load_config()
    assert {p["name"] for p in providers} == {"groq", "gemini", "openrouter"}
    for p in providers:
        assert p["enabled"] is False and p["terms_reviewed_utc"] is None and p["model_verified"] is False
        assert live.usable(p, ENV) is False          # even with a key present, it is never used
    assert live.build_chain(environ=ENV) is None      # nothing usable -> the caller refuses cleanly


def test_a_provider_needs_terms_review_and_verified_model_and_key():
    p = _enabled("groq", "PSXNI_GROQ_API_KEY")
    assert live.usable(p, ENV) is True
    assert live.usable({**p, "terms_reviewed_utc": None}, ENV) is False
    assert live.usable({**p, "model_verified": False}, ENV) is False
    assert live.usable(p, {}) is False                # key missing


def test_config_refuses_secret_values_and_non_psxni_key_names(tmp_path):
    bad_value = tmp_path / "v.json"
    bad_value.write_text(json.dumps({"providers": [{**_enabled("groq", "PSXNI_GROQ_API_KEY"),
                                                    "notes": "gsk_abcdefghijklmnop"}]}))
    with pytest.raises(live.ConfigError, match="secret value"):
        live.load_config(bad_value)
    bad_key = tmp_path / "k.json"
    bad_key.write_text(json.dumps({"providers": [{**_enabled("groq", "GROQ_API_KEY")}]}))
    with pytest.raises(live.ConfigError, match="PSXNI_"):
        live.load_config(bad_key)
    bad_field = tmp_path / "f.json"
    bad_field.write_text(json.dumps({"providers": [{"name": "x", "base_url": "https://x"}]}))
    with pytest.raises(live.ConfigError, match="missing"):
        live.load_config(bad_field)


def test_config_refuses_plain_http_endpoints(tmp_path):
    f = tmp_path / "h.json"
    f.write_text(json.dumps({"providers": [{**_enabled("groq", "PSXNI_GROQ_API_KEY"),
                                            "base_url": "http://insecure.test"}]}))
    with pytest.raises(live.ConfigError, match="https"):
        live.load_config(f)


# ----- provider behaviour
def test_successful_completion_is_parsed_and_sends_only_the_untrusted_document_wrapper():
    seen: list = []
    p = live.OpenAICompatProvider("groq", "https://example.test/v1", "groq-m", "PSXNI_GROQ_API_KEY",
                                  opener=_opener(200, OK_BODY, seen=seen), environ=ENV)
    out = p.complete(system="SYS", user="BODY TEXT", json_schema={}, max_output_tokens=500)
    assert out.text == '{"is_relevant": false}' and out.model == "served-m"
    assert (out.input_tokens, out.output_tokens) == (11, 5)
    req, body = seen[0]
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert "DOCUMENT (untrusted data)" in body["messages"][1]["content"]
    assert body["max_tokens"] <= p.max_output_tokens


def test_missing_key_is_not_connected_without_any_request():
    seen: list = []
    p = live.OpenAICompatProvider("groq", "https://example.test/v1", "m", "PSXNI_GROQ_API_KEY",
                                  opener=_opener(200, OK_BODY, seen=seen), environ={})
    with pytest.raises(ProviderNotConnected):
        p.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert seen == []


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_rate_limit_and_overload_are_transient(status):
    p = live.OpenAICompatProvider("groq", "https://example.test/v1", "m", "PSXNI_GROQ_API_KEY",
                                  opener=_opener(status, "busy"), environ=ENV)
    with pytest.raises(TransientProviderError):
        p.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_is_not_connected(status):
    p = live.OpenAICompatProvider("groq", "https://example.test/v1", "m", "PSXNI_GROQ_API_KEY",
                                  opener=_opener(status, "nope"), environ=ENV)
    with pytest.raises(ProviderNotConnected):
        p.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


def test_error_text_never_contains_the_key():
    leaky = f"upstream echoed {KEY} back"
    p = live.OpenAICompatProvider("groq", "https://example.test/v1", "m", "PSXNI_GROQ_API_KEY",
                                  opener=_opener(400, leaky), environ=ENV)
    with pytest.raises(LLMError) as err:
        p.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert KEY not in str(err.value) and "[REDACTED]" in str(err.value)


def test_unexpected_response_shape_and_empty_content_are_errors():
    for body in ({"choices": []}, {"choices": [{"message": {"content": "   "}}]}):
        p = live.OpenAICompatProvider("groq", "https://example.test/v1", "m", "PSXNI_GROQ_API_KEY",
                                      opener=_opener(200, body), environ=ENV)
        with pytest.raises(LLMError):
            p.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


# ----- fallback chain
class _Scripted:
    def __init__(self, name, outcomes):
        self.name, self.model, self._outcomes, self.calls = name, f"{name}-m", list(outcomes), 0

    def complete(self, *, system, user, json_schema, max_output_tokens):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _completion(name):
    from engines.llm import Completion
    return Completion(f"from {name}", f"{name}-m", 1, 1)


def test_transient_failure_falls_back_and_cools_the_failed_provider_down():
    clock = [0.0]
    first = _Scripted("a", [TransientProviderError("429"), TransientProviderError("429")])
    second = _Scripted("b", [_completion("b"), _completion("b"), _completion("b")])
    chain = live.FallbackChain([first, second], cooldown_s=60, now=lambda: clock[0])
    assert chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1).text == "from b"
    assert chain.name == "b"
    chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    assert first.calls == 1                        # skipped while cooling down
    clock[0] = 61
    chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    assert first.calls == 2                        # tried again after the cooldown


def test_not_connected_provider_is_skipped_without_cooldown():
    first = _Scripted("a", [ProviderNotConnected("no key"), ProviderNotConnected("no key")])
    second = _Scripted("b", [_completion("b"), _completion("b")])
    chain = live.FallbackChain([first, second], now=lambda: 0.0)
    chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    assert first.calls == 2                        # retried each time: no cooldown for a missing key


def test_all_transient_raises_transient_and_all_missing_raises_not_connected():
    chain = live.FallbackChain([_Scripted("a", [TransientProviderError("x")]),
                                _Scripted("b", [TransientProviderError("y")])], now=lambda: 0.0)
    with pytest.raises(TransientProviderError):
        chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    chain2 = live.FallbackChain([_Scripted("a", [ProviderNotConnected("x")])], now=lambda: 0.0)
    with pytest.raises(ProviderNotConnected):
        chain2.complete(system="s", user="u", json_schema={}, max_output_tokens=1)


def test_non_transient_error_is_raised_at_once_and_not_retried_on_another_provider():
    first = _Scripted("a", [LLMError("bad request")])
    second = _Scripted("b", [_completion("b")])
    chain = live.FallbackChain([first, second], now=lambda: 0.0)
    with pytest.raises(LLMError):
        chain.complete(system="s", user="u", json_schema={}, max_output_tokens=1)
    assert second.calls == 0


# ----- quotas, from the ledger, and the gateway
@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def _ledger(db, provider, calls, tokens_each):
    insert = ("INSERT INTO llm_calls(called_at_utc, provider, model, prompt_id, prompt_version, "
              "prompt_sha256, input_sha256, input_tokens, output_tokens, cost_usd, attempts, outcome, error) "
              "VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), ?, 'm', 'p', '1', ?, ?, ?, 0, 0, 1, 'ok', NULL)")
    for _ in range(calls):
        db.execute(insert, (provider, "0" * 64, "1" * 64, tokens_each))


def test_daily_call_quota_is_read_from_the_ledger(db):
    cfg = [{**_enabled("groq", "PSXNI_GROQ_API_KEY"), "max_calls_per_day": 2}]
    assert live.build_chain(cfg, db=db, environ=ENV) is not None
    _ledger(db, "groq", 2, 1)
    assert live.build_chain(cfg, db=db, environ=ENV) is None      # quota spent: provider skipped


def test_daily_token_quota_is_read_from_the_ledger(db):
    cfg = [{**_enabled("groq", "PSXNI_GROQ_API_KEY"), "max_tokens_per_day": 100}]
    _ledger(db, "groq", 1, 150)
    assert live.build_chain(cfg, db=db, environ=ENV) is None


def test_gateway_uses_the_chain_and_the_kill_switch_still_wins(monkeypatch, db):
    cfg = [_enabled("groq", "PSXNI_GROQ_API_KEY")]
    seen: list = []
    chain = live.build_chain(cfg, db=db, environ=ENV, opener=_opener(200, OK_BODY, seen=seen))
    gw = LLMGateway(provider=chain, pricing=Pricing(0.0, 0.0), db=db, sleep=lambda s: None)
    result = gw.complete(load_prompt("event_extraction_v1"), "ITEM TEXT", {})
    assert result.outcome == "ok" and result.model == "served-m"
    assert len(seen) == 1
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "1")
    gw2 = LLMGateway(provider=chain, pricing=Pricing(0.0, 0.0), db=db, sleep=lambda s: None)
    blocked = gw2.complete(load_prompt("event_extraction_v1"), "OTHER TEXT", {})
    assert blocked.outcome == "refused_kill_switch" and len(seen) == 1   # no call made
