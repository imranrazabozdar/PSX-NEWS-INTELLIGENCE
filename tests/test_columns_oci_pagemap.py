"""Column-aware KAM parsing, OCI and total comprehensive income, owner page map, and bank/corporate isolation.

Inputs are SYNTHETIC hand-written word coordinates and hand-set figures, testing the logic only. Real-report
figures with page references are pinned in tests/test_real_report_regression.py.
"""

from __future__ import annotations

import json

import pytest

from engines import page_layout as pl
from engines import statement_pipeline as sp
from engines import statement_reconciliation as rec
from scripts.financial_intake import _page_list, parse_page_map


def w(text, x0, top, width=None):
    width = width if width is not None else 6.0 * len(text)
    return {
        "text": text,
        "x0": float(x0),
        "x1": float(x0 + width),
        "top": float(top),
        "bottom": float(top + 8),
    }


def kam_page_words():
    """A KAM table laid out in columns: KAM (x 24), response (x 160), auditor text to the right (x 340)."""
    return [
        w("Key", 24, 250),
        w("audit", 50, 250),
        w("matters", 84, 250),
        w("How", 160, 250),
        w("the", 185, 250),
        w("matter", 210, 250),
        w("was", 245, 250),
        w("addressed", 270, 250),
        w("in", 310, 250),
        w("our", 330, 250),  # header words inside the table
        w("1.", 24, 262),
        w("Expected", 40, 262, 36),
        w("credit", 84, 262, 24),
        w("loss", 112, 262, 16),
        w("against", 130, 262, 18),
        w("advances", 150, 262, 30),  # the heading stays inside the KAM column
        w("As", 24, 276),
        w("disclosed", 42, 276),
        w("in", 96, 276),
        w("Note", 110, 276),
        w("9", 140, 276),
        w("We", 160, 280),
        w("obtained", 178, 280),
        w("an", 224, 280),
        w("understanding", 240, 280),
        w("Auditor’s", 340, 268),
        w("Responsibilities", 400, 268),  # the auditor's text, must be excluded
        w("The", 340, 282),
        w("Board", 365, 282),
        w("Information", 24, 470),
        w("Other", 90, 470),  # the table ends here (full-width section)
    ]


def test_columns_are_split_by_word_position_not_reading_order():
    cols = [pl.Column("kam", 20, 153), pl.Column("response", 153, 324)]
    buckets = pl.split_columns(kam_page_words(), cols)
    assert "Expected" in [x["text"] for x in buckets["kam"]]
    assert "obtained" in [x["text"] for x in buckets["response"]]
    assert "Board" not in [x["text"] for x in buckets["kam"] + buckets["response"]]  # right column, excluded


def test_kam_table_is_found_with_boundaries_and_bottom_edge():
    layout = pl.kam_table_layout(kam_page_words())
    assert layout is not None
    assert [c.name for c in layout["columns"]] == ["kam", "response"]
    assert layout["bottom"] == pytest.approx(470.0)


def test_kam_heading_note_references_and_page_evidence_are_extracted():
    r = pl.parse_kam_table(kam_page_words(), 42)
    k = r["kams"][0]
    assert k["heading"] == "Expected credit loss against advances"
    assert k["number"] == 1 and k["page"] == 42
    assert k["note_references"] == ["9"]
    assert "As disclosed in Note 9" in k["disclosure"]
    assert k["audit_response"].startswith("We obtained an understanding")
    assert "Auditor" not in k["audit_response"] and "Board" not in k["audit_response"]


def test_no_kam_table_means_no_kams_and_no_invented_headings():
    notes_only = [w("Note", 24, 100), w("1.", 24, 120), w("GENERAL", 40, 120), w("INFORMATION", 90, 120)]
    assert pl.kam_table_layout(notes_only) is None
    assert pl.parse_kam_table(notes_only, 80) is None


def test_numbered_note_heading_is_not_taken_as_a_kam_outside_the_table():
    words = kam_page_words() + [w("1.", 24, 520), w("STATUS", 40, 520), w("AND", 90, 520)]
    kams = pl.parse_kam_table(words, 42)["kams"]
    assert [k["heading"] for k in kams] == ["Expected credit loss against advances"]


