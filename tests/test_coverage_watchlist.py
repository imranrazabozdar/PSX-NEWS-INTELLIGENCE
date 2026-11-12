"""The coverage watchlist: the finite scope for extraction and analysis. Names and sectors come from
owner-supplied data, merged with the seed and deduplicated. Nothing is guessed, and no entry remains
UNVERIFIED."""

import json
from pathlib import Path

from database import seed_loader

ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = json.loads((ROOT / "config" / "coverage_watchlist.json").read_text(encoding="utf-8"))
COMPANIES = WATCHLIST["companies"]
OWNER_REQUESTED = [
    "NPL",
    "NCPL",
    "CNERGY",
    "PRL",
    "NRL",
    "ATRL",
    "SNGP",
    "HUBC",
    "SAZEW",
    "PAEL",
    "CSIL",
    "KEL",
    "BECO",
    "ALTN",
    "WAVESAPP",
    "SPSL",
    "OGDC",
    "PPL",
    "HASCOL",
    "PTC",
    "FATIMA",
    "LUCK",
    "WAHDAT",
    "PIBTL",
    "FFL",
    "JSBL",
    "SNBL",
    "UBL",
    "NBP",
    "ASL",
    "MUGHAL",
    "BPL",
]
OWNER_FILE_ROWS = 96
SEED_ONLY = 11


def test_symbols_are_unique_case_insensitively():
    symbols = [c["symbol"].upper() for c in COMPANIES]
    assert len(symbols) == len(set(symbols)) == WATCHLIST["count"]


def test_the_count_is_the_owner_file_plus_seed_only_plus_owner_additions():
    # 96 owner-file rows, minus the excluded ECPL, plus 11 seed-only companies, plus the two owner additions
    # (ASL and BPL, which are not in the file). SNGPL is merged into SNGP and adds nothing.
    assert WATCHLIST["count"] == OWNER_FILE_ROWS - 1 + SEED_ONLY + 2 == 108


def test_every_owner_requested_symbol_is_in_the_watchlist():
    assert set(OWNER_REQUESTED) <= {c["symbol"] for c in COMPANIES}


def test_no_company_is_unverified():
    assert [c["symbol"] for c in COMPANIES if "UNVERIFIED" in (c["name"], c["sector"])] == []
    assert WATCHLIST["unverified_for_owner_review"] == {}


def test_excluded_and_merged_symbols_are_resolved():
    symbols = {c["symbol"] for c in COMPANIES}
    assert "ECPL" not in symbols and "SNGPL" not in symbols
    by = {c["symbol"]: c for c in COMPANIES}
    assert by["SNGP"]["name"] == "Sui Northern Gas Pipelines Limited"


def test_owner_supplied_names_and_sectors_are_recorded_exactly():
    by = {c["symbol"]: c for c in COMPANIES}
    assert (by["ASL"]["name"], by["ASL"]["sector"]) == ("Aisha Steel Mills Limited", "ENGINEERING")
    assert (by["BPL"]["name"], by["BPL"]["sector"]) == (
        "Burshane LPG (Pakistan) Limited",
        "OIL & GAS MARKETING COMPANIES",
    )


def test_every_seed_company_is_in_the_watchlist_and_flagged_in_scope():
    seed = seed_loader.load_json("companies.json")["companies"]
    symbols = {c["symbol"] for c in COMPANIES}
    assert {c["ticker"] for c in seed} <= symbols
    assert all(c["in_scope"] is True for c in seed)


def test_every_entry_records_its_source_and_build_time():
    for c in COMPANIES:
        assert c["source"] and c["added_utc"] == WATCHLIST["built_utc"]


def test_the_owner_file_hash_is_recorded():
    assert len(WATCHLIST["owner_source"]["sha256"]) == 64
