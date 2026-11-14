"""Report facts: printed figures and KAMs only, page cited, no PDF text. No network."""

from __future__ import annotations

import json
from pathlib import Path

from engines import research_facts as rf
from scripts import import_report_facts as imp

ROOT = Path(__file__).resolve().parents[1]
CREATED = "2026-11-14T06:00:00Z"


def _rows(key: str, company: str):
    base = ROOT / "tests" / "fixtures" / "real_reports" / key
    return rf.rows_from_report(company=company,
                               manifest=json.loads((base / "manifest.json").read_text(encoding="utf-8")),
                               expected=json.loads((base / "expected.json").read_text(encoding="utf-8")),
                               created_at=CREATED)


def test_printed_figures_become_sourced_dated_rows_with_the_page_cited():
    rows = _rows("luck_ar2026", "LUCK")
    pat = next(r for r in rows if r["fact_text"].startswith("Profit after taxation:"))
    assert pat["value"] == 46629367.0 and pat["unit"] == "PKR_thousands" and pat["period"] == "FY2026"
    assert "p.40" in pat["fact_text"]
    assert pat["source_name"] == "Lucky Cement Limited annual report, audited statements"
    assert pat["source_date"] == "2026-06-30" and pat["confidence"] == "fact"


def test_a_figure_in_brackets_is_negative_and_an_unreconciled_one_is_flagged():
    rows = _rows("luck_ar2026", "LUCK")
    assert next(r for r in rows if "Remeasurement loss" in r["fact_text"])["value"] == -60572.0
    flagged = [r for r in rows if "not cross-checked" in r["fact_text"]]
    assert len(flagged) == 1  # the one printed_only value in this fixture


def test_key_audit_matters_are_kept_with_their_page():
    rows = _rows("ubl_ar2025", "UBL")
    kams = [r["fact_text"] for r in rows if r["topic"] == "report.kam"]
    # the fixture records the same matter twice: unconsolidated (p.42) and consolidated (p.98)
    assert len(kams) == 2 and all(", p." in k for k in kams)
    assert len(set(kams)) == 2  # the same title on different pages stays distinguishable


def test_no_pdf_page_text_reaches_any_row():
    base = ROOT / "tests" / "fixtures" / "real_reports" / "luck_ar2026"
    page_text = (base / "page-040.txt").read_text(encoding="utf-8")
    longest = max((ln.strip() for ln in page_text.splitlines()), key=len)
    body = json.dumps(_rows("luck_ar2026", "LUCK"))
    assert len(longest) > 40 and longest not in body
    assert all(len(r["fact_text"]) <= rf.MAX_FACT_CHARS for r in _rows("ogdc_ar2026_standalone", "OGDC"))


def test_the_importer_covers_the_three_reports_and_only_those():
    assert imp.REPORTS == {"luck_ar2026": "LUCK", "ogdc_ar2026_standalone": "OGDC", "ubl_ar2025": "UBL"}
    assert sum(len(r) for _, _, r in imp.report_rows(CREATED)) == 35
