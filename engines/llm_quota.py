"""Free-tier quota tracking: skip an exhausted account BEFORE calling it, not after a failed 429.

The gateway already retries a provider that fails. That is not quota protection: with a free vendor
the cost-based daily budget never engages (price is zero), so nothing stopped a run from exhausting an
account's free allowance and then burning retries against it. This module adds our own record of
calls attempted, per vendor and per account, and refuses a call that would exceed a configured limit.

The published numbers are not reliable. Two of the three vendors publish nothing authoritative for a
free tier, or have cut it more than once in 2026, so the defaults here are conservative placeholders,
not a source of truth. Confirm them in each vendor's own dashboard and override with
PSXNI_LLM_<VENDOR>_RPM / PSXNI_LLM_<VENDOR>_RPD when they differ.

Groq's limit is reported to apply per ORGANIZATION, not per key: a second key under the same Groq
account adds no capacity, only a second Groq account does. This tracker counts per `account` number
as supplied by the caller, so it is the caller's responsibility to number accounts that are genuinely
separate organizations -- which is how engines.analyst_council.provider_for_role numbers them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.canonical import now_utc

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0004_llm_quota.sql"
PRUNE_AFTER_SECONDS = 2 * 24 * 60 * 60
MINUTE_SECONDS = 60
DAY_SECONDS = 24 * 60 * 60

# Conservative placeholders. Sourced 2026-11: Groq sample limits (per org) for free chat models are
# commonly ~30 req/min, ~1000 req/day. Gemini's free-tier numbers are not published and have been cut
# more than once in 2026; this default is deliberately low. OpenRouter's free-model cap is the one
# figure documented by the vendor itself: 20 req/min, 50 req/day without $10+ lifetime credit ever
# added (1000 req/day above that threshold -- raise PSXNI_LLM_OPENROUTER_RPD if that applies to you).
DEFAULT_LIMITS: dict[str, tuple[int | None, int | None]] = {
    "groq": (30, 1000),
    "gemini": (10, 150),
    "openrouter": (20, 50),
}


@dataclass(frozen=True)
class QuotaLimits:
    requests_per_minute: int | None
    requests_per_day: int | None


def limits_for(vendor: str, environ: Any = None) -> QuotaLimits:
    env = os.environ if environ is None else environ
    rpm_default, rpd_default = DEFAULT_LIMITS.get(vendor, (None, None))

    def read(suffix: str, default: int | None) -> int | None:
        raw = str(env.get(f"PSXNI_LLM_{vendor.upper()}_{suffix}", "") or "").strip()
        if not raw:
            return default
        return None if raw == "0" else int(raw)

    return QuotaLimits(read("RPM", rpm_default), read("RPD", rpd_default))


class QuotaTracker:
    """Our own log of attempted calls. Backed by psx-library when `db` is given, in-memory otherwise.

    The in-memory fallback exists so a caller with no database handy still gets protection within one
    process; it does not survive past this run, so the daily limit is enforced reliably only when a
    database is supplied (as engines.analyst_council.provider_for_role does via scripts/council_run.py).
    """

    def __init__(self, db: Any = None):
        self.db = db
        self._memory: list[tuple[str, int, str]] = []
        if db is not None:
            from scripts import apply_library_migration as mig

            for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
                db.execute(stmt)

    def record(self, vendor: str, account: int) -> None:
        when = now_utc()
        if self.db is None:
            self._memory.append((vendor, account, when))
            return
        self.db.execute("INSERT INTO llm_quota_call (vendor, account, called_at_utc) VALUES (?, ?, ?)",
                        (vendor, account, when))

    def calls_since(self, vendor: str, account: int, seconds: int) -> int:
        cutoff = _shift_utc(now_utc(), -seconds)
        if self.db is None:
            return sum(1 for v, a, w in self._memory if v == vendor and a == account and w >= cutoff)
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM llm_quota_call WHERE vendor = ? AND account = ? "
            "AND called_at_utc >= ?", (vendor, account, cutoff))[0]
        return int(row["n"])

    def available(self, vendor: str, account: int, limits: QuotaLimits) -> tuple[bool, str]:
        if limits.requests_per_minute is not None:
            used = self.calls_since(vendor, account, MINUTE_SECONDS)
            if used >= limits.requests_per_minute:
                return False, f"{used}/{limits.requests_per_minute} calls in the last minute"
        if limits.requests_per_day is not None:
            used = self.calls_since(vendor, account, DAY_SECONDS)
            if used >= limits.requests_per_day:
                return False, f"{used}/{limits.requests_per_day} calls in the last day"
        return True, ""

    def prune(self) -> None:
        """Drop rows older than two days. This is our own small log, never a thing worth keeping."""
        cutoff = _shift_utc(now_utc(), -PRUNE_AFTER_SECONDS)
        if self.db is None:
            self._memory = [row for row in self._memory if row[2] >= cutoff]
            return
        self.db.execute("DELETE FROM llm_quota_call WHERE called_at_utc < ?", (cutoff,))


def _shift_utc(stamp: str, seconds: int) -> str:
    from datetime import UTC, datetime, timedelta

    dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class QuotaGuardedProvider:
    """Wraps one leaf provider. Refuses, with no network call, once its account is at its limit.

    Raising TransientProviderError (not a new exception type) means RotatingProvider and
    FallbackProvider need no changes at all: an exhausted account is simply one more account they
    already know how to skip past.
    """

    def __init__(self, provider: Any, quota: QuotaTracker, limits: QuotaLimits):
        self._provider = provider
        self._quota = quota
        self._limits = limits
        self.name = provider.name
        self.model = provider.model
        self.account = getattr(provider, "account", 0)

    def complete(self, *, system: str, user: str, json_schema: dict, max_output_tokens: int) -> Any:
        from engines.llm import TransientProviderError

        ok, reason = self._quota.available(self.name, self.account, self._limits)
        if not ok:
            raise TransientProviderError(f"{self.name}#{self.account or '?'} quota reached: {reason}")
        out = self._provider.complete(system=system, user=user, json_schema=json_schema,
                                      max_output_tokens=max_output_tokens)
        self._quota.record(self.name, self.account)
        return out


def guard(provider: Any, quota: QuotaTracker, environ: Any = None) -> Any:
    """Wrap every network-calling leaf of a provider or provider chain with its vendor's quota guard.

    Walks FallbackProvider and RotatingProvider in place (they only hold a list of sub-providers, so
    replacing that list is enough) and wraps a bare leaf provider directly. A provider with no `name`
    naming a known vendor (the not-connected Claude stub, a test double) passes through unchanged.
    """
    from engines.llm import FallbackProvider, RotatingProvider

    if isinstance(provider, FallbackProvider):
        provider._providers = [guard(p, quota, environ) for p in provider._providers]
        return provider
    if isinstance(provider, RotatingProvider):
        provider._providers = [guard(p, quota, environ) for p in provider._providers]
        return provider
    if getattr(provider, "name", None) in DEFAULT_LIMITS:
        return QuotaGuardedProvider(provider, quota, limits_for(provider.name, environ))
    return provider
