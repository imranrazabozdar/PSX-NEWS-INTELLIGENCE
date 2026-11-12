"""Receivables ageing, credit ratios, contingencies and continuation pages.

SYNTHETIC notes with invented figures.
"""

from __future__ import annotations

import pytest

from engines import notes_extraction as ne
from engines import pdf_extraction as pe
from tests.pdf_fixture_builder import write_pdf

COLS = ["2025-06-30", "2024-06-30"]
BALANCE_SHEET_CODES = {"total_assets", "total_liabilities", "total_equity", "trade_receivables", "inventory"}


def _pages():
    return [
        [
            "12. Trade debts",
            "Not yet due 500 400",
            "1-30 days 200 150",
            "31-90 days 80 70",
            "91-180 days 30 20",
            "181-365 days 10 8",
            "Over 365 days 5 4",
            "Other 3 2",
            "Trade debts 825 652",
            "Expected credit loss allowance (30) (25)",
            "Net trade debts 795 627",
        ],
        [
            "12. Trade debts (continued)",
            "Disputed receivables 12 10",
            "Undisputed receivables 813 642",
        ],
        [
            "20. Contingencies and commitments",
            "Income tax demands 150 120",
            "Sales tax demand under appeal 80 70",
            "Guarantees issued by banks 50 40",
            "Capital expenditure commitments 30 20",
            "A writ petition is pending before the High Court relating to the gas levy.",
        ],
    ]


@pytest.fixture
def result(tmp_path):
    return ne.extract_notes(pe.extract(write_pdf(tmp_path / "n.pdf", _pages())), columns=COLS)


def test_a_continued_heading_does_not_start_a_second_note(result):
    notes = [n for n in result["notes"] if n["category"] == "trade_receivables"]
    assert len(notes) == 1 and notes[0]["note_no"] == "12"
    disputed = [r for r in result["lines"] if r["raw_label"] == "Disputed receivables"]
    assert disputed and disputed[0]["note_ref"] == "12" and disputed[0]["page"] == 2


def test_ageing_brackets_are_classified_and_keep_their_original_labels(result):
    brackets = {
        r["raw_label"]: r["bucket"]
        for r in result["lines"]
        if r["canonical_code"] == "receivable_ageing_bracket" and r["column_period_end"] == COLS[0]
    }
    assert brackets == {
        "Not yet due": "not_due",
        "1-30 days": "1-30",
        "31-90 days": "31-90",
        "91-180 days": "91-180",
        "181-365 days": "181-365",
        "Over 365 days": ">365",
    }


def test_disputed_and_undisputed_status_is_recorded(result):
    q = ne.receivables_quality(result, COLS[0])
    statuses = {d["status"] for d in q["disputed"]}
    assert statuses == {"disputed", "undisputed"}


def test_unrecognised_brackets_are_reported_not_dropped(result):
    q = ne.receivables_quality(result, COLS[0])
    assert "Other" in q["unclassified_brackets"]
    assert any(r["raw_label"] == "Other" for r in result["lines"])  # still kept in the extraction


def test_receivables_ratios_are_computed_from_the_reported_amounts(result):
    q = ne.receivables_quality(result, COLS[0])
    assert q["gross_trade_debts"] == 825.0 and q["ecl_allowance"] == -30.0
    assert q["net_check"] == "match"  # 825 - 30 = 795
    assert q["overdue_percentage"] == pytest.approx(
        325 / 825
    )  # brackets other than not-yet-due, plus 'Other'? no
    assert q["overdue_over_90_ratio"] == pytest.approx(45 / 825)  # 91-180 + 181-365 + over 365
    assert q["ecl_coverage_ratio"] == pytest.approx(30 / 825)


def test_a_missing_amount_gives_no_ratio_not_zero(tmp_path):
    pages = [["12. Trade debts", "Not yet due 500 400", "Trade debts 500 400"]]
    r = ne.extract_notes(pe.extract(write_pdf(tmp_path / "m.pdf", pages)), columns=COLS)
    q = ne.receivables_quality(r, COLS[0])
    assert q["ecl_coverage_ratio"] is None and q["net_trade_debts_computed"] is None
    assert q["overdue_percentage"] is None  # no overdue bracket is reported: absent, not zero


def test_contingent_items_are_partitioned_by_type_and_never_recognised(result):
    rows = [r for r in result["lines"] if r["category"] == "contingencies"]
    assert rows and all(r["recognised"] is False for r in rows)
    assert all(r["canonical_code"] not in BALANCE_SHEET_CODES for r in rows)
    s = ne.contingency_summary(result, COLS[0])
    assert s["recognised_on_balance_sheet"] is False
    assert s["by_type"]["tax"]["total_reported"] == pytest.approx(230.0)
    assert s["by_type"]["guarantee"]["total_reported"] == pytest.approx(50.0)
    assert s["by_type"]["commitment"]["total_reported"] == pytest.approx(30.0)


def test_narrative_litigation_keeps_its_exact_excerpt_and_page(result):
    narrative = [r for r in result["lines"] if r.get("narrative")]
    assert len(narrative) == 1
    n = narrative[0]
    assert n["contingency_type"] == "litigation" and n["page"] == 3 and n["note_ref"] == "20"
    assert n["excerpt"] == _pages()[2][-1]
    assert n["value"] is None  # no figure invented for narrative wording


def test_contingency_types_are_classified_from_their_wording():
    assert ne.classify_contingency("Income tax demands") == "tax"
    assert ne.classify_contingency("Letters of credit issued") == "guarantee"
    assert ne.classify_contingency("Contractual commitments for drilling") == "commitment"
    assert ne.classify_contingency("Suit filed by a supplier") == "litigation"
    assert ne.classify_contingency("Miscellaneous") == "other"
