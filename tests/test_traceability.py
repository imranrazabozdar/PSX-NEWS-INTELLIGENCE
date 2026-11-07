"""Every numbered section of the specification must appear in the traceability matrix."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "SPECIFICATION.md"
MATRIX = ROOT / "docs" / "TRACEABILITY.md"
VALID_STATUSES = ("NOT STARTED", "IN PROGRESS", "PARTIAL", "BLOCKED", "IMPLEMENTED", "TESTED")


def spec_section_ids() -> set[str]:
    ids: set[str] = set()
    top = None
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^# (\d+)\. ", line)
        if m:
            top = m.group(1)
            ids.add(top)
            continue
        m = re.match(r"^# Appendix ([A-Z]) ", line)
        if m:
            top = None
            ids.add(m.group(1))
            continue
        m = re.match(r"^## (\d+\.\d+) ", line)
        if m:
            ids.add(m.group(1))
            continue
        m = re.match(r"^## (\d+)\. ", line)  # module headings inside section 3
        if m and top == "3":
            ids.add(f"3.{m.group(1)}")
    return ids


def matrix_rows() -> list[list[str]]:
    rows = []
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        if line.startswith("| R-"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def test_spec_parsing_finds_all_major_sections():
    ids = spec_section_ids()
    assert {str(n) for n in range(1, 21)} <= ids
    assert {f"3.{n}" for n in range(1, 24)} <= ids
    assert {"A", "B", "11.1", "4.6", "10.3"} <= ids


def test_every_spec_section_is_traced():
    covered = set()
    for row in matrix_rows():
        sec = row[1]
        covered.add(sec)
        covered.add(sec.split(".")[0])
    missing = sorted(spec_section_ids() - covered, key=lambda s: (len(s), s))
    assert not missing, f"Spec sections missing from TRACEABILITY.md: {missing}"


def test_every_row_has_a_valid_status():
    for row in matrix_rows():
        assert len(row) == 7, row
        assert row[6].startswith(VALID_STATUSES), row


def test_tested_rows_cite_a_test():
    for row in matrix_rows():
        if row[6].startswith("TESTED"):
            assert row[5], f"{row[0]} is TESTED but cites no test"
