"""The extraction quality gate: what it trusts, and what it sends to a stronger model."""

from __future__ import annotations

from scripts import check_extraction_batch as gate

SOURCE = ("cement energy is 70 percent of cost and limestone is 5 percent " * 400) + " 1500 2000 3000 45 60"


def row(text, period=None, **kw):
    base = {"company": "SECTOR:CEMENT", "topic": "cost.energy_share", "fact_text": text, "value": None,
            "unit": None, "period": period, "source_name": "ARN, 'X' (YouTube transcript, undated)",
            "source_url": "https://y/x", "video_id": "x", "confidence": "analyst_view"}
    base.update(kw)
    return base


def test_a_well_grounded_file_passes():
    rows = [row("Energy is 70 percent of cost.") for _ in range(40)]
    assert gate.judge(rows, SOURCE).ok


def test_numbers_the_speaker_never_said_are_flagged_as_invented():
    rows = [row("Margins were 9123 and 8841 and 7712 and 6655 and 5544 and 4433.") for _ in range(40)]
    v = gate.judge(rows, SOURCE)
    assert not v.ok and any("possible invention" in r for r in v.reasons)


def test_a_relative_period_is_a_defect_because_it_mixes_eras():
    rows = [row("Energy is 70 percent of cost.", period="last year") for _ in range(40)]
    assert any("relative period" in r for r in gate.judge(rows, SOURCE).reasons)


def test_a_sparse_file_from_a_long_source_is_escalated_as_skimmed():
    v = gate.judge([row("Energy is 70 percent of cost.")], SOURCE)
    assert not v.ok and any("too sparse" in r for r in v.reasons)


def test_an_empty_file_is_fine_for_a_short_source_and_suspect_for_a_long_one():
    assert gate.judge([], "short personal finance talk").ok
    assert not gate.judge([], SOURCE).ok


def test_buy_sell_wording_is_flagged():
    rows = [row("You should buy this stock at 45.") for _ in range(40)]
    assert any("advice" in r for r in gate.judge(rows, SOURCE).reasons)


def test_a_row_missing_the_undated_declaration_breaks_the_schema():
    rows = [row("Energy is 70 percent of cost.", source_name="ARN, 'X'") for _ in range(40)]
    assert any("schema" in r for r in gate.judge(rows, SOURCE).reasons)
