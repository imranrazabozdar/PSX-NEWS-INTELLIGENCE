"""
Unit tests for psx_feed_parser.

Run:  pytest -q
"""

import io
import zipfile
from datetime import date, time

import pytest

from engines.psx_feed_parser import (  # noqa: E402
    CompanyMaster,
    StatutoryAnnouncement,
    coerce_date,
    coerce_time,
    derive_category,
    extract_doc_id,
    index_by_symbol,
    load_announcements,
    parse_announcements,
    parse_company_master,
    split_record,
    unpack_member,
)

# --------------------------------------------------------------------------- #
# Tokenisation / coercion
# --------------------------------------------------------------------------- #


def test_split_record_detects_pipe():
    assert split_record("a|b|c") == ["a", "b", "c"]


def test_split_record_detects_tab():
    assert split_record("a\tb\tc") == ["a", "b", "c"]


def test_split_record_detects_whitespace_runs():
    assert split_record("a   b     c") == ["a", "b", "c"]


def test_coerce_date_multiple_formats():
    assert coerce_date("2026-01-15") == date(2026, 1, 15)
    assert coerce_date("15-Jan-2026") == date(2026, 1, 15)
    assert coerce_date("15/01/2026") == date(2026, 1, 15)
    # PSX live feed format, e.g. "11Nov2026"
    assert coerce_date("11Nov2026") == date(2026, 11, 11)


def test_derive_category_from_title():
    assert derive_category("Financial Results for the Quarter Ended Sep 30, 2026") == "Financial Results"
    assert derive_category("Board Meeting intimation") == "Board Meeting"
    assert derive_category("Material Information - plant shutdown") == "Material Information"
    assert derive_category("Change of registered office") is None


def test_coerce_time_variants_and_empty():
    assert coerce_time("09:45") == time(9, 45)
    assert coerce_time("09:45:30") == time(9, 45, 30)
    assert coerce_time("") is None


def test_extract_doc_id_from_url_and_bare_and_none():
    assert extract_doc_id("https://dps.psx.com.pk/download/document/123456.pdf") == 123456
    assert extract_doc_id("987654") == 987654
    assert extract_doc_id("no id here", "") is None


# --------------------------------------------------------------------------- #
# Announcement parsing
# --------------------------------------------------------------------------- #


# Real PSX announceWithSymbol.lis layout: SYMBOL|COMPANY_NAME|DATE|TIME|TITLE|
GOOD_ANNOUNCE = "\n".join(
    [
        "OGDC|Oil & Gas Development Company Limited|11Nov2026|14:22:10|"
        "Financial Results for the Quarter Ended September 30, 2026|",
        "LUCK|Lucky Cement Limited|11Nov2026|10:05:00|Board Meeting to consider interim dividend|",
        "ENGRO|Engro Corporation Limited|10Nov2026|09:30:45|Material Information regarding plant expansion|",
    ]
)


def test_parse_announcements_happy_path():
    recs = parse_announcements(GOOD_ANNOUNCE)
    assert len(recs) == 3
    first = recs[0]
    assert isinstance(first, StatutoryAnnouncement)
    assert first.symbol == "OGDC"
    assert first.company_name == "Oil & Gas Development Company Limited"
    assert first.date == date(2026, 11, 11)
    assert first.time == time(14, 22, 10)
    assert first.title.startswith("Financial Results")
    assert first.category == "Financial Results"
    assert first.doc_id is None  # feed has no attachment id
    assert recs[1].category == "Board Meeting"
    assert recs[2].category == "Material Information"


def test_parse_announcements_skips_corrupted_rows():
    text = "\n".join(
        [
            "OGDC|Oil & Gas Development Company Limited|11Nov2026|14:22:10|Results|",
            "GARBAGE",  # too few columns
            "LUCK|Lucky Cement|not-a-date|10:05:00|bad date row|",  # unparseable date
            "UBL|United Bank Limited|11Nov2026|11:00:00|Dividend notice|",
        ]
    )
    recs = parse_announcements(text)
    assert [r.symbol for r in recs] == ["OGDC", "UBL"]


def test_parse_announcements_doc_id_is_always_none():
    # A year in the title must NOT be mistaken for a doc_id.
    text = "HBL|Habib Bank Limited|11Nov2026|09:45:00|Notice for year 2026 accounts|"
    recs = parse_announcements(text)
    assert len(recs) == 1
    assert recs[0].doc_id is None
    assert recs[0].category is None


# --------------------------------------------------------------------------- #
# Company master parsing
# --------------------------------------------------------------------------- #


# Real PSX listed_cmp.lst layout: |SYMBOL|COMPANY_NAME|SECTOR_CODE|SECTOR_NAME|...
GOOD_MASTER = "\n".join(
    [
        "|OGDC|Oil & Gas Development Company Limited|0801|Oil & Gas Exploration|0|||",
        "|LUCK|Lucky Cement Limited|0501|Cement|0|||",
        "x",  # corrupted -> skipped
    ]
)


def test_parse_company_master():
    recs = parse_company_master(GOOD_MASTER)
    assert len(recs) == 2
    assert recs[0] == CompanyMaster(
        symbol="OGDC",
        name="Oil & Gas Development Company Limited",
        sector_code="0801",
        sector="Oil & Gas Exploration",
    )
    assert index_by_symbol(recs)["LUCK"].sector == "Cement"
    assert index_by_symbol(recs)["LUCK"].sector_code == "0501"


def test_symbol_is_uppercased():
    recs = parse_company_master("|ogdc|Oil & Gas Development Company Limited|0801|Oil & Gas|0|||")
    assert recs[0].symbol == "OGDC"


# --------------------------------------------------------------------------- #
# Archive unpacking (in memory, latin-1)
# --------------------------------------------------------------------------- #


def _zip_bytes(member_name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, text.encode("latin-1"))
    return buf.getvalue()


def test_unpack_member_by_suffix():
    data = _zip_bytes("announceWithSymbol.lis", GOOD_ANNOUNCE)
    text = unpack_member(data, ".lis")
    assert "OGDC" in text


def test_unpack_member_latin1_roundtrip():
    # latin-1 specific byte (0xE9 = é) must survive decoding.
    payload = "NESTLE|Nestl\xe9 Pakistan Limited|11Nov2026|09:45:00|Caf\xe9 listing notice|"
    data = _zip_bytes("announceWithSymbol.lis", payload)
    recs = load_announcements(data)
    assert recs[0].company_name == "Nestl\xe9 Pakistan Limited"
    assert recs[0].title == "Caf\xe9 listing notice"


def test_unpack_member_missing_suffix_raises():
    data = _zip_bytes("other.txt", "hello")
    with pytest.raises(ValueError):
        unpack_member(data, ".lis")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
