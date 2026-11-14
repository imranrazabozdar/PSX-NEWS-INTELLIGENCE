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


# ---------- numbered keys: several free-tier accounts of one vendor share the load

def test_numbered_keys_are_discovered_in_order_and_deduplicated():
    env = {"PSXNI_GROQ_API_KEY_ONE": "a", "PSXNI_GROQ_API_KEY_TWO": "b",
           "PSXNI_GROQ_API_KEY_THREE": "b", "PSXNI_GROQ_API_KEY": "z"}
    assert llm.keys_from_env(llm.GROQ_KEY_VAR, env) == ["z", "a", "b"]
    assert llm.keys_from_env(llm.GROQ_KEY_VAR, {"PSXNI_GROQ_API_KEY_ONE": "   "}) == []


def test_the_owners_key_names_build_a_rotating_groq_then_gemini_then_openrouter_chain():
    env = {"PSXNI_GROQ_API_KEY_ONE": "g1", "PSXNI_GROQ_API_KEY_TWO": "g2",
           "PSXNI_GROQ_API_KEY_THREE": "g3", "PSXNI_GEMINI_API_KEY_ONE": "m1",
           "PSXNI_OPENROUTER_API_KEY_ONE": "o1"}
    chain = llm.provider_from_env(env)
    assert isinstance(chain, llm.FallbackProvider)
    assert [p.name for p in chain._providers] == ["groq", "gemini", "openrouter"]
    assert chain._providers[0].key_count == 3


def test_rotation_spreads_calls_across_accounts_and_skips_an_exhausted_one():
    used: list[str] = []

    def answer(tag: str, fail: bool = False):
        def post(url, headers, body, timeout):
            used.append(tag)
            if fail:
                raise llm.TransientProviderError("HTTP 429")
            return {"choices": [{"message": {"content": "{}"}}], "usage": {}}
        return post

    rot = llm.RotatingProvider([
        llm.GroqProvider(api_key="k1", post=answer("one")),
        llm.GroqProvider(api_key="k2", post=answer("two", fail=True)),
        llm.GroqProvider(api_key="k3", post=answer("three")),
    ])
    for _ in range(3):
        rot.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    # call 1 starts at account one; call 2 starts at two, which is exhausted, so three answers;
    # call 3 starts at three. No single account carried every call.
    assert used == ["one", "two", "three", "three"]
    assert rot.last_used == "groq#3"


def test_a_vendor_whose_every_key_is_rate_limited_falls_through_to_the_next_vendor():
    def limited(url, headers, body, timeout):
        raise llm.TransientProviderError("HTTP 429")

    chain = llm.FallbackProvider([
        llm.RotatingProvider([llm.GroqProvider(api_key="k1", post=limited),
                              llm.GroqProvider(api_key="k2", post=limited)]),
        llm.OpenRouterProvider(api_key="o1", post=lambda u, h, b, t: {
            "choices": [{"message": {"content": '{"ok":true}'}}], "usage": {}}),
    ])
    out = chain.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert chain.last_used == "openrouter" and json.loads(out.text) == {"ok": True}


def test_openrouter_sends_the_key_only_in_the_header():
    captured: list = []

    def post(url, headers, body, timeout):
        captured.append((url, headers, body))
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    llm.OpenRouterProvider(api_key="or-test-value", post=post).complete(
        system="s", user="u", json_schema={}, max_output_tokens=10)
    url, headers, body = captured[0]
    assert url == llm.OPENROUTER_URL and "or-test-value" not in url
    assert headers["Authorization"] == "Bearer or-test-value"
    assert "or-test-value" not in json.dumps(body)


def test_an_empty_answer_is_transient_so_the_chain_tries_the_next_account():
    empty = lambda u, h, b, t: {"choices": [{"message": {"content": "   "}}], "usage": {}}  # noqa: E731
    with pytest.raises(llm.TransientProviderError, match="empty answer"):
        llm.GroqProvider(api_key="k", post=empty).complete(
            system="s", user="u", json_schema={}, max_output_tokens=10)
