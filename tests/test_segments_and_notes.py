"""Segment reconciliation and notes extraction with page evidence. SYNTHETIC inputs only."""

from __future__ import annotations

import pytest

from engines import notes_extraction as ne
from engines import segments as sg

GROUP_EV = {"page": 40, "excerpt": "Total revenue 1,000 800"}


def seg(name, revenue, profit=None, page=41):
    evidence = {"page": page, "excerpt": f"{name} revenue {revenue}"}
    row = {"name": name, "revenue": revenue, "evidence": evidence}
    if profit is not None:
        row["profit"] = profit
    return row


GROUP = {"revenue": 1000.0, "profit": 160.0, "evidence": GROUP_EV}


def test_reconciled_segments_give_shares_margins_and_profit_shares():
    result = sg.reconcile([seg("Upstream", 600.0, 120.0), seg("Downstream", 400.0, 40.0)], GROUP)
    assert result["state"] == "reconciled" and result["revenue_difference"] == 0.0
    by = {r["name"]: r for r in result["segments"]}
    assert by["Upstream"]["revenue_share_pct"] == 60.0 and by["Downstream"]["revenue_share_pct"] == 40.0
    assert by["Upstream"]["margin_pct"] == 20.0 and by["Downstream"]["margin_pct"] == 10.0
    assert by["Upstream"]["profit_share_pct"] == 75.0


def test_segments_that_do_not_add_up_are_unreconciled_and_show_no_shares():
    result = sg.reconcile([seg("Upstream", 600.0, 120.0), seg("Downstream", 300.0, 40.0)], GROUP)
    assert result["state"] == "unreconciled"
    assert result["revenue_difference"] == -100.0
    assert "segments" not in result                       # no shares presented as facts


def test_small_rounding_inside_the_stated_tolerance_still_reconciles():
    group = {"revenue": 10000.0, "evidence": GROUP_EV}
    result = sg.reconcile([seg("A", 6002.0), seg("B", 4002.0)], group)   # 4 over; tolerance is 10
    assert result["state"] == "reconciled"


def test_missing_evidence_is_refused_for_the_group_and_for_segments():
    with pytest.raises(sg.EvidenceError):
        sg.reconcile([seg("A", 1000.0)], {"revenue": 1000.0, "evidence": {"page": 0, "excerpt": "x"}})
    bad = {"name": "A", "revenue": 1000.0, "evidence": {"page": 3, "excerpt": ""}}
    with pytest.raises(sg.EvidenceError):
        sg.reconcile([bad], GROUP)


def test_a_missing_segment_revenue_is_named_not_treated_as_zero():
    b_without_revenue = {"name": "B", "evidence": seg("B", 0)["evidence"]}
    result = sg.reconcile([seg("A", 600.0), b_without_revenue], GROUP)
    assert result["state"] == "insufficient_data"
    assert result["missing"] == ["revenue of segment 'B'"]


def test_missing_segment_profit_gives_no_margin_and_no_profit_share():
    result = sg.reconcile([seg("A", 600.0, 120.0), seg("B", 400.0)], GROUP)
    by = {r["name"]: r for r in result["segments"]}
    assert by["B"]["margin_state"] == "insufficient_data" and by["B"]["margin_pct"] is None
    assert "profit_share_pct" not in by["A"]


def test_zero_revenue_segment_margin_is_not_applicable():
    result = sg.reconcile([seg("A", 1000.0, 50.0), seg("Dormant", 0.0, -5.0)], GROUP)
    by = {r["name"]: r for r in result["segments"]}
    assert by["Dormant"]["margin_state"] == "not_applicable"


def test_growth_for_a_new_segment_is_not_reported_not_zero():
    current = [{"name": "A", "revenue": 600.0}, {"name": "B", "revenue": 400.0}]
    prior = [{"name": "A", "revenue": 500.0}]
    by = {r["name"]: r for r in sg.growth(current, prior)}
    assert by["A"]["growth_pct"] == 20.0
    assert by["B"]["state"] == "not_reported" and by["B"]["growth_pct"] is None


def test_concentration_is_the_largest_reconciled_share():
    result = sg.reconcile([seg("A", 600.0, 120.0), seg("B", 400.0, 40.0)], GROUP)
    assert sg.concentration(result["segments"]) == {"name": "A", "revenue_share_pct": 60.0}
    assert sg.concentration([]) is None


PAGES = [
    (210, "Note 9: Trade debts\nTrade debts 1,234 (987)\n"
          "Less: provision for doubtful debts (45) -\nOther note text"),
    (211, "Trade debts are described in the accounting policy below.\nTotal assets 5,000 4,800"),
]


def test_a_labelled_value_keeps_its_page_and_verbatim_line():
    labels = {"trade_debts": r"Trade debts", "provision": r"Less: provision for doubtful debts"}
    found = ne.find(PAGES, labels)
    assert found["trade_debts"]["state"] == "reported"
    assert found["trade_debts"]["page"] == 210
    assert found["trade_debts"]["excerpt"] == "Trade debts 1,234 (987)"
    assert found["trade_debts"]["values"] == [1234.0, -987.0]


def test_brackets_read_as_negative_and_a_dash_is_not_reported_not_zero():
    found = ne.find(PAGES, {"provision": r"Less: provision for doubtful debts"})
    assert found["provision"]["values"] == [-45.0, None]


def test_a_label_that_only_appears_in_prose_is_not_a_value():
    found = ne.find(PAGES, {"trade_debts": r"Trade debts"})
    assert found["trade_debts"]["state"] == "reported"      # the prose row on page 211 has no numbers
    assert found["trade_debts"]["page"] == 210


def test_no_matching_row_is_not_reported():
    assert ne.find(PAGES, {"ageing": r"Ageing analysis"})["ageing"] == {"state": "not_reported"}


def test_two_matching_rows_are_ambiguous_and_neither_is_chosen():
    pages = [(5, "Total assets 100 90"), (9, "Total assets 200 180")]
    found = ne.find(pages, {"assets": r"Total assets"})
    assert found["assets"]["state"] == "ambiguous"
    assert [c["page"] for c in found["assets"]["candidates"]] == [5, 9]
    assert "values" not in found["assets"]
