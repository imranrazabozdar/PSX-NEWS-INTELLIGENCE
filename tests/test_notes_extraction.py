"""Notes and disclosures extraction on SYNTHETIC pages with invented figures. Logic tests only."""

from __future__ import annotations

from engines import notes_extraction as ne
from engines import pdf_extraction as pe
from tests.pdf_fixture_builder import write_pdf

COLS = ["2025-06-30", "2024-06-30"]


def _pages():
    return [
        [
            "12. Trade debts",
            "Trade debts 120 90",
            "Expected credit loss allowance (12) (10)",
            "Net trade debts 108 80",
            "Less than 30 days 70 60",
        ],
        [
            "Note 15 Borrowings",
            "Long term financing 50 40",
            "Short term borrowings 30 20",
            "Current portion of long term financing 10 10",
            "Finance cost accrued 4 3",
        ],
        ["18. Trade and other payables", "Creditors 40 35", "Accrued liabilities 12 10"],
        ["20. Contingencies and commitments", "Guarantees issued by banks 50 40"],
        [
            "25. Segment information",
            "Revenue - Exploration 600 500",
            "Operating profit - Exploration 200 180",
        ],
    ]


def _doc(tmp_path):
    pdf = write_pdf(tmp_path / "notes.pdf", _pages())
    return pe.extract(pdf)


def _find(result, label, column="2025-06-30"):
    return [r for r in result["lines"] if r["raw_label"] == label and r["column_period_end"] == column]


def test_each_note_category_is_found_with_its_note_number_and_page(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    found = {(n["note_no"], n["category"], n["page"]) for n in r["notes"]}
    assert found == {
        ("12", "trade_receivables", 1),
        ("15", "borrowings", 2),
        ("18", "trade_payables", 3),
        ("20", "contingencies", 4),
        ("25", "segment_reporting", 5),
    }


def test_every_line_keeps_page_note_label_period_and_extractor_version(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    assert r["lines"]
    for ln in r["lines"]:
        assert ln["statement"] == "NOTE" and ln["page"] and ln["note_ref"] and ln["raw_label"]
        assert ln["column_period_end"] in COLS
        assert ln["extractor_version"] == ne.EXTRACTOR_RULE_VERSION
        assert ln["value"] is not None  # a row without a figure is not stored as zero


def test_receivables_ecl_allowance_is_negative_as_printed_and_net_is_not_mapped_as_gross(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    ecl = _find(r, "Expected credit loss allowance")[0]
    assert ecl["value"] == -12.0 and ecl["canonical_code"] == "ecl_allowance" and ecl["confidence"] == 0.8
    net = _find(r, "Net trade debts")[0]
    assert net["canonical_code"] == "trade_receivables_net"
    gross = _find(r, "Trade debts")[0]
    assert gross["canonical_code"] == "trade_receivables_gross" and gross["note_ref"] == "12"


def test_short_term_and_long_term_borrowings_are_split_and_current_portion_is_not_long_term(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    assert _find(r, "Long term financing")[0]["canonical_code"] == "long_term_borrowings"
    assert _find(r, "Short term borrowings")[0]["canonical_code"] == "short_term_borrowings"
    assert (
        _find(r, "Current portion of long term financing")[0]["canonical_code"]
        == "current_portion_of_long_term_debt"
    )
    assert _find(r, "Finance cost accrued")[0]["canonical_code"] == "finance_cost"


def test_unmapped_disclosures_are_kept_with_no_code_and_no_guessed_confidence(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    creditors = _find(r, "Creditors")[0]
    assert creditors["canonical_code"] is None and creditors["confidence"] is None
    assert creditors["category"] == "trade_payables" and creditors["value"] == 40.0
    guarantees = _find(r, "Guarantees issued by banks")[0]
    assert guarantees["canonical_code"] is None and guarantees["category"] == "contingencies"
    assert _find(r, "Accrued liabilities")[0]["canonical_code"] == "accrued_liabilities"


def test_segment_revenue_and_operating_profit_are_identified(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    assert _find(r, "Revenue - Exploration")[0]["canonical_code"] == "segment_revenue"
    assert _find(r, "Operating profit - Exploration")[0]["canonical_code"] == "segment_operating_profit"


def test_summary_counts_mapped_and_unmapped_and_drops_nothing(tmp_path):
    r = ne.extract_notes(_doc(tmp_path), columns=COLS)
    s = ne.summary_by_category(r)
    total_lines = sum(v["lines"] for v in s.values())
    assert total_lines == len(r["lines"])
    assert all(v["mapped"] + v["unmapped"] == v["lines"] for v in s.values())
    assert s["contingencies"]["unmapped"] >= 1


def test_text_that_is_not_under_a_recognised_note_is_not_extracted(tmp_path):
    pdf = write_pdf(tmp_path / "other.pdf", [["7. Accounting policies", "Revenue recognised 999 888"]])
    r = ne.extract_notes(pe.extract(pdf), columns=COLS)
    assert r["lines"] == [] and r["notes"] == []
