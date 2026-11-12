"""Income-statement identity with the printed sign of the tax figure. SYNTHETIC figures, in printed units.

Profit before tax and the tax figure give profit after tax: a charge reduces profit, a credit increases it.
The presentation's sign decides which, and the printed profit after tax settles it."""

from engines import statement_reconciliation as rec


def _check(pbt, tax, pat):
    return rec.income_statement(
        "2026-06-30", {"profit_before_tax": pbt, "taxation": tax, "profit_after_tax": pat}
    )


def test_a_tax_charge_printed_as_a_plain_positive_figure_reconciles():
    c = _check(100.0, 10.0, 90.0)
    assert c.status == rec.RECONCILED and c.discrepancy == 0.0
    assert c.basis.startswith("tax charge")


def test_a_tax_charge_printed_in_brackets_reconciles():
    c = _check(100.0, -10.0, 90.0)
    assert c.status == rec.RECONCILED and c.discrepancy == 0.0


def test_a_tax_credit_increases_profit_and_reconciles():
    """The case the absolute-value rule misreads: a credit of 5 on profit before tax of 100 gives 105."""
    c = _check(100.0, 5.0, 105.0)
    assert c.status == rec.RECONCILED and c.discrepancy == 0.0
    assert c.basis.startswith("tax figure signed as printed")


def test_a_credit_printed_in_brackets_is_a_charge_and_the_mismatch_is_disclosed():
    """Printed as (5) the figure is a charge: profit should fall to 95, not rise to 105. The statement says
    105, so the identity is not forced to pass; the delta is stored."""
    c = _check(100.0, -5.0, 105.0)
    assert c.status == rec.UNRECONCILED and c.discrepancy == 10.0


def test_zero_tax_reconciles():
    assert _check(100.0, 0.0, 100.0).status == rec.RECONCILED


def test_a_profit_that_matches_neither_convention_is_an_exception_with_its_delta():
    c = _check(100.0, 10.0, 70.0)
    assert c.status == rec.UNRECONCILED and c.discrepancy == -20.0  # reported minus expected


def test_missing_tax_is_insufficient_not_zero():
    c = rec.income_statement(
        "2026-06-30", {"profit_before_tax": 100.0, "taxation": None, "profit_after_tax": 90.0}
    )
    assert c.status == rec.INSUFFICIENT and c.discrepancy is None


def test_the_printed_ubl_unconsolidated_profit_statement_reconciles_exactly():
    """UBL 2025 prints tax as a plain positive charge (PKR thousand)."""
    assert _check(288270069.0, 160261222.0, 128008847.0).status == rec.RECONCILED


def test_the_printed_ubl_consolidated_profit_statement_reconciles_within_rounding():
    """UBL 2025 consolidated (US$ thousand): 1,039,213 - 575,058 = 464,155 against a printed 464,154. The one
    printed unit of difference is within the rounding allowance and is recorded as such."""
    assert _check(1039213.0, 575058.0, 464154.0).status == rec.ROUNDED
