# ruff: noqa: E501 - the fixtures are printed-table rows, kept at their printed width
"""Note 21 (trade debts, ageing, circular debt, counterparties), note 41 (cash), and wrapped OCI labels.

Inputs are SYNTHETIC text laid out like the printed notes, with invented figures. They test the logic only.
"""

from __future__ import annotations

from engines import cash_equivalents as ce
from engines import trade_debts_note as tdn
from engines.financials import parse_statement_text

NOTE = [
    "21.   TRADE DEBTS",
    "Un-secured - considered good                                  700,000     650,000",
    "Un-secured - considered doubtful                                   40          30",
    "                                                              700,040     650,030",
    "Provision for doubtful trade debts                               (40)        (30)",
    "                                                              700,000     650,000",
    "21.1  Trade debts include overdue amount of Rs 500 million (2025: Rs 450 million) on account of",
    "inter-corporate circular debt, receivable from oil refineries, gas companies and power producers out",
    "of which Rs 300 million (2025: Rs 280 million) and Rs 150 million (2025: Rs 120 million) are overdue from",
    "related parties, Sui Northern Gas Pipeline Limited and Sui Southern Gas Company Limited respectively.",
    "As disclosed in note 2.1.2, SECP has deferred the applicability of ECL model till financial year ending on or",
    "before 31 December 2026 on debts due directly or ultimately from the GoP in consequence of the circular debt.",
    "22.   LOANS AND ADVANCES",
]
AGEING = [
    "The aging of trade debts at the reporting date was:",
    "                                             Gross debts            Impaired       Gross debts        Impaired",
    "Not past due                                 300,000                    -          280,000               -",
    "Past due 0-30 days                            60,000                    -           50,000               -",
    "Past due 31-60 days                           20,000                    -           20,000               -",
    "Past due 61-90 days                           10,000                    -           10,000               -",
    "Over 90 days                                 310,040                 (40)          290,030             (30)",
    "21                                           700,040                 (40)          650,030             (30)",
]
CP = [
    "The aging of trade debts from related parties at the reporting date was:",
    "Total    Not past due  0-30  31-60  61-90  Over 90  Impaired",
    "Sui Northern Gas Pipelines Limited          200,000   100,000   50,000   20,000   10,000   20,000    -",
    "Sui Southern Gas Company Limited            100,000    40,000   30,000   10,000    5,000   15,000    -",
    "WAPDA                                           -           -        -        -        -        5      (5)",
    "                                            300,000   140,000   80,000   30,000   15,000   40,000   (5)",
]


def test_trade_debts_gross_and_net_are_checked_and_provision_is_negative():
    r = tdn.parse_note_21(NOTE, pages=["33R"])
    y = r["by_year"]["2026"]
    assert y["gross_trade_debts"] == 700_040 and y["net_trade_debts"] == 700_000
    assert y["doubtful_debt_provision"] == -40
    assert {c["status"] for c in r["checks"]} == {"RECONCILED"}


def test_a_net_that_does_not_add_up_is_unreconciled_not_corrected():
    bad = [
        ln.replace("700,000     650,000", "700,001     650,000")
        if "good" not in ln and "700,000" in ln
        else ln
        for ln in NOTE
    ]
    r = tdn.parse_note_21(bad, pages=["33R"])
    assert any(c["status"] == "UNRECONCILED" for c in r["checks"])


def test_circular_debt_overdue_and_counterparty_split_are_read_in_millions():
    c = tdn.parse_circular_debt(NOTE)
    assert c["overdue_total"] == {"2026": 500.0, "2025": 450.0}
    assert c["overdue_from_sngpl"]["2026"] == 300.0 and c["overdue_from_ssgc"]["2026"] == 150.0
    assert c["other_overdue"]["2026"] == 50.0  # the remainder, not attributed to a named counterparty


def test_ecl_deferral_is_recorded_and_the_doubtful_provision_is_not_ecl():
    e = tdn.ecl_treatment(NOTE, pages=["33R"])
    assert e["ecl_model_deferred_for_gop_linked_debts"] is True
    assert e["deferral_deadline"] == "31 December 2026"
    assert e["doubtful_debt_provision_is_ecl"] is False and e["ecl_allowance"] is None


