"""Groq provider: offline tests with an injected transport. No network, no key is ever printed."""

from __future__ import annotations

import json

import pytest

from engines import llm


def _prompt() -> llm.Prompt:
    return llm.Prompt("test.macro", "1", "Return JSON.")


def _ok_post(captured: list):
    def post(url, headers, body, timeout):
        captured.append((url, headers, body))
        return {"choices": [{"message": {"content": json.dumps({"ok": True})}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4}}
    return post


def test_without_a_key_groq_reports_not_connected_and_makes_no_call():
    captured: list = []
    provider = llm.GroqProvider(api_key="", post=_ok_post(captured))
    with pytest.raises(llm.ProviderNotConnected):
        provider.complete(system="s", user="u", json_schema={}, max_output_tokens=50)
    assert captured == []


def test_the_request_is_json_mode_deterministic_and_carries_the_key_only_in_the_header():
    captured: list = []
    provider = llm.GroqProvider(api_key="test-key-value", post=_ok_post(captured))
    out = provider.complete(system="sys", user="usr", json_schema={}, max_output_tokens=120)
    url, headers, body = captured[0]
    assert url == llm.GROQ_URL
    assert headers["Authorization"] == "Bearer test-key-value"
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    assert body["max_tokens"] == 120 and "test-key-value" not in json.dumps(body)
    assert out.text == json.dumps({"ok": True}) and out.input_tokens == 10 and out.output_tokens == 4


def test_a_rate_limit_is_transient_and_the_gateway_retries_it():
    calls = {"n": 0}

    def flaky(url, headers, body, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise llm.TransientProviderError("groq HTTP 429")
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    gw = llm.LLMGateway(provider=llm.GroqProvider(api_key="k", post=flaky),
                        pricing=llm.Pricing(0.1, 0.1), sleep=lambda s: None)
    res = gw.complete(_prompt(), "user text", {})
    assert res.outcome == "ok" and calls["n"] == 2


def test_the_gateway_reports_not_connected_cleanly_when_groq_has_no_key():
    gw = llm.LLMGateway(provider=llm.GroqProvider(api_key=""), pricing=llm.Pricing(0.1, 0.1))
    res = gw.complete(_prompt(), "user text", {})
    assert res.outcome == "not_connected" and res.text is None


def test_provider_selection_prefers_groq_and_needs_no_claude():
    assert isinstance(llm.provider_from_env({}), llm.ClaudeProvider)
    chosen = llm.provider_from_env({llm.GROQ_KEY_VAR: "k"})
    assert isinstance(chosen, llm.GroqProvider) and chosen.model == llm.DEFAULT_GROQ_MODEL
