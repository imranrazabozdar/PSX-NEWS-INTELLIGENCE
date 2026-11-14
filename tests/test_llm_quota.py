"""Free-tier quota tracking: records, windows, pruning, and skip-before-call. Offline, no network."""

from __future__ import annotations

import json

import pytest

from database.connection import SQLiteDatabase
from engines import llm, llm_quota


def _tracker() -> llm_quota.QuotaTracker:
    return llm_quota.QuotaTracker(SQLiteDatabase())


def test_an_account_is_available_until_it_reaches_its_limit():
    tracker = _tracker()
    limits = llm_quota.QuotaLimits(requests_per_minute=2, requests_per_day=None)
    assert tracker.available("groq", 1, limits) == (True, "")
    tracker.record("groq", 1)
    assert tracker.available("groq", 1, limits) == (True, "")
    tracker.record("groq", 1)
    ok, reason = tracker.available("groq", 1, limits)
    assert ok is False and "2/2" in reason


def test_accounts_and_vendors_are_tracked_independently():
    tracker = _tracker()
    limits = llm_quota.QuotaLimits(requests_per_minute=1, requests_per_day=None)
    tracker.record("groq", 1)
    assert tracker.available("groq", 1, limits) == (False, "1/1 calls in the last minute")
    assert tracker.available("groq", 2, limits)[0] is True  # a different account of the same vendor
    assert tracker.available("gemini", 1, limits)[0] is True  # a different vendor, same account number


def test_a_call_older_than_the_window_no_longer_counts():
    tracker = _tracker()
    limits = llm_quota.QuotaLimits(requests_per_minute=None, requests_per_day=1)
    tracker.record("openrouter", 1)
    # backdate the one row past the day window, as if it happened yesterday
    tracker.db.execute("UPDATE llm_quota_call SET called_at_utc = '2000-01-01T00:00:00Z'")
    assert tracker.available("openrouter", 1, limits) == (True, "")


def test_a_limit_of_none_means_unlimited_and_is_never_the_reason_for_a_refusal():
    tracker = _tracker()
    for _ in range(50):
        tracker.record("gemini", 1)
    assert tracker.available("gemini", 1, llm_quota.QuotaLimits(None, None)) == (True, "")


def test_prune_drops_only_rows_older_than_two_days():
    tracker = _tracker()
    tracker.record("groq", 1)
    tracker.db.execute("UPDATE llm_quota_call SET called_at_utc = '2000-01-01T00:00:00Z'")
    tracker.record("groq", 1)  # a fresh row, right now
    tracker.prune()
    assert tracker.db.execute("SELECT COUNT(*) AS n FROM llm_quota_call")[0]["n"] == 1


def test_without_a_database_the_tracker_still_protects_this_one_process():
    tracker = llm_quota.QuotaTracker(db=None)
    limits = llm_quota.QuotaLimits(requests_per_minute=1, requests_per_day=None)
    tracker.record("groq", 1)
    assert tracker.available("groq", 1, limits)[0] is False


# ---------- limits: conservative defaults, overridable, since the published numbers are not reliable

def test_defaults_exist_for_every_wired_vendor_and_are_overridable():
    for vendor in ("groq", "gemini", "openrouter"):
        limits = llm_quota.limits_for(vendor, {})
        assert limits.requests_per_day is not None  # every default vendor has SOME cap, not "trust it"
    overridden = llm_quota.limits_for("groq", {"PSXNI_LLM_GROQ_RPD": "7"})
    assert overridden.requests_per_day == 7


def test_a_configured_zero_means_explicitly_unlimited_not_blocked():
    limits = llm_quota.limits_for("openrouter", {"PSXNI_LLM_OPENROUTER_RPD": "0"})
    assert limits.requests_per_day is None


# ---------- the guard: an exhausted leaf is skipped with no network call, not caught after failing

def _rotating(n: int, post):
    return llm.RotatingProvider([llm.GroqProvider(api_key=f"k{i}", post=post, account=i)
                                 for i in range(1, n + 1)])


def test_an_exhausted_account_is_skipped_before_any_call_is_made():
    calls: list[str] = []

    def post(url, headers, body, timeout):
        calls.append(headers["Authorization"])
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    tracker = _tracker()
    for _ in range(llm_quota.DEFAULT_LIMITS["groq"][1]):  # exhaust account #1's daily cap
        tracker.record("groq", 1)

    guarded = llm_quota.guard(_rotating(3, post), tracker)
    guarded.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert calls == ["Bearer k2"]  # account #1 never dialled out; #2 answered on the first attempt


def test_a_fallback_chain_is_guarded_vendor_by_vendor():
    def groq_busy(url, headers, body, timeout):
        raise llm.TransientProviderError("HTTP 429")

    def openrouter_ok(url, headers, body, timeout):
        return {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {}}

    tracker = _tracker()
    chain = llm.FallbackProvider([
        llm.GroqProvider(api_key="g", post=groq_busy, account=1),
        llm.OpenRouterProvider(api_key="o", post=openrouter_ok, account=1),
    ])
    guarded = llm_quota.guard(chain, tracker)
    out = guarded.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert json.loads(out.text) == {"ok": True}
    # the OpenRouter call that DID succeed was recorded, so it now counts toward that account's cap
    assert tracker.calls_since("openrouter", 1, llm_quota.DAY_SECONDS) == 1
    assert tracker.calls_since("groq", 1, llm_quota.DAY_SECONDS) == 0  # a failed attempt is not a "use"