def test_note_references_tolerate_letter_spacing_and_split_decimals():
    assert pl._note_refs("in N o te 9.4 to the") == {"9.4"}
    assert pl._note_refs("Notes 9 . 4 and 9") == {"9.4", "9"}
    assert pl._note_refs("the Bank in 9.4 only") == set()  # no "Note" word, no reference


def test_letter_spaced_passage_is_flagged_not_quoted_as_exact():
    spaced = "we i d e n t i f i e d a d e q u a c y and completeness of ECL"
    assert pl._text_quality(spaced) == "letter_spaced_or_overlapped"
    assert pl._text_quality("We identified adequacy and completeness of ECL against advances.") == "clean"


# ------------------------------------------------------------------ OCI and total comprehensive income

# Printed in the UBL Annual Report 2025 (owner upload 04688c48): profit after tax 128,008,847 and total
# comprehensive income 237,707,671 on PDF page 44; other comprehensive income, net of tax, 109,698,824 on PDF
# page 45. Pinned against the fixture text in tests/test_real_report_regression.py.
UBL_OCI = {"profit_after_tax": 128_008_847.0, "other_comprehensive_income": 109_698_824.0}


def test_total_comprehensive_income_identity_reconciles_on_the_ubl_figures():
    v = {**UBL_OCI, "total_comprehensive_income": 237_707_671.0}
    c = rec.comprehensive_income("2025-12-31", v)
    assert c.status == rec.RECONCILED and c.discrepancy == 0


def test_total_comprehensive_income_difference_is_shown_not_hidden():
    v = {**UBL_OCI, "total_comprehensive_income": 237_707_000.0}
    c = rec.comprehensive_income("2025-12-31", v)
    assert c.status == rec.UNRECONCILED and c.discrepancy == pytest.approx(-671.0)


def _oci_line(code, value, col="2025-12-31"):
    return {
        "statement_type": "OCI",
        "canonical_code": code,
        "column_period_end": col,
        "reported_amount": value,
    }


def test_oci_total_is_the_sum_of_mapped_components_and_missing_oci_does_not_run_the_check():
    lines = [
        _oci_line("oci_translation", 508_221.0),
        _oci_line("oci_debt_fvoci", 93_877_970.0),
        _oci_line("oci_equity_fvoci", 3_213_232.0),
        _oci_line("oci_remeasurement_defined_benefit", 12_099_401.0),
    ]
    assert sp._oci_total(lines, "2025-12-31") == 109_698_824.0
    assert sp._oci_total([], "2025-12-31") is None  # no OCI mapped: nothing is assumed to be zero


def test_reconcile_runs_the_comprehensive_income_check_when_oci_is_present():
    lines = [
        {
            "statement_type": "IS",
            "canonical_code": "profit_after_tax",
            "column_period_end": "2025-12-31",
            "reported_amount": 128_008_847.0,
            "unit_scale": 1000,
        }
    ]
    lines += [
        _oci_line("oci_translation", 508_221.0),
        _oci_line("oci_debt_fvoci", 93_877_970.0),
        _oci_line("oci_equity_fvoci", 3_213_232.0),
        _oci_line("oci_remeasurement_defined_benefit", 12_099_401.0),
        {
            "statement_type": "OCI",
            "canonical_code": "total_comprehensive_income",
            "column_period_end": "2025-12-31",
            "reported_amount": 237_707_671.0,
            "unit_scale": 1000,
        },
    ]
    out = sp.reconcile({"lines": lines}, period_end="2025-12-31")
    names = {c["check"]: c["status"] for c in out["checks"]}
    assert names["comprehensive_income"] == rec.RECONCILED


