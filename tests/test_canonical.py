"""Canonicalisation, hashing and timezone handling."""

from __future__ import annotations

import pytest

from database.canonical import (
    PKT,
    base_ticker,
    canonical_url,
    content_sha256,
    is_utc_iso,
    normalise_name,
    short_name,
    to_utc,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("HTTPS://WWW.Dawn.com:443/news/1/?utm_source=tw&b=2&a=1#top", "https://www.dawn.com/news/1?a=1&b=2"),
    ("http://example.com:80", "http://example.com/"),
    ("https://example.com:8443//a//b/", "https://example.com:8443/a/b"),
    ("https://example.com/p?fbclid=abc&id=5", "https://example.com/p?id=5"),
])
def test_canonical_url(raw, expected):
    assert canonical_url(raw) == expected


def test_canonical_url_rejects_relative():
    with pytest.raises(ValueError):
        canonical_url("/news/1")


def test_content_hash_ignores_whitespace_only():
    assert content_sha256("A  b\r\nc ") == content_sha256("A b c")
    assert content_sha256("A b c") != content_sha256("A b d")


def test_names_and_tickers():
    assert normalise_name("Oil & Gas Development Company Limited") == \
        "oil and gas development company limited"
    assert short_name("The Bank of Punjab") == "bank of punjab"
    known = {"HBL", "PSO", "MCB"}
    assert base_ticker("HBLXD", known) == "HBL"
    assert base_ticker("pso", known) == "PSO"
    assert base_ticker("ABCXD", known) == "ABCXD"  # unknown base: unchanged


def test_timestamps_to_utc():
    assert to_utc("2026-11-06T16:48:00+05:00") == ("2026-11-06T11:48:00Z",
                                                   "2026-11-06T16:48:00+05:00", "+05:00")
    assert to_utc("Fri, 06 Nov 2026 16:48:00 +0500")[0] == "2026-11-06T11:48:00Z"
    utc, raw, off = to_utc("Fri, Nov 6, 2026 4:48 PM", default_tz=PKT)
    assert (utc, raw, off) == ("2026-11-06T11:48:00Z", "Fri, Nov 6, 2026 4:48 PM", "+05:00")
    assert is_utc_iso(utc)


def test_timestamp_without_zone_is_not_guessed():
    with pytest.raises(ValueError, match="no timezone"):
        to_utc("2026-11-06 16:48")
