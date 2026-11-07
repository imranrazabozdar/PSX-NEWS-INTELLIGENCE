"""Data-quality validation for reference data, run before anything is written (spec 11.1, 16)."""

from __future__ import annotations

import re
from collections import Counter
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


def validate_source_registry(reg: dict[str, Any]) -> list[str]:
    errors = []
    ids = [s.get("source_id") for s in reg.get("sources", [])]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        errors.append(f"duplicate source ids: {dupes}")
    for s in reg.get("sources", []):
        sid = s.get("source_id") or ""
        if not SOURCE_ID.match(sid):
            errors.append(f"{sid!r}: invalid source id")
        if s.get("enabled"):
            errors.append(f"{sid}: sources must not be enabled in Phase 1")
        if not s.get("name"):
            errors.append(f"{sid}: missing name")
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