def test_oci_codes_exist_only_in_the_bank_framework():
    bank = sp.load_mappings(framework="bank")
    corp = sp.load_mappings(framework="corporate")
    # OCI is printed in the statement of profit or loss and other comprehensive income: stored as IS
    assert (
        sp.map_label(
            "IS", "Movement in surplus on revaluation of debt investments through FVOCI - net of tax", bank
        )[0]
        == "oci_debt_fvoci"
    )
    assert (
        sp.map_label("IS", "Total comprehensive income for the year", bank)[0] == "total_comprehensive_income"
    )
    assert sp.map_label(
        "IS", "Movement in surplus on revaluation of debt investments through FVOCI - net of tax", corp
    ) == (None, None)
    # the corporate table has its own OCI lines; the bank's FVOCI and translation codes never appear there
    corp_codes = set(sp.load_mappings(framework="corporate").get("IS", {}).values())
    assert "oci_debt_fvoci" not in corp_codes and "oci_translation" not in corp_codes


def test_bank_working_capital_labels_never_map_under_corporate_rules():
    corp = sp.load_mappings(framework="corporate")
    for label in (
        "Net cash flow generated from operating activities",
        "Balances with other banks",
        "Mark-up / return / interest earned",
        "Net mark-up / interest income",
    ):
        for st in ("BS", "IS", "CF"):
            assert sp.map_label(st, label, corp) == (None, None), (st, label)


def test_fx_effect_on_cash_is_part_of_the_bank_cash_flow_identity():
    bank = sp.load_mappings(framework="bank")
    assert (
        sp.map_label("CF", "Effect of exchange rate changes on cash and cash equivalents", bank)[0]
        == "fx_effect_on_cash"
    )
    v = {
        "opening_cash": 368_320_156.0,
        "net_change_in_cash": 235_112_499.0,
        "fx_effect_on_cash": 1_394_001.0,
        "closing_cash": 604_826_656.0,
    }
    assert rec.cash_flow("2025-12-31", v).status == rec.RECONCILED


# ------------------------------------------------------------------ owner page map


def _write_map(tmp_path, data):
    p = tmp_path / "map.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_page_map_gives_statement_regions_auditor_and_kam_pages(tmp_path):
    m = parse_page_map(
        _write_map(
            tmp_path,
            {
                "BS": "43R",
                "IS": "44L",
                "OCI": "44R",
                "CF": "45R",
                "EQ": "45L",
                "AUDITOR": "41-42",
                "KAM": "42",
            },
        )
    )
    assert m["statement_regions"]["OCI"] == (44, "R")
    assert m["statement_pages"]["BS"] == [43]
    assert m["auditor_pages"] == [41, 42]
    assert m["kam_pages"] == [(42, "")]


@pytest.mark.parametrize(
    "bad", [{"NOTES": "10"}, {"BS": "0"}, {"BS": "43X"}, {"AUDITOR": "42-41"}, {"KAM": "a"}]
)
def test_bad_page_map_entries_are_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        parse_page_map(_write_map(tmp_path, bad))


