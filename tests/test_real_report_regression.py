"""PERMANENT regression tests on real annual-report pages (archive extraction path).

The fixtures in tests/fixtures/real_reports/ are text only: per-page `pdftotext -layout` output, spread
halves from the reader, a manifest (source SHA-256, pdftotext version, extractor version) and expected.json
(every pinned value with its PDF page number). No PDF is committed. Each expected value is a printed figure
that must appear on its cited page; the pipeline must reproduce each recorded check status from the same
text.

To re-check the text against the owner's vault (needs PSXNI_DOCUMENT_VAULT), see
test_fixtures_match_the_vault below; it is skipped otherwise.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from engines import pdf_extraction as pe
from engines import pdf_reader as pr
from engines import statement_pipeline as sp
from scripts.financial_intake import EXTRACTOR_VERSION

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "tests" / "fixtures" / "real_reports"
REPORTS = ["ubl_ar2025", "luck_ar2026", "ogdc_ar2026_standalone"]


def _manifest(key: str) -> dict:
    return json.loads((REAL / key / "manifest.json").read_text(encoding="utf-8"))


def _expected(key: str) -> dict:
    return json.loads((REAL / key / "expected.json").read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    return " ".join(text.split())


def _lines(text: str) -> list[str]:
    """Lines exactly as the production reader makes them: split on newlines only, blank lines dropped."""
    return [ln.rstrip() for ln in text.split("\n") if ln.strip()]


def _file_text(key: str, page: int, side: str = "") -> str:
    return _norm((REAL / key / f"page-{page:03d}{side}.txt").read_text(encoding="utf-8"))


def _number(printed: str) -> float:
    neg = printed.strip().startswith("(")
    value = float(printed.strip("() ").replace(",", ""))
    return -value if neg else value


# --------------------------------------------------------------------------- provenance


@pytest.mark.parametrize("key", REPORTS)
def test_manifest_records_the_source_hash_and_the_extraction_environment(key):
    m = _manifest(key)
    assert re.fullmatch(r"[0-9a-f]{64}", m["source_sha256"])
    assert m["pdftotext_version"] and m["pdftotext_version"] != "unknown"
    assert m["extractor_version"] == EXTRACTOR_VERSION, "fixtures are stale: regenerate them"
    assert m["source_pdf_pages"] >= max(
        m["page_files"] and [int(re.search(r"\d+", f).group()) for f in m["page_files"]]
    )
    for name in m["page_files"]:
        assert (REAL / key / name).is_file(), name


@pytest.mark.parametrize("key", REPORTS)
def test_every_pinned_value_is_printed_on_its_cited_page(key):
    m, e = _manifest(key), _expected(key)
    assert e["report_key"] == key
    for v in e["values"]:
        side = v.get("side", "")
        assert f"page-{v['page']:03d}{side}.txt" in m["page_files"], v["item"]
        assert _norm(v["printed"]) in _file_text(key, v["page"], side), (
            f"{v['item']}: {v['printed']!r} not printed on page {v['page']}{side}"
        )


@pytest.mark.parametrize("key", REPORTS)
def test_every_kam_is_present_on_its_cited_page(key):
    e = _expected(key)
    kams = e["kams"]
    numbers = {k["n"] for k in kams["items"]}
    assert kams["printed_count"] == len(numbers), "a KAM is missing from the record (no silent omission)"
    for k in kams["items"]:
        side = k.get("side", "")
        assert k["title"] in _file_text(key, k["page"], side), (k["n"], k["title"], k["page"])


def test_status_flags_are_explicit_for_every_unreproduced_figure():
    for key in REPORTS:
        for v in _expected(key)["values"]:
            assert v["status"] in ("reconciled", "printed_only", "requires_review"), v["item"]
            if v["status"] == "requires_review":
                assert v.get("reason"), f"{v['item']}: requires_review needs a reason"


# ------------------------------------------------------------------ the pipeline reproduces the record


def _pipeline(key: str, period: str | None = None) -> dict:
    m = _manifest(key)
    layout = {}
    for name in m["page_files"]:
        mm = re.match(r"page-(\d{3})([LR]?)\.txt$", name)
        page, side = int(mm.group(1)), mm.group(2)
        layout[(page, side)] = _lines((REAL / key / name).read_text(encoding="utf-8"))
    pages = [
        pe.Page(number=p, lines=lines, has_text=True, extraction_method="pdftotext_layout")
        for (p, side), lines in sorted(layout.items())
        if side == ""
    ]
    doc = pe.DocumentText(pages)

    def region_reader(page: int, side: str) -> list[str]:
        return layout[(page, side)]

    regions = {}
    for k, v in m.get("statement_regions", {}).items():
        # one (page, side) pair, or a list of pairs for a statement printed across both halves of a spread
        regions[k] = [tuple(x) for x in v] if isinstance(v[0], list) else tuple(v)
    extracted = sp.extract(
        doc,
        columns=m["columns"],
        statement_pages=m["statement_pages"] or None,
        statement_regions=regions or None,
        region_reader=region_reader if regions else None,
    )
    tagged = sp.tag(
        extracted,
        document={
            "document_id": key,
            "file_hash": m["source_sha256"],
            "symbol": key.upper(),
            "period_end": m["period_end"],
            "currency": m["currency"],
            "unit_scale": m["unit_scale"],
            "consolidation": m["consolidation"],
        },
        extractor_version=m["extractor_version"],
        mapping=sp.load_mappings(framework=m["framework"]),
        framework=m["framework"],
    )
    return sp.reconcile(tagged, period_end=period or m["period_end"])


@pytest.mark.parametrize("key", REPORTS)
def test_pipeline_reproduces_each_recorded_check_status(key):
    rec = _pipeline(key)
    got = {c["check"]: c["status"] for c in rec["checks"]}
    for check, status in _expected(key)["pipeline_checks"].items():
        assert got.get(check) == status, f"{key}: {check} is {got.get(check)}, recorded {status}"
    for check, value in _expected(key).get("pipeline_reported", {}).items():
        row = next(c for c in rec["checks"] if c["check"] == check)
        assert row["reported"] == value


def test_ubl_profit_after_tax_is_reconciled_to_the_printed_figure():
    rec = _pipeline("ubl_ar2025")
    row = next(c for c in rec["checks"] if c["check"] == "income_statement")
    assert row["status"] == "RECONCILED" and row["reported"] == 128008847.0


def test_ogdc_is_oci_and_total_comprehensive_income_reconcile_from_spread_halves():
    rec = _pipeline("ogdc_ar2026_standalone")
    got = {c["check"]: c for c in rec["checks"]}
    assert got["income_statement"]["reported"] == 242373646.0
    assert got["oci_components"]["reported"] == -2246324.0
    assert got["comprehensive_income"]["reported"] == 240127322.0
    assert got["cash_flow"]["reported"] == 291123943.0


# --------------------------------------------------------------------------- the LUCK 2025 OCI resolution


def test_luck_2025_oci_components_sum_to_the_printed_total_with_zero_tci_delta():
    v = {x["item"]: _number(x["printed"]) for x in _expected("luck_ar2026")["values"]}
    # (548,039) = (938,127) + 365,870 + 27,678 + (3,460); subtotal after the first block (572,257)
    assert (
        v["oci_remeasurement_2025"] + v["oci_deferred_tax_thereon_2025"]
        == v["oci_subtotal_2025_after_remeasurement"]
    )
    assert (
        (
            v["oci_subtotal_2025_after_remeasurement"]
            + v["oci_fvoci_2025"]
            + v["oci_deferred_tax_thereon_fvoci_2025"]
        )
        == v["oci_total_2025"]
        == -548039
    )
    # total comprehensive income = profit after tax + OCI, both years, zero delta
    assert (
        v["profit_after_tax_2025"] + v["oci_total_2025"] == v["total_comprehensive_income_2025"] == 32544123
    )
    assert (
        v["profit_after_tax_2026"] + v["oci_total_2026"] == v["total_comprehensive_income_2026"] == 46591207
    )


def test_luck_2026_oci_components_sum_to_the_printed_total():
    v = {x["item"]: _number(x["printed"]) for x in _expected("luck_ar2026")["values"]}
    assert v["oci_remeasurement_2026"] + v["oci_deferred_tax_thereon_2026"] == v["oci_total_2026"] == -38160


def test_ubl_oci_constants_and_their_page_references():
    """The UBL 2025 constants used by test_columns_oci_pagemap.py: PAT 128,008,847 (p.44), OCI 109,698,824
    (p.45), TCI 237,707,671 (p.44). PAT + OCI = TCI."""
    v = {x["item"]: x for x in _expected("ubl_ar2025")["values"]}
    pat = _number(v["profit_after_tax_2025"]["printed"])
    oci = _number(v["other_comprehensive_income_net_of_tax_2025"]["printed"])
    tci = _number(v["total_comprehensive_income_2025"]["printed"])
    assert (pat, oci, tci) == (128008847.0, 109698824.0, 237707671.0)
    assert pat + oci == tci
    assert (
        v["profit_after_tax_2025"]["page"],
        v["other_comprehensive_income_net_of_tax_2025"]["page"],
        v["total_comprehensive_income_2025"]["page"],
    ) == (44, 45, 44)


# --------------------------------------------------------------------------- the vault (optional)


@pytest.mark.parametrize("key", REPORTS)
def test_fixtures_match_the_vault(key):
    vault = os.environ.get("PSXNI_DOCUMENT_VAULT", "")
    if not vault:
        pytest.skip("PSXNI_DOCUMENT_VAULT is not set: the vault re-check is not run")
    m = _manifest(key)
    pdf = Path(vault) / f"{m['source_sha256']}.pdf"
    if not pdf.is_file():
        pytest.skip(f"vault has no file {m['source_sha256'][:12]}")
    assert pe.sha256_file(pdf) == m["source_sha256"]
    if not pr.layout_available():
        pytest.skip("pdftotext is not installed")
    layout = pr.read_layout_pages(pdf)
    for name in m["page_files"]:
        mm = re.match(r"page-(\d{3})([LR]?)\.txt$", name)
        if mm.group(2):
            continue  # spread halves come from the reader's crops; checked by the regeneration script
        fixture = _lines((REAL / key / name).read_text(encoding="utf-8"))
        assert fixture == layout[int(mm.group(1)) - 1], f"{name} differs from the vault copy"


# --------------------------------------------------------------------------- stitching from word coordinates


def _words(key: str, page: int, side: str = "") -> list[dict]:
    """Word coordinates saved from the vault PDF (text data, not the PDF). A side keeps the words whose left
    edge lies in that half of the page, as the intake does."""
    data = json.loads((REAL / key / f"words-{page:03d}.json").read_text(encoding="utf-8"))
    words = data["words"]
    if side:
        half = data["page_width"] / 2.0
        words = [w for w in words if (w["x0"] < half) == (side == "L")]
    return words


@pytest.mark.parametrize(
    "key,page,side",
    [
        ("ogdc_ar2026_standalone", 5, "R"),
        ("ogdc_ar2026_standalone", 6, "L"),
        ("ogdc_ar2026_standalone", 6, "R"),
    ],
)
def test_kam_headings_are_stitched_from_word_coordinates(key, page, side):
    from engines import page_layout as pl

    found = pl.parse_kam_table(_words(key, page, side), page)
    got = {k["number"]: k["heading"] for k in found["kams"]} if found else {}
    expected = {
        k["n"]: k["title"]
        for k in _expected(key)["kams"]["items"]
        if k["page"] == page and k.get("side", "") == side
    }
    for n, title in expected.items():
        assert got[n].startswith(title), (n, got.get(n))


def test_ogdc_kam3_heading_is_the_full_stitched_title():
    from engines import page_layout as pl

    found = pl.parse_kam_table(_words("ogdc_ar2026_standalone", 6, "R"), 6)
    kam3 = next(k for k in found["kams"] if k["number"] == 3)
    assert kam3["heading"] == (
        "Impairment assessment of development and production assets and related property, plant and equipment"
    )


def test_ogdc_balance_sheet_identity_from_the_printed_totals():
    v = {
        x["item"]: _number(x["printed"])
        for x in _expected("ogdc_ar2026_standalone")["values"]
        if x["item"] in ("total_liabilities_2026", "total_equity_2026", "total_assets_2026")
    }
    assert v["total_liabilities_2026"] + v["total_equity_2026"] == v["total_assets_2026"] == 1852828189


def test_ubl_oci_components_equal_the_printed_total_on_page_45():
    rec = _pipeline("ubl_ar2025")
    comp = [
        x
        for x in _expected("ubl_ar2025")["values"]
        if x["item"] == "other_comprehensive_income_net_of_tax_2025"
    ]
    printed_p45 = _number(comp[0]["printed"])
    components = [508221, 93877970, 3213232, 12099401]  # the p.44 right-half OCI lines (all printed)
    assert sum(components) == printed_p45 == 109698824
    assert next(c for c in rec["checks"] if c["check"] == "comprehensive_income")["status"] == "RECONCILED"


@pytest.mark.parametrize("key", REPORTS)
def test_every_statement_is_reconciled_or_flagged_with_page_evidence(key):
    """Five-statement coverage: balance sheet, P&L, OCI, cash flow, changes in equity. Each entry names its
    page (and spread side) and its closing figure, which must be printed there. A statement is reconciled by
    the pipeline from the same text, or recorded as requires_review with a reason."""
    m, e = _manifest(key), _expected(key)
    for st in e["statements"]:
        side = st["side"].replace("/", "")
        names = [f"page-{st['page']:03d}{x}.txt" for x in (side if side else [""])]
        for n in names:
            assert n in m["page_files"], (key, st["statement"], n)
        if st["closing_printed"]:
            text = _file_text(key, st["page"], side if len(side) == 1 else "")
            assert _norm(st["closing_printed"]) in text, (key, st["statement"], st["closing_printed"])
        assert st["status"] in ("reconciled", "requires_review")


@pytest.mark.parametrize(
    "key,period",
    [
        ("ubl_ar2025", "2025-12-31"),
        ("luck_ar2026", "2026-06-30"),
        ("luck_ar2026", "2025-06-30"),
        ("ogdc_ar2026_standalone", "2026-06-30"),
    ],
)
def test_pipeline_reconciles_each_recorded_statement_for_each_column(key, period):
    rec = _pipeline(key, period)
    got = {c["check"]: c["status"] for c in rec["checks"]}
    expected_checks = {st["check"] for st in _expected(key)["statements"] if st["column"] == period}
    for check in expected_checks:
        assert got.get(check) == "RECONCILED", (key, period, check, got.get(check))
