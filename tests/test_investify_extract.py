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