def test_page_map_must_be_an_object(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        parse_page_map(p)


def test_page_list_expands_ranges_and_lists():
    assert _page_list("41-43, 45", "AUDITOR") == [41, 42, 43, 45]


# ------------------------------------------------------------------ corporate taxonomy, spreads (OGDC)


def test_statement_spec_accepts_several_regions_of_one_spread():
    from scripts.financial_intake import parse_statement_spec

    pages, regions = parse_statement_spec("BS=8L+8R,IS=9L,OCI=9R")
    assert pages == {"BS": [8], "IS": [9], "OCI": [9]}
    assert regions == {"BS": [(8, "L"), (8, "R")], "IS": (9, "L"), "OCI": (9, "R")}


def test_corporate_total_assets_and_equity_are_inferred_from_their_components():
    cols = ["2026-06-30"]

    def row(code, value):
        return {
            "statement_type": "BS",
            "canonical_code": code,
            "column_period_end": cols[0],
            "reported_amount": value,
            "pdf_page_number": 8,
        }

    tagged = [
        row("ppe", 600.0),
        row("trade_receivables", 400.0),
        row("share_capital", 100.0),
        row("reserves", 50.0),
        row("unappropriated_profit", 850.0),
    ]
    unparsed = [{"statement": "BS", "line": "1,000", "page": 8, "extraction_engine": "x"}]
    out = sp.infer_unlabelled_totals(tagged, unparsed, columns=cols, framework="corporate")
    got = {(r["canonical_code"], r["reported_amount"]) for r in out}
    # both groups print a total equal to their components here (equity: 100 + 50 + 850)
    assert ("total_assets", 1000.0) in got and ("total_equity", 1000.0) in got
    unparsed_eq = [{"statement": "BS", "line": "2,000", "page": 8, "extraction_engine": "x"}]
    assert sp.infer_unlabelled_totals(tagged, unparsed_eq, columns=cols, framework="corporate") == []


def test_repeated_printed_total_on_both_halves_is_one_total():
    cols = ["2026-06-30"]
    tagged = [
        {
            "statement_type": "BS",
            "canonical_code": "ppe",
            "column_period_end": cols[0],
            "reported_amount": 1000.0,
            "pdf_page_number": 8,
        }
    ]
    unparsed = [
        {"statement": "BS", "line": "1,000", "page": 8, "extraction_engine": "x"},
        {"statement": "BS", "line": "1,000", "page": 8, "extraction_engine": "x"},
    ]
    out = sp.infer_unlabelled_totals(tagged, unparsed, columns=cols, framework="corporate")
    assert [r["canonical_code"] for r in out] == ["total_assets"]


def test_income_statement_identity_uses_the_tax_as_an_expense_of_its_printed_size():
    v_bracketed = {
        "profit_before_tax": 259_134_869.0,
        "taxation": -16_761_223.0,
        "profit_after_tax": 242_373_646.0,
    }
    v_plain = {
        "profit_before_tax": 288_270_069.0,
        "taxation": 160_261_222.0,
        "profit_after_tax": 128_008_847.0,
    }
    assert rec.income_statement("2026", v_bracketed).status == rec.RECONCILED
    assert rec.income_statement("2025", v_plain).status == rec.RECONCILED
    bad = {"profit_before_tax": 259_134_869.0, "taxation": -16_761_223.0, "profit_after_tax": 242_000_000.0}
    assert rec.income_statement("2026", bad).status == rec.UNRECONCILED


def test_kam_column_starts_at_the_s_no_column_and_half_pages_are_read_separately():
    # the "S. No." number sits left of the "Key audit matters" text; it must still belong to the KAM column
    words = [
        w("S.", 343, 446),
        w("No.", 360, 446),
        w("Key", 380, 446),
        w("audit", 402, 446),
        w("matters", 430, 446),
        w("How", 473, 446),
        w("the", 495, 446),
        w("matter", 515, 446),
        w("was", 548, 446),
        w("addressed", 565, 446),
        w("1.", 344, 456),
        w("Over", 358, 456),
        w("due", 386, 456),
        w("trade", 412, 456),
        w("debts", 446, 456),
        w("(Refer", 358, 470),
        w("notes", 396, 470),
        w("2.4.10,", 430, 470),
        w("21.1)", 440, 470),
        w("Our", 473, 456),
        w("procedures", 495, 456),
    ]
    r = pl.parse_kam_table(words, 5)
    assert r is not None and r["kams"][0]["heading"] == "Over due trade debts"
    assert r["kams"][0]["note_references"] == ["2.4.10", "21.1"]


def test_heading_continuation_only_for_wrapped_lowercase_lines():
    words = kam_page_words()
    # a capital-letter sentence right after the heading is disclosure text, not part of the heading
    words = [x for x in words if x["text"] != "against"] + [w("Note", 24, 276)]
    k = pl.parse_kam_table(kam_page_words(), 42)["kams"][0]
    assert "As disclosed" in k["disclosure"] and "As disclosed" not in k["heading"]


def test_dotted_note_references_survive_letter_spacing():
    assert pl._note_refs("Refer notes 3 . 1 1 , 3 .1 2 , 2 8 and 30") == {"3.11", "3.12", "28", "30"}
    assert pl._note_refs("Refer notes 2.4.10, 19.2 and 21.1") == {"2.4.10", "19.2", "21.1"}
