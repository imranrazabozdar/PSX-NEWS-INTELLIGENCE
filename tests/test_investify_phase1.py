"""Phase 1 of the Investify ingestion: taxonomy, insider transactions, News behind its flag.

All data is SYNTHETIC. The taxonomy totals use an invented set with the same subtype mix as a 40-item page,
so the test checks the mapping and the completeness rule without any live data.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from collectors import investify_fundamentals as fund
from engines import investify_extract as x
from engines import investify_insiders as ins
from engines import investify_taxonomy as tax

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "investify"

# (event type, subtype, count): the mix observed on one 40-item company page (synthetic counts, same shape)
MIX = [
    ("corporate_action", "dividend", 7), ("corporate_briefing", "briefing_video", 6),
    ("other", "report_transmission", 4), ("financials", "financial_result", 4),
    ("meeting_governance", "board_meeting", 4), ("material_disclosure", "other", 4),
    ("corporate_briefing", "briefing_presentation", 3), ("meeting_governance", "agm_egm", 3),
    ("material_disclosure", "mna_public_offer", 1), ("material_disclosure", "operations_update", 1),
    ("insider_activity", "insider_buy", 1), ("corporate_action", "share_buyback", 1),
    ("meeting_governance", "auditor_certificate", 1),
]
EXPECTED = {"Financials": 8, "Material": 6, "Actions": 8, "Insiders": 1, "Meetings": 7, "Briefings": 9,
            "Other": 1}


def _items():
    return [{"event_type": e, "sub_type": s} for e, s, n in MIX for _ in range(n)]


# ------------------------------------------------------------------ taxonomy

def test_every_observed_pair_maps_to_one_known_group():
    for e, s, _ in MIX:
        assert tax.is_known(e, s), (e, s)
        assert tax.classify(e, s) in tax.GROUPS


def test_the_seven_group_counts_match_the_page_mix_and_sum_to_the_total():
    c = tax.counts(_items())
    assert c == EXPECTED
    assert sum(c.values()) == len(_items()) == 40  # completeness: nothing is left unclassified


def test_report_transmission_is_financials_and_auditor_certificate_is_other():
    assert tax.classify("other", "report_transmission") == "Financials"
    assert tax.classify("meeting_governance", "auditor_certificate") == "Other"
    assert tax.classify("meeting_governance", "board_meeting") == "Meetings"


def test_an_unknown_pair_is_other_and_reported_as_unknown_never_guessed():
    assert tax.classify("brand_new_type", "brand_new_subtype") == "Other"
    assert tax.is_known("brand_new_type", "brand_new_subtype") is False


def test_the_announcements_parser_attaches_the_group_to_each_item():
    parsed = x.parse_announcements((FIX / "announcements_synthetic.html").read_bytes(), "FCL")
    by_sub = {i["sub_type"]: i["taxonomy"] for i in parsed["items"]}
    assert by_sub == {"financial_result": "Financials", "board_meeting": "Meetings"}


# ------------------------------------------------------------------ insider transactions

def _fields(**over):
    base = {"symbol": "HUBC", "insider_name": "A Director", "role": "Director", "action": "buy",
            "date": "2026-08-11", "shares": 198378, "price_or_value": "Rs. 200.00",
            "source_external_id": "dps:image:900000-1"}
    base.update(over)
    return base


def test_an_insider_record_needs_every_field_and_guesses_none():
    fields = _fields()
    del fields["shares"]
    with pytest.raises(ValueError, match="missing"):
        ins.transaction(fields)


def test_an_unknown_action_or_a_malformed_date_is_refused():
    with pytest.raises(ValueError):
        ins.transaction(_fields(action="gift"))
    with pytest.raises(ValueError):
        ins.transaction(_fields(date="11/08/2026"))


def test_the_same_insider_date_and_action_is_one_record():
    a = ins.transaction(_fields())
    b = ins.transaction(_fields(insider_name="a director", shares=1, source_external_id="dps:image:900000-2"))
    assert ins.dedupe([a, b]) == [a]  # case-insensitive name; the first record is kept


def test_a_different_action_or_date_is_a_distinct_record():
    buy = ins.transaction(_fields())
    sell = ins.transaction(_fields(action="sell"))
    later = ins.transaction(_fields(date="2026-08-12"))
    assert len(ins.dedupe([buy, sell, later])) == 3


# ------------------------------------------------------------------ News: off by its flag

def test_the_shipped_flag_keeps_news_off():
    assert fund.news_enabled() is False


def test_news_is_refused_before_any_request_while_the_flag_is_off():
    out = fund.run_endpoint(now=__import__("datetime").datetime(2026, 11, 16, 5, 0,
                            tzinfo=__import__("datetime").UTC), state_path=Path("/nonexistent/state.json"),
                            entry={}, db=None, endpoint="news", symbol="HUBC", watchlist=frozenset({"HUBC"}))
    assert out.status == "refused" and "news is off" in out.reason


def test_news_stays_refused_even_with_the_flag_on_while_its_path_is_unconfirmed(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    monkeypatch.setattr(fund, "news_enabled", lambda *a, **k: True)
    entry = {"source_id": fund.SOURCE_ID, "enabled": 1, "lifecycle_status": "APPROVED",
             "terms_status": "approved",
             "access_status": "verified_permitted", "access_method": "html_permitted"}
    out = fund.run_endpoint(now=datetime(2026, 11, 16, 5, 0, tzinfo=UTC), state_path=tmp_path / "s.json",
                            entry=entry, db=None, endpoint="news", symbol="HUBC",
                            watchlist=frozenset({"HUBC"}))
    assert out.status == "refused" and "not yet confirmed" in out.reason


def test_news_is_listed_but_has_no_confirmed_path():
    assert fund.ENDPOINTS["news"].path_template is None


# ------------------------------------------------------------------ no archive, production or Turso

@pytest.mark.parametrize("module", ["engines/investify_taxonomy.py", "engines/investify_insiders.py",
                                    "collectors/investify_fundamentals.py"])
def test_phase1_modules_never_import_the_archive_or_production_connections(module):
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("archive" in m or m == "database.financial_repo" for m in imported)
    assert "connect_main" not in " ".join(imported) and "connect_archive" not in " ".join(imported)
