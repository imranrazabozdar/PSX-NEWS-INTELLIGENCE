"""The extraction coverage matrix is generated from the fixture pipeline and the watchlist. It must not
drift from the code, its headline numbers must be the counts of its own rows, and every watchlist company
must appear."""

import re
from pathlib import Path

from scripts import build_coverage_matrix as bcm

DOC = Path(__file__).resolve().parents[1] / "docs" / "coverage" / "EXTRACTION_COVERAGE.md"


def test_the_committed_matrix_is_the_generator_output():
    assert DOC.read_text(encoding="utf-8") == bcm.render(bcm.build_rows()), (
        "docs/coverage/EXTRACTION_COVERAGE.md is stale: run `python -m scripts.build_coverage_matrix`"
    )


def test_the_headline_company_coverage_is_the_count_over_the_watchlist():
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"Company coverage: (\d+) of (\d+) watchlist companies", text)
    assert m, "the company coverage headline is missing"
    rows = bcm.build_rows()
    covered, size = bcm.company_coverage(rows)
    assert (int(m.group(1)), int(m.group(2))) == (covered, size) == (3, len(bcm.watchlist()))


def test_the_extracted_cell_headline_counts_its_own_rows():
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"Extracted cells: (\d+) of (\d+) green", text)
    cells = [r for r in bcm.build_rows() if r["status"] != "not_started"]
    assert m and (int(m.group(1)), int(m.group(2))) == (
        sum(1 for r in cells if r["status"] == "reconciled"),
        len(cells),
    )


def test_every_watchlist_company_appears_and_the_others_are_not_started():
    rows = bcm.build_rows()
    symbols = [c["symbol"] for c in bcm.watchlist()]
    not_started = [r["symbol"] for r in rows if r["status"] == "not_started"]
    extracted = {r["symbol"] for r in rows if r["status"] != "not_started"}
    assert set(not_started) | extracted == set(symbols)
    assert set(not_started).isdisjoint(extracted)
    assert len(not_started) == len(symbols) - 3
