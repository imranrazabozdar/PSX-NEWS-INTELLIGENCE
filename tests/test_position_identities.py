"""Identity checks by coordinates: interim IS column, equity without circularity, A=L+E and PBT-tax=PAT.

Every figure is SYNTHETIC. Rules under test: a four-column interim income statement resolves to the right
period column from its header; total equity comes from the SOCE closing balance and from the balance-sheet
components, never from assets minus liabilities; neither source available blocks the identity.
"""

from __future__ import annotations

from engines import layout_words as lw
from engines import position_identities as pid


def word(text: str, x1: float, top: float) -> lw.Word:
    return lw.Word(text=text, x0=x1 - 4 * len(text), x1=x1, top=top, chars=len(text))


def row(label: str, cells: dict[int, str], top: float = 100.0) -> lw.Row:
    r = lw.Row(top=top, label=label)
    for band, text in cells.items():
        r.cells[band] = (text, 300.0 + band * 60, top)
    return r


BANDS = [(245.0, 3), (307.0, 3), (367.0, 3), (430.0, 3)]  # four interim income-statement columns


def test_a_four_column_interim_income_statement_resolves_to_the_correct_period_column():
    header = [
        word("Quarter", 257, 77), word("ended", 277, 77),
        word("Halfyear", 380, 77), word("ended", 400, 77),
        word("2025", 232, 99), word("2024", 294, 99), word("2025", 354, 99), word("2024", 416, 99),
    ]
    roles = pid.period_group_columns(header, BANDS)
    assert roles[0] == {"group": "quarter", "role": "current"}  # current quarter
    assert roles[1] == {"group": "quarter", "role": "prior"}  # prior-year quarter
    assert roles[2] == {"group": "half_year", "role": "current"}  # current half-year to date
    assert roles[3] == {"group": "half_year", "role": "prior"}  # prior-year half-year to date
    rows = [
        row("Profit before income tax", {2: "3,044,065"}),
        row("Taxation", {2: "(1,278,803)"}),
        row("Profit after taxation", {2: "1,765,262"}),
    ]
    result = pid.tax_identity(rows, 2)
    assert result["status"] == "reconciled" and result["delta"] == 0


def test_total_equity_from_the_soce_closing_balance_is_an_independent_source():
    soce = [row("Balance as at September 30, 2025", {0: "51,341,467"})]
    eq = pid.total_equity([], 0, soce=pid.soce_closing_equity(soce, 0))
    assert eq["source"] == "soce_only" and eq["value"] == 51341467


def test_total_equity_from_components_agreeing_with_the_soce_is_a_real_cross_check():
    bs = [
        row("Share capital", {0: "799,666"}),
        row("Reserves", {0: "4,407,382"}),
        row("Surplus on revaluation of land", {0: "46,134,419"}),
    ]
    soce = [row("Balance as at September 30, 2025", {0: "51,341,467"})]
    eq = pid.total_equity(bs, 0, soce=pid.soce_closing_equity(soce, 0))
    assert eq["source"] == "both_agree" and eq["value"] == 51341467


def test_neither_equity_source_available_is_requires_review_and_never_reconciled():
    bs = [
        row("Total assets", {0: "155,815,229"}),
        row("Total liabilities", {0: "104,473,762"}),
    ]
    result = pid.balance_identity(bs, 0)
    assert result["equity"]["source"] == "none"
    # not reconciled and not insufficient: there is nothing independent to test against
    assert result["status"] == "requires_review"


def test_balance_identity_reconciles_on_independent_equity_and_flags_a_single_source():
    bs = [
        row("Total assets", {0: "155,815,229"}),
        row("Total liabilities", {0: "104,473,762"}),
        row("Share capital", {0: "799,666"}),
        row("Reserves", {0: "4,407,382"}),
        row("Surplus on revaluation of land", {0: "46,134,419"}),
    ]
    result = pid.balance_identity(bs, 0)
    assert result["status"] == "reconciled" and result["delta"] == 0
    assert result["flag"] == "equity from components_only"


def test_a_disagreeing_equity_source_blocks_the_identity():
    bs = [
        row("Total assets", {0: "155,815,229"}),
        row("Total liabilities", {0: "104,473,762"}),
        row("Share capital", {0: "799,666"}),
        row("Reserves", {0: "4,407,382"}),
    ]
    soce = [row("Balance as at September 30, 2025", {0: "51,341,467"})]
    result = pid.balance_identity(bs, 0, soce_rows=soce)
    assert result["equity"]["source"] == "disagree"
    assert result["status"] == "requires_review"