def test_the_claude_stub_passes_through_unguarded():
    stub = llm.ClaudeProvider()
    assert llm_quota.guard(stub, _tracker()) is stub


def test_a_single_leaf_with_no_rotation_is_still_guarded():
    """A lone key is numbered account #1, matching how every real builder numbers its first key."""
    tracker = _tracker()
    for _ in range(llm_quota.DEFAULT_LIMITS["gemini"][1]):
        tracker.record("gemini", 1)
    leaf = llm.GeminiProvider(api_key="k", post=lambda *a: {"candidates": []}, account=1)
    guarded = llm_quota.guard(leaf, tracker)
    with pytest.raises(llm.TransientProviderError, match="quota reached"):
        guarded.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


def test_an_unnumbered_leaf_defaults_to_account_zero_not_silently_to_one():
    """account=0 ("not numbered by a builder") must track as its own bucket, never alias account #1."""
    tracker = _tracker()
    for _ in range(llm_quota.DEFAULT_LIMITS["gemini"][1]):
        tracker.record("gemini", 1)  # exhaust account #1 only
    leaf = llm.GeminiProvider(api_key="k", post=lambda *a: {"candidates": [{"content": {
        "parts": [{"text": "{}"}]}}], "usageMetadata": {}})
    guarded = llm_quota.guard(leaf, tracker)
    guarded.complete(system="s", user="u", json_schema={}, max_output_tokens=10)  # account 0 is untouched


# ---------- smart rotation: most headroom first, ties kept in the given (role-preferred) order

def _leaves(n: int, post):
    return [llm.GroqProvider(api_key=f"k{i}", post=post, account=i) for i in range(1, n + 1)]


def test_the_account_with_the_most_remaining_headroom_is_tried_first():
    calls: list[str] = []

    def post(url, headers, body, timeout):
        calls.append(headers["Authorization"])
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    tracker = _tracker()
    for _ in range(40):
        tracker.record("groq", 1)  # account #1 has used far more of its day than #2 or #3
    smart = llm_quota.SmartRotatingProvider(_leaves(3, post), tracker, llm_quota.QuotaLimits(None, 1000))
    smart.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert calls == ["Bearer k2"]  # the given order was [1,2,3]; #2 is first among the least-used


def test_equally_fresh_accounts_keep_the_order_they_were_given_in():
    """Ties must not scramble the caller's preferred order, or three roles would herd onto one account."""
    calls: list[str] = []

    def post(url, headers, body, timeout):
        calls.append(headers["Authorization"])
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    tracker = _tracker()
    leaves = _leaves(3, post)
    reordered = [leaves[2], leaves[0], leaves[1]]  # account #3 first, as a role's own preference
    smart = llm_quota.SmartRotatingProvider(reordered, tracker, llm_quota.QuotaLimits(None, 1000))
    smart.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert calls == ["Bearer k3"]


def test_usage_is_recorded_against_the_account_that_actually_answered():
    tracker = _tracker()

    def post(url, headers, body, timeout):
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    smart = llm_quota.SmartRotatingProvider(_leaves(2, post), tracker, llm_quota.QuotaLimits(None, 1000))
    smart.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert tracker.calls_since("groq", 1, llm_quota.DAY_SECONDS) == 1
    assert tracker.calls_since("groq", 2, llm_quota.DAY_SECONDS) == 0


def test_an_account_that_fails_live_is_skipped_in_favour_of_the_next_freshest():
    def account_one_down(url, headers, body, timeout):
        raise llm.TransientProviderError("HTTP 503")

    def account_two_ok(url, headers, body, timeout):
        return {"choices": [{"message": {"content": "{}"}}], "usage": {}}

    leaves = [llm.GroqProvider(api_key="k1", post=account_one_down, account=1),
              llm.GroqProvider(api_key="k2", post=account_two_ok, account=2)]
    smart = llm_quota.SmartRotatingProvider(leaves, _tracker(), llm_quota.QuotaLimits(None, 1000))
    smart.complete(system="s", user="u", json_schema={}, max_output_tokens=10)
    assert smart.last_used == "groq#2"


def test_every_account_exhausted_raises_with_every_reason_named():
    tracker = _tracker()
    for account in (1, 2):
        for _ in range(3):
            tracker.record("groq", account)
    smart = llm_quota.SmartRotatingProvider(_leaves(2, lambda *a: {}), tracker,
                                            llm_quota.QuotaLimits(None, 3))
    with pytest.raises(llm.TransientProviderError, match="groq#1.*groq#2"):
        smart.complete(system="s", user="u", json_schema={}, max_output_tokens=10)


def test_guard_replaces_a_rotating_provider_with_the_smart_equivalent_over_the_same_accounts():
    rotating = llm._vendor(llm.GroqProvider, {"PSXNI_GROQ_API_KEY_ONE": "a",
                                              "PSXNI_GROQ_API_KEY_TWO": "b"}, llm.GROQ_MODEL_VAR)
    smart = llm_quota.guard(rotating, _tracker())
    assert isinstance(smart, llm_quota.SmartRotatingProvider)
    assert [p.account for p in smart._providers] == [1, 2]
