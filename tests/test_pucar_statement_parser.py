"""Tests for engines/pucar_statement_parser.py.

All fixtures are SYNTHETIC: fictitious symbols and invented round figures laid out the way PUCAR
letterheads print them. They are not PSX data and must not be read as any company's results.
"""

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from engines.pucar_statement_parser import PucarFinancialResult, parse_number, parse_pucar_text

FIXTURES = Path(__file__).parent / "fixtures" / "pucar"

# Manufacturing, quarterly, profitable. Units printed in thousands.
MANUFACTURING_Q = """\
SYNTHETIC TEST FIXTURE - NOT PSX DATA
Statement of Profit or Loss (Un-audited)
For the quarter ended March 31, 2026
Rupees in thousand
                                       Quarter ended            Nine months ended
                                   Mar 31, 2026  Mar 31, 2025   Mar 31, 2026  Mar 31, 2025
Sales - net                           1,250,000     1,100,000      3,600,000     3,300,000
Cost of sales                          (950,000)     (870,000)    (2,700,000)   (2,500,000)
Gross profit                            300,000       230,000        900,000       800,000
Distribution cost                       (20,000)      (18,000)       (60,000)      (55,000)
Operating profit                        200,000       150,000        600,000       560,000
Finance cost                            (30,000)      (40,000)       (90,000)     (120,000)
Profit before taxation                  170,000       110,000        510,000       440,000
Taxation                                (40,000)      (25,000)      (120,000)     (100,000)
Profit after taxation                   130,000        85,000        390,000       340,000
Earnings per share - basic and diluted     2.31          1.51           6.93          6.04
"""

# Bank, half year. Note references printed before the figures. Mark-up income label variant.
BANK_HALF = """\
SYNTHETIC TEST FIXTURE - NOT PSX DATA
Profit and Loss Account (Un-audited)
For the half year ended June 30, 2026
Rupees in thousand
                                              Note   Half year ended        Quarter ended
                                                       2026        2025      2026        2025
Net mark-up / interest income                  17  45,600,000  40,100,000  23,100,000  20,300,000
Non mark-up / interest income                  18   9,200,000   7,800,000   4,700,000   4,000,000
Profit before taxation                              21,400,000  18,000,000  10,900,000   9,100,000
Taxation                                            (6,100,000) (5,200,000) (3,100,000) (2,600,000)
Net profit for the period                           15,300,000  12,800,000   7,800,000   6,500,000
Basic EPS (Rs.)                                           6.12        5.12        3.12        2.60
The Board has announced an interim cash dividend of Rs. 3.50 per share.
"""

# Loss-making quarter, dashes and nil printed as values, brackets for negatives.
LOSS_QUARTER = """\
SYNTHETIC TEST FIXTURE - NOT PSX DATA
Condensed Interim Profit or Loss (Un-audited)
For the quarter ended September 30, 2026
Rupees in thousand
Turnover                                        420,000       510,000
Cost of sales                                  (455,000)     (470,000)
Gross (loss)/profit                             (35,000)       40,000
Operating loss                                  (60,000)      (10,000)
Loss before taxation                            (95,000)      (25,000)
Taxation                                            nil           nil
Loss after taxation                             (95,000)      (25,000)
Loss per share - basic and diluted               (1.42)        (0.37)
Cash dividend per share                              -             -
"""


# --------------------------------------------------------------------------- full statements


def test_manufacturing_quarter_is_read_as_printed():
    r = parse_pucar_text(MANUFACTURING_Q, "EXMFG")
    assert isinstance(r, PucarFinancialResult)
    assert r.symbol == "EXMFG"
    assert r.period_ended == date(2026, 3, 31)
    assert r.period_type == "quarterly"
    assert r.turnover == 1250000.0
    assert r.cost_of_sales == -950000.0  # bracketed cost is negative, as printed
    assert r.gross_profit == 300000.0
    assert r.operating_profit == 200000.0
    assert r.profit_before_tax == 170000.0
    assert r.profit_after_tax == 130000.0
    assert r.eps == 2.31
    assert r.dividend_pkr is None  # no dividend stated: absent, not zero
    assert r.scale == 1000 and r.currency == "PKR"
    assert r.turnover_pkr == 1250000000.0  # 1,250,000 PKR thousand = 1,250,000,000 PKR
    assert "not found: dividend_pkr" in " ".join(r.warnings)