def test_ageing_buckets_sum_to_the_printed_total_and_over_365_is_null_when_not_disclosed():
    a = tdn.parse_ageing(AGEING, pages=["42L"])
    b = a["by_year"]["2026"]
    assert b["gross_by_bucket"]["over_90"] == 310_040
    assert b["over_365"] is None and b["over_365_disclosed"] is False
    assert all(c["status"] == "RECONCILED" for c in a["checks"])


def test_ageing_bucket_that_does_not_sum_is_flagged():
    bad = [ln.replace("310,040", "310,041") if ln.startswith("Over 90") else ln for ln in AGEING]
    a = tdn.parse_ageing(bad, pages=["42L"])
    assert any(c["status"] == "UNRECONCILED" for c in a["checks"])


def test_counterparty_rows_are_separate_and_sum_to_their_total():
    cp = tdn.parse_counterparties(CP, pages=["42R"])
    keys = [r["key"] for r in cp["rows"]]
    assert keys == ["sngpl", "ssgc", "wapda"]
    assert cp["printed_total_2026"] == 300_000 and cp["kept_separate_from_trade_debts"] is True
    assert all(c["status"] == "RECONCILED" for c in cp["checks"])
    wapda = cp["rows"][2]
    assert wapda["total_2026"] is None and wapda["impaired"] == -5  # nil total is not turned into zero


def test_note_41_explains_the_cash_difference_with_term_deposits():
    n41 = ce.parse_note_41(
        [
            "41.",
            "CASH AND CASH EQUIVALENTS",
            "Cash and bank balances                                    27       100        90",
            "Short term highly liquid investments - Term deposits      26       400       300",
            "                                                                   500       390",
        ],
        pages=["46L"],
    )
    assert (
        n41["rows"]["term_deposits"]["2026"] == 400 and n41["rows"]["cash_and_bank_balances"]["note"] == "27"
    )
    assert all(c["status"] == "RECONCILED" for c in n41["checks"])
    mat = ce.maturity_terms(["having maturities up to six months (2025: six months)."], pages=["36"])
    r = ce.reconcile_cash(bs_cash=100, cf_closing=500, note41=n41, maturity=mat)
    assert r["status"] == "EXPLAINED" and r["residual"] == 0
    assert r["ias7_cash_equivalent_test"].startswith("NOT_VERIFIABLE_FROM_DISCLOSURE")


def test_cash_difference_not_explained_by_note_41_is_reported_not_forced():
    n41 = {
        "status": "parsed",
        "rows": {
            "cash_and_bank_balances": {"2026": 100},
            "term_deposits": {"2026": 400},
            "total": {"2026": 500},
        },
    }
    mat = {"max_maturity_months": 3}
    r = ce.reconcile_cash(bs_cash=100, cf_closing=550, note41=n41, maturity=mat)
    assert r["status"] == "NOT_EXPLAINED" and r["residual"] == 50
    assert r["ias7_cash_equivalent_test"].startswith("CONSISTENT")


def test_missing_inputs_are_insufficient_data_never_zero():
    r = ce.reconcile_cash(bs_cash=None, cf_closing=500, note41={"status": "not_found"}, maturity={})
    assert r["status"] == "INSUFFICIENT_DATA"


def test_wrapped_oci_label_whose_second_line_carries_figures_is_one_label():
    text = (
        "Share of effect of translation of investment in foreign associated\n"
        "company of the associates - net of taxation     (848,606)   (4,108,356)"
    )
    r = parse_statement_text(text, statement="IS", columns=["2026-06-30", "2025-06-30"], page=9)
    labels = {ln["raw_label"] for ln in r["lines"]}
    assert labels == {
        "Share of effect of translation of investment in foreign associated "
        "company of the associates - net of taxation"
    }
    assert [ln["value"] for ln in r["lines"]] == [-848_606.0, -4_108_356.0]
