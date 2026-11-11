"""Run the statement pipeline on the committed real-report text fixtures (tests/fixtures/real_reports/).

Shared by the regression tests and the coverage matrix builder, so both read the same text the same way.
Reads text only; no PDF is opened.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engines import pdf_extraction as pe
from engines import statement_pipeline as sp

REAL = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_reports"
REPORTS = ["ubl_ar2025", "luck_ar2026", "ogdc_ar2026_standalone"]


def manifest(key: str) -> dict:
    return json.loads((REAL / key / "manifest.json").read_text(encoding="utf-8"))


def expected(key: str) -> dict:
    return json.loads((REAL / key / "expected.json").read_text(encoding="utf-8"))


def lines_of(text: str) -> list[str]:
    """Lines exactly as the production reader makes them: split on newlines, blank lines dropped."""
    return [ln.rstrip() for ln in text.split("\n") if ln.strip()]


def layout(key: str) -> dict[tuple[int, str], list[str]]:
    m = manifest(key)
    out = {}
    for name in m["page_files"]:
        mm = re.match(r"page-(\d{3})([LR]?)\.txt$", name)
        out[(int(mm.group(1)), mm.group(2))] = lines_of((REAL / key / name).read_text(encoding="utf-8"))
    return out


def pipeline(key: str, period: str | None = None) -> dict:
    """The reconciliation of one report's statements for one period column (default: the manifest period)."""
    m = manifest(key)
    pages = layout(key)
    doc = pe.DocumentText([
        pe.Page(number=p, lines=lines, has_text=True, extraction_method="pdftotext_layout")
        for (p, side), lines in sorted(pages.items()) if side == ""
    ])

    def region_reader(page: int, side: str) -> list[str]:
        return pages[(page, side)]

    regions = {}
    for k, v in m.get("statement_regions", {}).items():
        regions[k] = [tuple(x) for x in v] if isinstance(v[0], list) else tuple(v)
    extracted = sp.extract(doc, columns=m["columns"], statement_pages=m["statement_pages"] or None,
                           statement_regions=regions or None,
                           region_reader=region_reader if regions else None)
    tagged = sp.tag(
        extracted,
        document={"document_id": key, "file_hash": m["source_sha256"], "symbol": key.upper(),
                  "period_end": m["period_end"], "currency": m["currency"], "unit_scale": m["unit_scale"],
                  "consolidation": m["consolidation"]},
        extractor_version=m["extractor_version"],
        mapping=sp.load_mappings(framework=m["framework"]),
        framework=m["framework"],
    )
    return sp.reconcile(tagged, period_end=period or m["period_end"])
