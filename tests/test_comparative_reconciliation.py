"""Comparative-period reconciliation: restatement, reclassification and unit or period discrepancies.

Pure-function cases with invented figures, plus one pipeline case. Nothing here overwrites a prior extraction.
"""

from __future__ import annotations

import copy
import hashlib

import pytest

from engines import comparative_reconciliation as cr
from engines import statement_pipeline as sp
from tests.test_statement_pipeline import COLS, _doc, _pdf, _report_pages


def _one(
    prior, comp, *, p_unit=1000, c_unit=1000, p_period="2024-06-30", c_period="2024-06-30", code="revenue"
):
    out = cr.compare(
        {code: prior},
        {code: comp},
        prior_period=p_period,
        printed_period=c_period,
        prior_unit=p_unit,
        current_unit=c_unit,
    )
    return out[0]


def test_identical_amounts_in_the_same_unit_match():
    assert _one(800.0, 800.0)["classification"] == cr.MATCH


def test_the_same_amount_printed_in_a_different_unit_is_not_a_restatement():
    f = _one(800.0, 800_000.0, p_unit=1000, c_unit=1)
    assert f["classification"] == cr.UNIT_PRESENTATION and f["discrepancy"] == pytest.approx(0.0)


def test_one_printed_unit_of_difference_is_rounding():
    assert _one(800.0, 801.0)["classification"] == cr.ROUNDING


def test_a_thousand_fold_gap_in_the_same_printed_unit_is_a_suspected_unit_error():
    assert _one(800.0, 800_000.0)["classification"] == cr.UNIT_SUSPECTED


def test_a_different_amount_is_a_restatement_candidate_with_the_exact_discrepancy():
    f = _one(800.0, 750.0)
    assert f["classification"] == cr.RESTATEMENT and f["discrepancy"] == -50.0


def test_discrepancies_are_reported_in_the_current_filing_printed_unit():
    f = _one(800.0, 750.0, p_unit=1000, c_unit=1)  # 750 is printed in units here, so 800 thousand = 800,000
    assert f["classification"] == cr.RESTATEMENT and f["discrepancy"] == pytest.approx(750.0 - 800_000.0)


def test_a_comparative_column_for_another_period_is_a_period_mismatch():
    f = _one(800.0, 800.0, p_period="2024-06-30", c_period="2024-03-31")
    assert f["classification"] == cr.PERIOD_MISMATCH and f["discrepancy"] is None


def test_a_missing_side_is_not_compared_and_no_difference_is_invented():
    f = _one(800.0, None)
    assert f["classification"] == cr.NOT_COMPARED and f["missing"] == "comparative"
    assert cr.to_checks([f])[0]["status"] == "INSUFFICIENT_DATA"


def test_status_mapping_for_storage():
    statuses = {
        cls: cr.to_checks(
            [
                {
                    "code": "x",
                    "printed_period": "p",
                    "classification": cls,
                    "discrepancy": 0,
                    "reported": 1,
                    "expected": 1,
                    "allowance": 1,
                }
            ]
        )[0]["status"]
        for cls in (
            cr.MATCH,
            cr.UNIT_PRESENTATION,
            cr.ROUNDING,
            cr.RESTATEMENT,
            cr.UNIT_SUSPECTED,
            cr.PERIOD_MISMATCH,
        )
    }
    assert statuses[cr.MATCH] == statuses[cr.UNIT_PRESENTATION] == "RECONCILED"
    assert statuses[cr.ROUNDING] == "RECONCILED_WITH_ROUNDING"
    assert (
        statuses[cr.RESTATEMENT]
        == statuses[cr.UNIT_SUSPECTED]
        == statuses[cr.PERIOD_MISMATCH]
        == "UNRECONCILED"
    )


def test_compare_never_changes_its_inputs():
    prior = {"revenue": 800.0, "total_assets": 900.0}
    comp = {"revenue": 750.0, "total_assets": 900.0}
    p0, c0 = copy.deepcopy(prior), copy.deepcopy(comp)
    cr.compare(
        prior,
        comp,
        prior_period="2024-06-30",
        printed_period="2024-06-30",
        prior_unit=1000,
        current_unit=1000,
    )
    assert prior == p0 and comp == c0


def test_pipeline_flags_a_unit_presentation_difference_as_reconciled(tmp_path):
    """The prior filing is in thousands; this filing prints the prior-year revenue in units. Same amount."""
    mapping = sp.load_mappings()
    prior_pdf = _pdf(tmp_path, "fy24.pdf", _report_pages(revenue=("800", "700")))
    cur_pdf = _pdf(tmp_path, "fy25.pdf", _report_pages(revenue=("1,000,000", "800,000")))
    prior = sp.tag(
        sp.extract(
            prior_pdf, columns=["2024-06-30", "2023-06-30"], statement_pages={"BS": [1], "IS": [2], "CF": [3]}
        ),
        document=_doc(prior_pdf, hashlib.sha256(b"p").hexdigest(), period="2024-06-30"),
        extractor_version="v1",
        mapping=mapping,
    )
    prior["period"] = "2024-06-30"
    cur_doc = _doc(cur_pdf, hashlib.sha256(b"c").hexdigest())
    cur_doc["unit_scale"] = 1  # this filing prints its figures in units
    cur = sp.tag(
        sp.extract(cur_pdf, columns=COLS, statement_pages={"BS": [1], "IS": [2], "CF": [3]}),
        document=cur_doc,
        extractor_version="v1",
        mapping=mapping,
    )
    rev = next(
        c
        for c in sp.reconcile(cur, period_end="2025-06-30", prior=prior)["checks"]
        if c["check"] == "comparative:revenue"
    )
    assert rev["status"] == "RECONCILED" and rev["classification"] == cr.UNIT_PRESENTATION
