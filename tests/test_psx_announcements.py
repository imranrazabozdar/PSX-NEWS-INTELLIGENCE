"""PSX announcement feed to dated facts: grouping, figures, losses, missing values, typos left unknown."""

from __future__ import annotations

from datetime import date

from engines import psx_announcements as pa
from scripts import council_run


def feed(*fragments, symbol="POML", day="10Nov2026", time="15:44:55"):
    return [f"{symbol}|Punjab Oil|{day}|{time}|{t}|\r\n" for t in fragments]


def rows_for(*fragments, **kw):
    rows, skipped = pa.build_rows(pa.read_announcements(feed(*fragments, **kw)))
    return rows, skipped


def test_fragments_with_the_same_symbol_date_and_time_are_one_announcement():
    lines = feed("A", "B") + feed("C", day="11Nov2026") + feed("D", symbol="HUBC")
    got = list(pa.read_announcements(lines))
    assert [(a.symbol, a.day.day, a.lines) for a in got] == [
        ("POML", 10, ["A", "B"]),
        ("POML", 11, ["C"]),
        ("HUBC", 10, ["D"]),
    ]


def test_a_loss_result_keeps_its_sign_and_every_figure_comes_from_its_own_line():
    rows, skipped = rows_for(
        "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION (154.882)",
        "PROFIT/LOSS AFTER TAXATION RS. IN MILLION (141.233)",
        "FINANCIAL RESULT FOR THE FIRST QUARTER ENDED 30/09/2026",
        "EPS = (18.19)",
    )
    (r,) = rows
    assert r["topic"] == "results.quarterly" and r["company"] == "POML" and r["source_date"] == "2026-11-10"
    assert (
        r["value"] == -18.19 and r["unit"] == "PKR/share" and r["period"] == "first quarter ended 2026-09-30"
    )
    assert (
        "loss before tax Rs 154.882 million" in r["fact_text"]
        and "loss after tax Rs 141.233 million" in r["fact_text"]
    )
    assert "EPS -18.19" in r["fact_text"] and not skipped


def test_profit_figures_with_thousands_separators_and_scoped_lines():
    rows, _ = rows_for(
        "FINANCIAL RESULT FOR THE YEAR ENDED 30/06/2026",
        "(UNCONSOLIDATED) PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 16,534.525",
        "(UNCONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 13,009.308",
        "(CONSOLIDATED) PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 17,161.864",
        "(CONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 13,721.739",
        "EPS = 30.25",
    )
    by_basis = {("unconsolidated" in r["fact_text"], "consolidated" in r["fact_text"]): r for r in rows}
    assert len(rows) == 3 and {r["topic"] for r in rows} == {
        "results.annual"
    }  # two bases + the EPS of unknown basis
    texts = " ".join(r["fact_text"] for r in rows)
    assert (
        "profit before tax Rs 16,534.525 million" in texts
        and "profit after tax Rs 13,721.739 million" in texts
    )
    assert any("basis not stated" in r["fact_text"] and r["value"] == 30.25 for r in rows) and by_basis


def test_unscoped_eps_joins_the_only_scoped_result():
    rows, _ = rows_for(
        "FINANCIAL RESULT FOR THE HALF YEAR ENDED 31/12/2025",
        "(UNCONSOLIDATED) PROFIT/LOSS AFTER TAXATION RS. IN MILLION 5.100",
        "EPS = 0.51",
    )
    assert len(rows) == 1 and rows[0]["value"] == 0.51 and "(unconsolidated)" in rows[0]["fact_text"]


def test_a_figure_the_announcement_does_not_state_is_unknown_not_zero():
    rows, _ = rows_for(
        "FINANCIAL RESULT FOR THE FIRST QUARTER ENDED 31/12/2022",
        "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 495.610",
        "PROFIT/LOSS AFTER TAXATION RS. IN MILLION 467.821",
        "EPS =",
    )
    (r,) = rows
    assert (
        r["value"] == 467.821 and r["unit"] == "PKR million" and "EPS" not in r["fact_text"]
    )  # no EPS: not 0
    assert pa.parse_number("") is None and pa.parse_number(None) is None and pa.parse_number("(2.5)") == -2.5


def test_a_mistyped_figure_is_left_unknown_and_reported_not_repaired():
    rows, skipped = rows_for(
        "FINANCIAL RESULT FOR THE YEAR ENDED 31/12/2022",
        "PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 50,633.954",
        "PROFIT/LOSS AFTER TAXATION RS. IN MILLION 34,370..887",  # PSX's own typo
    )
    assert (
        "after tax" not in rows[0]["fact_text"] and "before tax Rs 50,633.954 million" in rows[0]["fact_text"]
    )
    assert sum(skipped.values()) == 1


def test_dividend_with_its_period_and_kind():
    rows, _ = rows_for(
        "DIVIDEND = 250%(F)",
        "FOR THE YEAR ENDED 30/06/2025",
        "BOOK CLOSURE FROM 22/09/2025",
        "BOOK CLOSURE TO 28/09/2025",
        "ANNUAL GENERAL MEETING WILL BE HELD ON 28/09/2025",
    )
    by = {r["topic"]: r for r in rows}
    assert (
        by["corporate_action.dividend"]["value"] == 250
        and "(final)" in by["corporate_action.dividend"]["fact_text"]
    )
    assert "year ended 30/06/2025" in by["corporate_action.dividend"]["fact_text"]
    assert "from 22/09/2025 to 28/09/2025" in by["corporate_action.book_closure"]["fact_text"]
    assert "scheduled for 28/09/2025" in by["corporate_action.meeting"]["fact_text"]


def test_bonus_right_and_interim_dividend_kinds():
    rows, _ = rows_for("BONUS ISSUE = 25%", "RIGHT ISSUE  = 100%", "DIVIDEND = 5.5%(ii)")
    got = {r["topic"]: r["value"] for r in rows}
    assert got == {
        "corporate_action.bonus": 25.0,
        "corporate_action.rights": 100.0,
        "corporate_action.dividend": 5.5,
    }
    assert any("second interim" in r["fact_text"] for r in rows)


def test_since_filters_by_announcement_date_and_unknown_lines_are_counted():
    old = feed("DIVIDEND = 10%(F)", day="01Jan2020")
    new = feed("SOMETHING WE DO NOT RECOGNISE", "BONUS ISSUE = 10%", day="01Jan2024")
    rows, skipped = pa.build_rows(pa.read_announcements(old + new), date(2023, 1, 1))
    assert [r["source_date"] for r in rows] == ["2024-01-01"] and skipped[
        "SOMETHING WE DO NOT RECOGNISE"
    ] == 1


def test_every_row_passes_the_fact_validator_and_names_its_source():
    from engines import research_facts as rf

    rows, _ = rows_for("DIVIDEND = 10%(F)", "BONUS ISSUE = 5%")
    for r in rows:
        assert rf.validate_fact(r)["source_name"] == pa.SOURCE_NAME and r["confidence"] == "fact"


def test_the_council_reads_results_as_figures_and_corporate_actions_as_announcements():
    assert council_run.kind_for("results.quarterly") == "figure"
    assert council_run.kind_for("corporate_action.dividend") == "announcement"
