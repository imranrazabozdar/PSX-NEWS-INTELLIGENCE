"""The quota status reporter: our own tracked counts, and parsing OpenRouter's live response.

Offline. The "live" OpenRouter call is an injected function; no network is ever used.
"""

from __future__ import annotations

from database.connection import SQLiteDatabase
from engines import llm_quota
from scripts import llm_quota_status as status


def test_openrouter_live_status_reads_the_documented_shape():
    def fake_get(url, headers):
        assert headers["Authorization"] == "Bearer or-test"
        return {"data": {"free_model_daily_requests": {"used": 3, "limit": 50, "remaining": 47}}}

    out = status.openrouter_live_status("or-test", get=fake_get)
    assert out == {"used": 3, "limit": 50, "remaining": 47}


def test_an_unreadable_live_response_reports_none_not_a_crash():
    def broken_get(url, headers):
        raise TimeoutError("slow")

    assert status.openrouter_live_status("k", get=broken_get) is None


def test_an_unexpected_shape_reports_none_rather_than_a_wrong_number():
    assert status.openrouter_live_status("k", get=lambda u, h: {"nothing": "useful"}) is None


def test_the_report_shows_every_vendor_with_a_key_and_skips_vendors_without_one(capsys):
    env = {"PSXNI_GROQ_API_KEY_ONE": "g1"}
    status.report(env, db=SQLiteDatabase())
    out = capsys.readouterr().out
    assert "== groq:" in out and "#1:" in out
    assert "== gemini: no key set" in out and "== openrouter: no key set" in out


def test_tracked_usage_for_an_exhausted_account_is_shown_as_at_limit(capsys):
    db = SQLiteDatabase()
    tracker = llm_quota.QuotaTracker(db)
    for _ in range(llm_quota.DEFAULT_LIMITS["groq"][1]):
        tracker.record("groq", 1)
    status.report({"PSXNI_GROQ_API_KEY_ONE": "g1"}, db=db)
    out = capsys.readouterr().out
    assert "AT LIMIT" in out


def test_openrouter_live_lookup_is_attempted_for_every_openrouter_key(capsys):
    calls = []

    def fake_get(url, headers):
        calls.append(headers["Authorization"])
        return {"data": {"free_model_daily_requests": {"used": 0, "limit": 50, "remaining": 50}}}

    import unittest.mock

    with unittest.mock.patch.object(status, "_get", fake_get):
        status.report({"PSXNI_OPENROUTER_API_KEY_ONE": "or1"}, db=SQLiteDatabase())
    assert calls == ["Bearer or1"]
