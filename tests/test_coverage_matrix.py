"""The extraction coverage matrix is generated from the fixture pipeline. It must not drift from the code,
and its percentage must be the percentage of its own cells."""

import re
from pathlib import Path

from scripts import build_coverage_matrix as bcm

DOC = Path(__file__).resolve().parents[1] / "docs" / "coverage" / "EXTRACTION_COVERAGE.md"


def test_the_committed_matrix_is_the_generator_output():
    assert DOC.read_text(encoding="utf-8") == bcm.render(bcm.build_rows()), (
        "docs/coverage/EXTRACTION_COVERAGE.md is stale: run `python -m scripts.build_coverage_matrix`"
    )


def test_the_stated_percentage_is_the_share_of_green_cells_in_the_table():
    text = DOC.read_text(encoding="utf-8")
    cells = [
        ln
        for ln in text.splitlines()
        if ln.startswith("| ") and "| Statement |" not in ln and "|---" not in ln
    ]
    green = sum(1 for ln in cells if "| reconciled |" in ln)
    m = re.search(r"Green cells: (\d+) of (\d+) \(([\d.]+)%\)", text)
    assert m, "the green-cell summary is missing"
    assert (int(m.group(1)), int(m.group(2))) == (green, len(cells))
    assert float(m.group(3)) == round(100.0 * green / len(cells), 1)


def test_every_company_period_statement_combination_is_a_cell():
    rows = bcm.build_rows()
    combos = {(r["company"], r["period"], r["statement"]) for r in rows}
    companies = {r["company"] for r in rows}
    assert len(combos) == len(rows) == len(companies) * 2 * 5  # two periods and five statements per company
