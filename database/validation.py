"""Data-quality validation for reference data, run before anything is written (spec 11.1, 16)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from database.canonical import canonical_url

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
TICKER = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+00:00|Z)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PSX_COMPANY_URL = re.compile(r"^https://dps\.psx\.com\.pk/company/([A-Z0-9]+)$")
SOURCE_ID = re.compile(r"^[a-z0-9_]{2,64}$")


def validate_company_seed(seed: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    companies = seed.get("companies", [])
    if not 30 <= sum(c.get("listing_status") == "listed" for c in companies) <= 60:
        errors.append("company universe must have about 30-50 listed companies")
    dupes = [t for t, n in Counter(c.get("ticker") for c in companies).items() if n > 1]
    if dupes:
        errors.append(f"duplicate tickers: {dupes}")
    names = [t for t, n in Counter(c.get("legal_name") for c in companies).items() if n > 1]
    if names:
        errors.append(f"duplicate legal names: {names}")
    for c in companies:
        t = c.get("ticker", "")
        p = f"{t}: "
        if not TICKER.match(t):
            errors.append(p + "invalid ticker format")
        if t.endswith("XD"):
            errors.append(p + "'XD' is a PSX status marker, not part of a ticker")
        if not (c.get("legal_name") or "").strip():
            errors.append(p + "missing legal name")
        if not (c.get("psx_sector") or "").strip():
            errors.append(p + "missing PSX sector")
        if c.get("fiscal_year_end_month") not in MONTHS:
            errors.append(p + f"invalid fiscal year end {c.get('fiscal_year_end_month')!r}")
        if c.get("listing_status") not in ("listed", "delisted", "suspended", "unknown"):
            errors.append(p + "invalid listing status")
        if len(c.get("business_summary") or "") > 600:
            errors.append(p + "business summary longer than 600 characters")
        src = c.get("source") or {}
        m = PSX_COMPANY_URL.match(src.get("url", ""))
        if not m or m.group(1) != t:
            errors.append(p + "source URL must be the official PSX page for this ticker")
        if not ISO_UTC.match(src.get("fetched_at_utc", "")):
            errors.append(p + "source fetched_at_utc must be ISO-8601 UTC")
        if not SHA256.match(src.get("page_sha256", "")):
            errors.append(p + "source page_sha256 missing or malformed")
    return errors


LIFECYCLE = ("NOT REVIEWED", "REVIEWED", "APPROVED", "RESTRICTED", "LICENCE REQUIRED", "BLOCKED",
             "IMPLEMENTED", "TESTED", "ACTIVE", "DISABLED")
ADAPTERS = ("rss", "atom", "json_api", "udf_ohlcv")  # udf_ohlcv: collectors/market_ohlcv.py
# Sources collected under written consent, mapped to their consent record. Such a source is enabled but never
# ACTIVE: the generic engine refuses it; only its consent-bound job (collectors/investify_job.py) collects it.
CONSENT_RECORDS = {"investify_announcements": "docs/consent/investify-2026-11-12.md"}
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _consent_errors(s: dict[str, Any]) -> list[str]:
    sid = s.get("source_id", "")
    errors = []
    record = CONSENT_RECORDS[sid]
    if not (_REPO_ROOT / record).is_file():
        errors.append(f"{sid}: consent record {record} is missing")
    if s.get("lifecycle_status") != "APPROVED":
        errors.append(f"{sid}: a consent-governed source must have lifecycle APPROVED (never ACTIVE)")
    if s.get("terms_status") != "approved":
        errors.append(f"{sid}: a consent-governed source must have terms_status approved")
    if s.get("access_status") != "verified_permitted":
        errors.append(f"{sid}: a consent-governed source must have access_status verified_permitted")
    if s.get("access_method") != "html_permitted":
        errors.append(f"{sid}: a consent-governed source must have access_method html_permitted")
    if s.get("licensing_status") != "permission_required":
        errors.append(f"{sid}: a consent-governed source must record licensing_status permission_required")
    return errors


def validate_source_registry(reg: dict[str, Any]) -> list[str]:
    errors = []
    ids = [s.get("source_id") for s in reg.get("sources", [])]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"duplicate source ids: {dupes}")
    urls = Counter((s.get("official_url"), s.get("feed_url")) for s in reg.get("sources", [])
                   if s.get("official_url") and s.get("feed_url"))
    for key, n in urls.items():
        if n > 1:
            errors.append(f"duplicate source endpoint {key}")
    for s in reg.get("sources", []):
        sid = s.get("source_id") or ""
        if not SOURCE_ID.match(sid):
            errors.append(f"{sid!r}: invalid source id")
        if not s.get("name"):
            errors.append(f"{sid}: missing name")
        life = s.get("lifecycle_status", "NOT REVIEWED")
        if life not in LIFECYCLE:
            errors.append(f"{sid}: invalid lifecycle status {life!r}")
        consent_governed = sid in CONSENT_RECORDS
        if s.get("enabled") and life != "ACTIVE" and not consent_governed:
            errors.append(f"{sid}: enabled without being ACTIVE")
        if consent_governed:
            errors.extend(_consent_errors(s))
        if life == "ACTIVE" and (s.get("terms_status") != "approved"
                                 or s.get("access_status") != "verified_permitted"):
            errors.append(f"{sid}: ACTIVE requires approved terms and verified access")
        if life in ("IMPLEMENTED", "TESTED", "ACTIVE") and (s.get("adapter") not in ADAPTERS
                                                            or not s.get("feed_url")):
            errors.append(f"{sid}: {life} requires an implemented adapter and endpoint")
        fresh = s.get("freshness_status", "unknown")
        if fresh not in ("unknown", "fresh", "stale", "not_applicable"):
            errors.append(f"{sid}: invalid freshness status {fresh!r}")
        if s.get("last_test_result", "not_tested") not in ("not_tested", "passed", "failed"):
            errors.append(f"{sid}: invalid last test result")
        if life in ("TESTED", "ACTIVE") and (s.get("last_test_result") != "passed" or fresh != "fresh"):
            errors.append(f"{sid}: {life} requires a passed test and a fresh feed")
        if s.get("last_test_result", "not_tested") != "not_tested" and not s.get("last_test_at_utc"):
            errors.append(f"{sid}: test result without test date")
        if life != "NOT REVIEWED" and not s.get("reviewed_at_utc"):
            errors.append(f"{sid}: reviewed status without review date")
        if life != "NOT REVIEWED" and not s.get("review_notes"):
            errors.append(f"{sid}: reviewed status without review notes")
        for key in ("official_url", "feed_url"):
            if s.get(key) and not str(s[key]).startswith("https://"):
                errors.append(f"{sid}: {key} must be https")
        retention = s.get("retention_mode", "metadata_only")
        if retention != "metadata_only" and s.get("terms_status") != "approved":
            errors.append(f"{sid}: retaining excerpts requires approved terms")
    return errors


def validate_media_watchlist(wl: dict[str, Any]) -> list[str]:
    errors = []
    seen = set()
    for a in wl.get("accounts", []):
        key = (a.get("platform"), (a.get("handle") or "").lower())
        if a.get("handle"):
            if key in seen:
                errors.append(f"duplicate account {key}")
            seen.add(key)
            expected = (f"https://x.com/{a['handle']}" if a["platform"] == "x"
                        else f"https://youtube.com/@{a['handle']}")
            if a.get("supplied_url") != expected:
                errors.append(f"{key}: supplied URL does not match the exact handle")
        elif a.get("supplied_url"):
            errors.append(f"{a.get('display_name')}: pending account must not have a guessed URL")
    return errors


def validate_url(url: str) -> list[str]:
    try:
        canonical_url(url)
        return []
    except ValueError as exc:
        return [str(exc)]