def test_bank_half_year_uses_mark_up_label_drops_note_refs_and_reads_sentence_dividend():
    r = parse_pucar_text(BANK_HALF, "EXBNK")
    assert r.period_ended == date(2026, 6, 30)
    assert r.period_type == "half_yearly"
    assert r.turnover == 45600000.0  # note reference 17 is not the figure
    assert r.profit_before_tax == 21400000.0
    assert r.profit_after_tax == 15300000.0  # "Net profit for the period" is the PAT
    assert r.eps == 6.12
    assert r.dividend_pkr == 3.50  # from the sentence, no table row
    assert r.cost_of_sales is None and r.gross_profit is None  # banks print neither: None


def test_loss_quarter_keeps_negatives_and_dash_or_nil_as_zero():
    r = parse_pucar_text(LOSS_QUARTER, "EXLOSS")
    assert r.period_type == "quarterly"
    assert r.turnover == 420000.0
    assert r.cost_of_sales == -455000.0
    assert r.gross_profit == -35000.0  # "Gross (loss)/profit" with a bracketed negative
    assert r.operating_profit == -60000.0
    assert r.profit_before_tax == -95000.0
    assert r.profit_after_tax == -95000.0
    assert r.eps == -1.42
    assert r.dividend_pkr == 0.0  # printed as a dash: nil dividend, not unknown


# --------------------------------------------------------------------------- label variants


@pytest.mark.parametrize(
    ("label", "field"),
    [
        ("Sales - net", "turnover"),
        ("Turnover", "turnover"),
        ("Revenue from contracts with customers", "turnover"),
        ("Net markup/interest income", "turnover"),
        ("Net mark-up / interest income", "turnover"),
        ("Profit after taxation", "profit_after_tax"),
        ("Net profit for the period", "profit_after_tax"),
        ("Profit for the year", "profit_after_tax"),
        ("Earnings per share - basic and diluted", "eps"),
        ("Basic EPS (Rs.)", "eps"),
        ("Cash dividend per share", "dividend_pkr"),
        ("Cost of sales", "cost_of_sales"),
        ("Profit / (loss) before taxation", "profit_before_tax"),
    ],
)
def test_label_variants_map_to_the_intended_field(label, field):
    text = f"For the quarter ended June 30, 2026\n{label}    1,000    900\n"
    assert getattr(parse_pucar_text(text, "EXVAR"), field) is not None


def test_unrecognised_labels_are_ignored_and_not_invented():
    text = "For the quarter ended June 30, 2026\nChange in fair value of investments    5,000    4,000\n"
    r = parse_pucar_text(text, "EXVAR")
    assert r.turnover is None and r.profit_after_tax is None and r.eps is None


# --------------------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("(1,234,567)", -1234567.0),
        ("1,234", 1234.0),
        ("2.31", 2.31),
        ("(0.52)", -0.52),
        ("-", 0.0),
        ("—", 0.0),
        ("nil", 0.0),
        ("NIL", 0.0),
        ("abc", None),
        ("(loss)", None),
        ("12,34", None),  # badly grouped thousands are not a figure
        ("", None),
    ],
)
def test_parse_number(token, expected):
    assert parse_number(token) == expected


# --------------------------------------------------------------------------- period


