"""Structured-field extractors, tested on SYNTHETIC fixtures (invented values, same markup shape).

No test uses live Investify data. The fixtures in tests/fixtures/investify/ are constructed for these tests.
"""

from __future__ import annotations

from pathlib import Path

from engines import investify_extract as x

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "investify"


def test_profile_fields_from_a_synthetic_page():
    p = x.parse_profile((FIX / "profile_synthetic.html").read_bytes(), "HUBC")
    # the sector comes from the embedded company index, not from rendered text
    assert p["sector"] == "Power Generation & Distribution"
    assert p["leadership"] == {"chairperson": "Person A", "ceo": "Person B", "company_secretary": "Person C"}
    assert p["market_structure"]["market_cap"] == {"text": "Rs 10.00B", "value": 10_000_000_000.0}
    assert p["market_structure"]["total_shares"]["value"] == 2_000_000_000.0
    assert p["share_float_split"]["locked_pct"] == 50.0 and p["share_float_split"]["free_float_pct"] == 50.0
    assert p["registered_address"] == "1 Test Street, Testville"
    assert p["website"] == "www.example.test"
    assert p["description"] == "Synthetic description."  # stored, attributed (owner decision)


def test_amount_keeps_printed_text_and_scales_units():
    assert x.amount("Rs 268.23B") == {"text": "Rs 268.23B", "value": 268_230_000_000.0}
    assert x.amount("972.87M")["value"] == 972_870_000.0
    assert x.amount("206.78")["value"] == 206.78


def test_fundamentals_cards_from_a_synthetic_page():
    r = x.parse_fundamentals((FIX / "fundamentals_synthetic.html").read_bytes(), "HUBC")
    assert r["metric_count"] == 4
    by = {m["label"]: m for m in r["metrics"]}
    assert by["Annual EPS"]["value"] == {"text": "Rs. 10.50", "value": 10.5, "unit": "PKR"}
    assert by["Annual EPS"]["period_basis"] == "2026 FY" and by["Annual EPS"]["sentiment"] == "positive"
    assert by["Current Ratio"]["value"]["unit"] == "ratio" and by["Current Ratio"]["value"]["value"] == 1.5
    assert by["Book Value / Share"]["period_basis"] == "BASED ON 2027 1Q"  # verbatim
    assert by["Gross Margin"]["value"] == {"text": "40.00%", "value": 40.0, "unit": "percent"}
    assert by["Gross Margin"]["sentiment"] == "negative"


def test_competitors_are_the_same_sector_companies_marked_sector_derived():
    r = x.parse_competitors((FIX / "competitors_synthetic.html").read_bytes(), "TGT")
    assert r["peer_source"] == "sector-derived"
    assert r["peer_count"] == 16 and r["same_sector_count"] == 16
    tickers = [p["ticker"] for p in r["peers"]]
    assert tickers == [f"PEER{i:02d}" for i in range(16)]  # the target and the other sector are excluded
    assert r["peers"][0] == {"ticker": "PEER00", "name": "Peer 00 Ltd", "sector": "Synthetic Sector"}


def test_the_sixteen_versus_fourteen_note_is_recorded():
    r = x.parse_competitors((FIX / "competitors_synthetic.html").read_bytes(), "TGT")
    assert r["displayed_peer_count_reported"] == 14
    assert r["displayed_excluded_same_sector"] == ["GEMMEL", "NGLEL"]
    assert "superset by 2" in r["note"]
