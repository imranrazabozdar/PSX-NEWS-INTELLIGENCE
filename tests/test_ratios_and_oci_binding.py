"""Core ratios (partitioned by framework), OCI parent binding, and the IAS 7 status separated from arithmetic.

Synthetic figures and synthetic text laid out like the printed statements.
"""

from __future__ import annotations

from engines import cash_equivalents as ce
from engines import ratios
from engines import statement_pipeline as sp
from engines.financials import parse_statement_text

CORP = {
    "gross_profit": 50.0,
    "revenue": 100.0,
    "profit_after_tax": 20.0,
    "cfo": 30.0,
    "total_current_assets": 80.0,
    "total_current_liabilities": 40.0,
    "trade_receivables": 10.0,
}


def _by(out, key):
    return next(r for r in out if r["key"] == key)


def test_corporate_ratios_compute_and_carry_formula_inputs_and_validation():
    out = ratios.compute_ratios("corporate", CORP, {"revenue": ["IS:IS:5"]})
    gm = _by(out, "gross_margin")
    assert gm["value"] == 0.5 and gm["status"] == "COMPUTED" and gm["validation"] == "VALID"
    assert gm["formula"] == "gross_profit / revenue"
    assert gm["inputs"]["revenue"]["line_item_ids"] == ["IS:IS:5"]
    assert _by(out, "current_ratio")["value"] == 2.0
    assert _by(out, "trade_debt_days")["value"] == 36.5  # 10 / 100 * 365
    assert _by(out, "ocf_to_pat")["value"] == 1.5


def test_a_missing_input_is_null_with_a_reason_never_zero():
    v = {**CORP, "trade_receivables": None}
    out = ratios.compute_ratios("corporate", v)
    d = _by(out, "trade_debt_days")
    assert d["value"] is None and d["status"] == "NOT_COMPUTED" and "trade_receivables" in d["reason"]


def test_zero_denominator_and_non_positive_pat_are_not_computed():
    out = ratios.compute_ratios("corporate", {**CORP, "revenue": 0.0})
    assert _by(out, "gross_margin")["validation"] == "ZERO_DENOMINATOR"
    out = ratios.compute_ratios("corporate", {**CORP, "profit_after_tax": -5.0})
    assert _by(out, "ocf_to_pat")["validation"] == "NOT_MEANINGFUL"


def test_ratio_sets_are_partitioned_by_framework():
    assert {r["key"] for r in ratios.compute_ratios("corporate", CORP)}.isdisjoint(
        {"cost_to_income", "adr", "roa", "roe"}
    )
    bank = {
        "non_markup_expenses": 135.0,
        "net_interest_income": 361.0,
        "non_markup_income": 58.0,
        "advances_net": 1369.0,
        "deposits": 5168.0,
        "profit_after_tax": 128.0,
        "total_assets": 12620.0,
        "total_equity": 498.0,
    }
    out = ratios.compute_ratios("bank", bank)
    assert {r["key"] for r in out} == {"cost_to_income", "adr", "roa", "roe"}
    assert _by(out, "cost_to_income")["value"] == round(135 / (361 + 58), 6)
    assert _by(out, "adr")["value"] == round(1369 / 5168, 6)
    assert ratios.compute_ratios("corporate", bank) == [] or all(
        r["key"] not in ("roa", "roe") for r in ratios.compute_ratios("corporate", bank)
    )


def test_arithmetic_is_reconciled_even_when_the_maturity_is_not_verifiable():
    audit = ce.standard_cash_audit(
        bs_cash=100.0,
        cf_closing=500.0,
        components=[{"label": "short-term", "value": 400.0}],
        maturity_text="maturities up to six months",
        source="t",
    )
    assert audit["arithmetic_reconciliation"]["status"] == "RECONCILED"
    assert audit["arithmetic_reconciliation"]["delta"] == 0
    assert audit["ias7_maturity_status"] == "NOT_VERIFIABLE_FROM_DISCLOSURE"


def test_maturity_statuses_are_the_three_allowed_values():
    assert (
        ce.ias7_maturity_status("original maturity of three months or less")["ias7_maturity_status"]
        == "VERIFIED"
    )
    assert (
        ce.ias7_maturity_status("maturity of more than 90 days")["ias7_maturity_status"]
        == "DOES_NOT_MEET_DISCLOSED_MATURITY_CRITERION"
    )
    assert (
        ce.ias7_maturity_status("maturities up to six months")["ias7_maturity_status"]
        == "NOT_VERIFIABLE_FROM_DISCLOSURE"
    )


def test_a_tax_effect_is_bound_to_its_own_parent_and_both_rows_are_kept():
    text = "\n".join(
        [
            "Remeasurement loss of post retirement benefit obligation 23.1.2   (60)   (938)",
            "Deferred tax thereon                                             22    366",
            "Gain on equity instrument at fair value",
            "through other comprehensive income                                 –     28",
            "Deferred tax thereon                                              –    (3)",
        ]
    )
    r = parse_statement_text(text, statement="IS", columns=["2026", "2025"], page=40)
    kids = [ln for ln in r["lines"] if ln["raw_label"].lower().endswith("deferred tax thereon")]
    assert len(kids) == 4  # two rows x two columns, both kept
    parents = {k["context_label"].rsplit(" Deferred tax thereon", 1)[0] for k in kids}
    assert parents == {
        "Remeasurement loss of post retirement benefit obligation",
        "Gain on equity instrument at fair value through other comprehensive income",
    }
    m = sp.load_mappings(framework="corporate")
    codes = {sp.map_label("IS", k["context_label"], m)[0] for k in kids}
    assert codes == {"oci_tax_on_remeasurement", "oci_tax_on_fvoci_equity"}