@pytest.mark.parametrize(
    ("text", "end", "ptype"),
    [
        ("For the year ended 31 December 2025", date(2025, 12, 31), "annual"),
        ("For the half year ended 30 June 2026", date(2026, 6, 30), "half_yearly"),
        ("For the quarter ended 31/03/2026", date(2026, 3, 31), "quarterly"),
        ("For the nine months ended March 31, 2026", date(2026, 3, 31), "nine_months"),
        ("For the quarter ended 31st March, 2026", date(2026, 3, 31), "quarterly"),
    ],
)
def test_period_end_and_type(text, end, ptype):
    r = parse_pucar_text(text + "\n", "EXPER")
    assert r.period_ended == end
    assert r.period_type == ptype


def test_period_length_not_stated_is_flagged():
    r = parse_pucar_text("For the period ended 31 March 2026\n", "EXPER")
    assert r.period_ended == date(2026, 3, 31)
    assert r.period_type is None
    assert any("period length" in w for w in r.warnings)


# --------------------------------------------------------------------------- absence and guards


def test_empty_text_gives_nothing_and_no_exception():
    r = parse_pucar_text("", "EXEMPTY")
    assert r.period_ended is None and r.period_type is None
    assert r.turnover is None and r.eps is None and r.dividend_pkr is None
    assert any("period end date not found" in w for w in r.warnings)


def test_symbol_is_required_and_normalised_not_inferred():
    with pytest.raises(ValueError):
        parse_pucar_text(MANUFACTURING_Q, "   ")
    assert parse_pucar_text(MANUFACTURING_Q, " exmfg ").symbol == "EXMFG"


def test_result_is_immutable():
    r = parse_pucar_text(MANUFACTURING_Q, "EXMFG")
    with pytest.raises(FrozenInstanceError):
        r.turnover = 1.0  # type: ignore[misc]


def test_conflicting_repeat_labels_warn_and_first_value_is_used():
    text = "For the quarter ended June 30, 2026\nTurnover    1,000    900\nTurnover    2,000    800\n"
    r = parse_pucar_text(text, "EXDUP")
    assert r.turnover == 1000.0
    assert any("turnover appears 2 times" in w for w in r.warnings)


# --------------------------------------------------------------------------- real statement pages

# Verbatim pdftotext output; see tests/fixtures/pucar/SOURCES.md for the source file and page.
REAL_MANUFACTURING = (FIXTURES / "real_manufacturing_unconsolidated_pl_pkr000_p39.txt").read_text("utf-8")
REAL_BANK = (FIXTURES / "real_bank_consolidated_pl_usd000_p49.txt").read_text("utf-8")


def test_real_manufacturing_statement_extracts_the_current_year_figures():
    r = parse_pucar_text(REAL_MANUFACTURING, "REALMFG")
    assert r.period_ended == date(2026, 6, 30) and r.period_type == "annual"
    assert r.currency == "PKR" and r.scale == 1000
    assert r.turnover == 136527017.0  # Net Revenue, not the 192,861,184 gross revenue
    assert r.cost_of_sales == -85356494.0  # note 28 dropped; bracketed cost is negative
    assert r.gross_profit == 51170523.0
    assert r.profit_before_tax == 60541979.0  # after levy: the statement total, not the 60,898,313 line
    assert r.profit_after_tax == 46629367.0
    assert r.eps == 31.83  # note 35 dropped; prior year 22.59 not used
    assert r.operating_profit is None  # the statement has no operating-profit total
    assert r.turnover_pkr == 136527017000.0


def test_real_bank_statement_ignores_the_shareholder_table_and_dividend_income():
    r = parse_pucar_text(REAL_BANK, "REALBNK")
    assert r.period_ended == date(2025, 12, 31) and r.period_type == "annual"
    assert r.currency == "USD" and r.scale == 1000
    assert r.turnover == 1290690.0  # net mark-up income, not the 84,425,429 holding figure
    assert r.profit_before_tax == 1039213.0  # from continuing operations; prior year not used
    assert r.profit_after_tax == 464154.0
    assert r.eps == 0.19  # label printed over three lines
    assert r.dividend_pkr is None  # "Dividend income" is not a per-share dividend
    assert r.turnover_pkr is None  # dollars are never reported as rupees
    assert any("currency is USD" in w for w in r.warnings)


