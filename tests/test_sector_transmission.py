import json
from pathlib import Path

from engines import news_facts as nf
from engines import news_importance as ni
from engines import sector_transmission as st

ROOT = Path(__file__).resolve().parents[1]


def test_a_driver_lists_the_usually_exposed_sectors_without_asserting_a_direction():
    out = st.candidates("Oil slips as recovering Mideast exports blunt Gulf tensions; Brent drops 78 cents")
    assert out and out[0]["driver"] == "crude oil price"
    sectors = {s["sector"] for s in out[0]["sectors"]}
    assert {"exploration and production", "refineries", "oil marketing"} <= sectors
    assert "not asserted" in out[0]["direction"] and "positive" not in out[0]["direction"]


def test_domestic_fuel_prices_gas_rates_and_the_rupee_each_have_a_driver_and_unrelated_news_none():
    assert st.candidates("Govt cuts petrol, high-speed diesel price by Rs2")[0]["driver"].startswith(
        "domestic petrol"
    )
    assert any(
        c["driver"] == "natural gas price or availability"
        for c in st.candidates("Plan finalised to procure 16 LNG cargoes")
    )
    assert any(c["driver"] == "interest rates" for c in st.candidates("SBP holds policy rate at 11%"))
    assert any(
        c["driver"] == "rupee exchange rate" for c in st.candidates("Rupee records gain against US dollar")
    )
    assert st.candidates("Kohat Cement shares its corporate briefing presentation") == []
    assert st.candidates("Fauji Foods appoints Waseem Haider as acting CEO") == []


def test_classified_events_carry_the_candidates_into_the_queue_payload():
    from engines import council_ledger as cl

    listing = json.loads((ROOT / "docs/research/psx_listed_companies.json").read_text("utf-8"))
    vocab = nf.build_vocabulary(dict(listing["companies"]), {}, [])
    head = ni.Headline(
        "profit", "u", "Govt cuts petrol, high-speed diesel price by Rs2", "2026-11-18T05:00:00Z"
    )
    events = ni.cluster([head], (), vocab)
    ni.classify(vocab, events)
    assert events[0].transmission and events[0].transmission[0]["sectors"]
    assert cl.event_payload(events[0])["transmission"] == events[0].transmission
