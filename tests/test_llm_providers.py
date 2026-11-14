"""Gemini provider and fallback chain: offline, injected transport, no key is ever printed."""

from __future__ import annotations

import json

import pytest

from engines import llm


def _gemini_ok(captured: list):
    def post(url, headers, body, timeout):
        captured.append((url, headers, body))
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"ok": True})}]}}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}}
    return post


def test_gemini_key_goes_in_the_header_never_in_the_url():
    captured: list = []
    provider = llm.GeminiProvider(api_key="gem-test-value", post=_gemini_ok(captured))
    out = provider.complete(system="sys", user="usr", json_schema={}, max_output_tokens=80)
    url, headers, body = captured[0]
    assert "gem-test-value" not in url and "key=" not in url
    assert headers["x-goog-api-key"] == "gem-test-value"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0
    assert out.input_tokens == 7 and out.output_tokens == 3


def test_gemini_without_a_key_makes_no_call():
    captured: list = []
    with pytest.raises(llm.ProviderNotConnected):
        llm.GeminiProvider(api_key="", post=_gemini_ok(captured)).complete(
            system="s", user="u", json_schema={}, max_output_tokens=10)
    assert captured == []


def test_fallback_moves_to_gemini_when_groq_is_rate_limited():
    def groq_limited(url, headers, body, timeout):
        raise llm.TransientProviderError("groq HTTP 429")

    chain = llm.FallbackProvider([
        llm.GroqProvider(api_key="g", post=groq_limited),
        llm.GeminiProvider(api_key="m", post=_gemini_ok([])),
    ])
    out = chain.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert chain.last_used == "gemini" and json.loads(out.text) == {"ok": True}


def test_fallback_with_nothing_connected_reports_both_reasons():
    chain = llm.FallbackProvider([llm.GroqProvider(api_key=""), llm.GeminiProvider(api_key="")])
    with pytest.raises(llm.TransientProviderError, match="groq.*gemini"):
        chain.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


def test_selection_builds_the_chain_in_order_and_needs_no_claude():
    chosen = llm.provider_from_env({llm.GROQ_KEY_VAR: "a", llm.GEMINI_KEY_VAR: "b"})
    assert isinstance(chosen, llm.FallbackProvider)
    assert [p.name for p in chosen._providers] == ["groq", "gemini"]
    assert isinstance(llm.provider_from_env({llm.GEMINI_KEY_VAR: "b"}), llm.GeminiProvider)
    assert isinstance(llm.provider_from_env({}), llm.ClaudeProvider)
