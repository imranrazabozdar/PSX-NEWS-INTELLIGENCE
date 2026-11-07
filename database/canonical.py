"""Deterministic canonicalisation helpers: URLs, content hashes, names, tickers and timestamps.

Everything here is pure Python with no I/O, so the same input always gives the same output.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track clicks and never change the content.
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref_src"}
TRACKING_PREFIXES = ("utm_",)

PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan Standard Time; no daylight saving.

# Status markers PSX shows after a symbol (e.g. ex-dividend). They are not part of the ticker.
PSX_STATUS_SUFFIXES = ("XD", "XB", "XR", "XW")


def canonical_url(url: str) -> str:
    """Normalise a URL for deduplication.

    Lowercases the scheme and host, drops default ports, fragments and tracking parameters,
    sorts the query string, and removes a trailing slash (except on the root path).
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an absolute http(s) URL: {url!r}")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES))
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def normalise_text(text: str) -> str:
    """Unicode NFC, unify line endings and collapse whitespace."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def content_sha256(text: str) -> str:
    """Hash of normalised content. Whitespace-only differences give the same hash."""
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


_LEGAL_WORDS = r"\b(the|limited|ltd|company|co|plc|pvt|private|\(pvt\.\)|\(private\))\b"


def normalise_name(name: str) -> str:
    """Normalise a company name or alias for matching (casefold, '&' -> 'and', no punctuation)."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def short_name(legal_name: str) -> str:
    """Legal name without generic legal words, e.g. 'The Bank of Punjab' -> 'bank of punjab'."""
    s = normalise_name(legal_name)
    s = re.sub(_LEGAL_WORDS, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def base_ticker(symbol: str, known_tickers: set[str]) -> str:
    """Strip a PSX status suffix (e.g. 'HBLXD' -> 'HBL') when the base is a known ticker."""
    sym = symbol.strip().upper()
    if sym in known_tickers:
        return sym
    for suffix in PSX_STATUS_SUFFIXES:
        if sym.endswith(suffix) and sym[: -len(suffix)] in known_tickers:
            return sym[: -len(suffix)]
    return sym


def utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime: a timezone is required")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_utc_iso(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value or ""))


def to_utc(raw: str, *, default_tz: timezone | None = None) -> tuple[str, str, str]:
    """Parse a source timestamp. Returns (utc_iso, raw_string, original_offset).

    Accepts ISO-8601 (with offset or 'Z'), RFC-822 style ('Fri, 06 Nov 2026 16:48:00 +0500')
    and PSX's 'Fri, Nov 6, 2026 4:48 PM'. A timestamp without a zone is accepted only when
    default_tz is given (e.g. PKT for PSX pages). Otherwise it raises, rather than guessing.
    """
    from email.utils import parsedate_to_datetime

    s = raw.strip()
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    if dt is None:  # PSX formats first: the e-mail date parser misreads 'AM/PM'
        for fmt in ("%a, %b %d, %Y %I:%M %p", "%b %d, %Y %I:%M %p", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s, fmt)  # noqa: DTZ007 - zone applied below
                break
            except ValueError:
                continue
    if dt is None and not re.search(r"\b(AM|PM)\b", s, re.IGNORECASE):
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError):
            dt = None
    if dt is None:
        raise ValueError(f"unrecognised timestamp: {raw!r}")
    if dt.tzinfo is None:
        if default_tz is None:
            raise ValueError(f"timestamp has no timezone and no default was given: {raw!r}")
        dt = dt.replace(tzinfo=default_tz)
    offset = dt.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    return utc_iso(dt), raw, offset


def now_utc() -> str:
    return utc_iso(datetime.now(UTC))