# --------------------------------------------------------------------------- synthetic layouts

# SYNTHETIC: a 4-column quarterly table with a Note column. Figures follow the printed column order.
QUARTERLY_4COL = """\
SYNTHETIC TEST FIXTURE - NOT PSX DATA
For the quarter ended March 31, 2026
Rupees in '000
                              Note   Quarter ended   Quarter ended   Nine months    Nine months
                                     Mar 31, 2026    Mar 31, 2025    Mar 31, 2026   Mar 31, 2025
Net sales                      21     1,250,000       1,100,000       3,600,000      3,300,000
Cost of sales                  22      (950,000)       (870,000)     (2,700,000)    (2,500,000)
Gross profit                            300,000         230,000         900,000        800,000
Profit before taxation                  170,000         110,000         510,000        440,000
Profit after taxation                   130,000          85,000         390,000        340,000
Earnings per share - basic and diluted     2.31            1.51            6.93           6.04
"""

# SYNTHETIC: labels printed across two or three lines, and "Rupees in" with '000 on the next line.
SPLIT_LABELS = """\
SYNTHETIC TEST FIXTURE - NOT PSX DATA
Statement of Profit or Loss (Un-audited)
For the quarter ended
March 31, 2026
Rupees in
'000
Revenue from contracts
with customers                      1,000,000          900,000
Profit before taxation                170,000          110,000
Profit after taxation                 130,000           85,000
Earnings per share for profit attributable to the equity holders
of the Bank - Restated
Basic and diluted                       2.31             1.51
"""


def test_four_column_quarterly_table_reads_the_quarter_not_the_prior_or_cumulative_columns():
    r = parse_pucar_text(QUARTERLY_4COL, "EXQ4")
    assert r.period_ended == date(2026, 3, 31) and r.period_type == "quarterly"
    assert r.scale == 1000 and r.currency == "PKR"
    assert r.turnover == 1250000.0  # note 21 dropped
    assert r.cost_of_sales == -950000.0  # note 22 dropped
    assert r.gross_profit == 300000.0
    assert r.profit_before_tax == 170000.0
    assert r.profit_after_tax == 130000.0
    assert r.eps == 2.31


def test_labels_split_across_lines_are_joined_and_units_across_lines_are_read():
    r = parse_pucar_text(SPLIT_LABELS, "EXSPLIT")
    assert r.period_ended == date(2026, 3, 31) and r.period_type == "quarterly"
    assert r.scale == 1000 and r.currency == "PKR"  # "Rupees in" then "'000" on the next line
    assert r.turnover == 1000000.0  # "Revenue from contracts" + "with customers"
    assert r.profit_before_tax == 170000.0
    assert r.profit_after_tax == 130000.0
    assert r.eps == 2.31  # a three-line EPS label


def test_a_single_spaced_row_is_read_from_its_trailing_figures():
    text = "For the year ended June 30, 2026\nProfit before taxation 170 110\n"
    assert parse_pucar_text(text, "EXSING").profit_before_tax == 170.0


def test_the_normalised_pkr_figures_follow_the_scale():
    millions = "For the year ended June 30, 2026\nRupees in million\nSales - net    2,500    2,000\n"
    r = parse_pucar_text(millions, "EXMIL")
    assert r.scale == 1_000_000 and r.turnover == 2500.0 and r.turnover_pkr == 2_500_000_000.0
    units_unstated = "For the year ended June 30, 2026\nSales - net    2,500    2,000\n"
    r = parse_pucar_text(units_unstated, "EXNOU")
    assert r.scale == 1 and r.turnover_pkr is None  # no currency stated, so no PKR figure
    assert any("units not stated" in w for w in r.warnings)
