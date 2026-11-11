"""The coverage watchlist: the finite scope for extraction and analysis. Name-only data (symbol, name,
sector) from an owner-supplied file, merged with the seed and deduplicated. Unverified names are never
invented."""

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
    "SNGPL",
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
]


def test_symbols_are_unique_case_insensitively():
    symbols = [c["symbol"].upper() for c in COMPANIES]
    assert len(symbols) == len(set(symbols)) == WATCHLIST["count"]


def test_the_count_is_the_file_plus_seed_only_plus_requested_unverified():
    # 96 owner-file rows + 11 seed-only + the owner-requested symbols absent from the file (SNGPL, ASL, BPL)
    assert WATCHLIST["count"] == WATCHLIST["owner_source"]["rows"] + 11 + 3


def test_every_owner_requested_symbol_is_in_the_watchlist():
    symbols = {c["symbol"] for c in COMPANIES}
    assert set(OWNER_REQUESTED) <= symbols


def test_every_seed_company_is_in_the_watchlist_and_flagged_in_scope():
    seed = seed_loader.load_json("companies.json")["companies"]
    symbols = {c["symbol"] for c in COMPANIES}
    assert {c["ticker"] for c in seed} <= symbols
    assert all(c["in_scope"] is True for c in seed)


def test_unverified_names_are_marked_and_listed_for_review_and_only_those():
    marked = {c["symbol"] for c in COMPANIES if c["name"] == "UNVERIFIED" or c["sector"] == "UNVERIFIED"}
    assert marked == set(WATCHLIST["unverified_for_owner_review"]) == {"ECPL", "SNGPL", "ASL", "BPL"}
    assert all(
        c["name"] == "UNVERIFIED" and c["sector"] == "UNVERIFIED" for c in COMPANIES if c["symbol"] in marked
    )


def test_sngpl_is_not_merged_into_sngp():
    symbols = {c["symbol"]: c for c in COMPANIES}
    assert symbols["SNGPL"]["name"] == "UNVERIFIED"
    assert symbols["SNGP"]["name"] == "Sui Northern Gas Pipelines Limited"


def test_every_entry_records_its_source_and_build_time():
    for c in COMPANIES:
        assert c["source"] and c["added_utc"] == WATCHLIST["built_utc"]


def test_the_owner_file_hash_is_recorded():
    assert len(WATCHLIST["owner_source"]["sha256"]) == 64
