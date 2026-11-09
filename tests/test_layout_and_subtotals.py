"""Side-by-side layout, touching-glyph repair and structural subtotals (pilot defects D5 and D6).

SYNTHETIC fixtures only. The layout mirrors the pattern of the owner's OGDCL announcement annexure, but every
figure is invented for testing. These tests show the logic; they are not evidence of real-document accuracy.
"""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import document_intake as di
from engines import financials as fin
from engines import pdf_extraction as pe
from engines import pdf_reader as pr
from engines import subtotals as st
from tests.pdf_fixture_builder import write_positioned_pdf

_HELV = {",": 278, ".": 278, " ": 278, "(": 333, ")": 333, "-": 333}
COLS_BS = ["2026-09-30", "2026-06-30"]
SYNTH = "synthetic fixture (not a real document)"


def _w(text: str) -> float:
    """Helvetica advance widths at 10 pt, for right-aligning figures in a fixture."""
    return sum(_HELV.get(ch, 556) for ch in text) / 1000 * 10


def at(x: float, top: float, text: str) -> tuple[float, float, str]:
    return (x, top, text)


def at_right(x_right: float, top: float, text: str) -> tuple[float, float, str]:
    return (x_right - _w(text), top, text)


def side_by_side_bs() -> list[tuple[float, float, str]]:
    """Left: equity and liabilities. Right: assets. Figures right-aligned in each column. Invented values."""
    items = [at(60, 100, "SHARE CAPITAL AND RESERVES"), at(330, 100, "NON CURRENT ASSETS")]
    left = [
        (115, "Share capital", "1,000", "1,000"),
        (130, "Reserves 4", "500", "450"),
        (145, "Unappropriated profit", "2,000", "1,800"),
        (160, None, "3,500", "3,250"),
        (175, "NON CURRENT LIABILITIES", None, None),
        (190, "Deferred taxation", "300", "280"),
        (205, "Provision for decommissioning", "700", "650"),
        (220, None, "1,000", "930"),
        (235, "TOTAL LIABILITIES", "1,000", "930"),
        (250, None, "4,500", "4,180"),
    ]
    right = [
        (115, "Property, plant and equipment", "1,000", "950"),
        (130, "Long term investments", "500", "480"),
        (145, None, "1,500", "1,430"),
        (160, "CURRENT ASSETS", None, None),
        (175, "Trade debts", "1,000", "900"),
        (190, "Cash and bank balances", "2,000", "1,850"),
        (205, None, "3,000", "2,750"),
        (220, None, "4,500", "4,180"),
    ]
    for top, label, v1, v2 in left:
        if label:
            items.append(at(60, top, label))
        if v1 is not None:
            items += [at_right(250, top, v1)]
            if v2 is not None:
                items += [at_right(300, top, v2)]
    for top, label, v1, v2 in right:
        if label:
            items.append(at(330, top, label))
        if v1 is not None:
            items.append(at_right(520, top, v1))
            if v2 is not None:
                items.append(at_right(590, top, v2))
    return items


def _pdf(tmp_path, pages):
    return write_positioned_pdf(tmp_path / "layout.pdf", pages)


# ---------------------------------------------------------------- D6: layout-aware column split
def test_side_by_side_boundary_is_found_and_each_label_stays_with_its_column(tmp_path):
    pdf = _pdf(tmp_path, [side_by_side_bs()])
    info, parts = pr.split_page(pdf, 1)
    assert info["layout"] == "two_column" and info["rows"] >= 3
    left, right = next(p for p in parts if p.column == "L"), next(p for p in parts if p.column == "R")
    left_text, right_text = " | ".join(left.lines), " | ".join(right.lines)
    assert (
        "Property" not in left_text and "Trade debts" not in left_text
    )  # assets never in the liabilities column
    assert (
        "CURRENT LIABILITIES" not in right_text and "NON CURRENT LIABILITIES" not in right_text
    )  # no heading crossed
    assert "Share capital 1,000 1,000" in left.lines
    assert any(line.startswith("Trade debts") for line in right.lines)


def test_a_single_table_with_note_references_and_two_value_columns_is_not_split(tmp_path):
    """Negative: a normal table has two figure columns and no label after a figure: it must not split."""
    rows = [
        (115, "Revenue", "1,000,000", "800,000"),
        (130, "Cost of sales", "600,000", "500,000"),
        (145, "Gross profit", "400,000", "300,000"),
        (160, "Finance cost", "20,000", "15,000"),
    ]
    items = []
    for top, label, a, b in rows:
        items += [at(60, top, label), at_right(330, top, a), at_right(440, top, b)]
    info, parts = pr.split_page(_pdf(tmp_path, [items]), 1)
    assert info["layout"] == "single" and len(parts) == 1 and parts[0].column is None


def test_too_few_matching_rows_is_uncertain_and_is_never_parsed(tmp_path):
    """Negative: two matching rows are not enough to trust a boundary. The page is flagged, not guessed."""
    items = side_by_side_bs()
    keep = [i for i in items if i[1] in (100, 115, 130)] + [at(330, 145, "Another"), at_right(480, 145, "5")]
    pdf = _pdf(tmp_path, [keep])
    info, parts = pr.split_page(pdf, 1)
    assert info["layout"] == "uncertain"
    db = SQLiteDatabase()
    migrate(db)
    load(db)
    doc = pe.DocumentText(parts)
    out = pe.to_statement_lines(doc, "BS", [1], columns=COLS_BS)
    assert out["lines"] == [] and any("layout uncertain" in u["reason"] for u in out["unparsed"])
    db.close()


def _word(text, x0, x1, top=100.0):
    return {"text": text, "x0": x0, "x1": x1, "top": top}


def test_touching_digit_fragment_is_joined_and_recorded():
    """The real text layer split '81,155' into '8' and '1,155' whose glyph boxes touch (gap 0.0 pt). The join
    is deterministic and recorded with its original text."""
    words = [_word("Unclaimed", 60, 110), _word("1,155", 205.56, 235), _word("8", 200, 205.56)]
    joined, repairs = pr.join_touching_figures(words, page=2)
    assert [w["text"] for w in joined if w["text"] != "Unclaimed"] == ["81,155"]
    assert repairs == [{"page": 2, "original": "8 1,155", "joined": "81,155", "gap_pt": 0.0}]


def test_separated_fragments_are_not_joined():
    """Negative: a real separator (about 20 points) is never joined into one number."""
    words = [_word("8", 200, 205.56), _word("1,155", 230, 260)]
    joined, repairs = pr.join_touching_figures(words, page=2)
    assert repairs == [] and len(joined) == 2


# ---------------------------------------------------------------- D5: structural subtotals
def _lines(*rows):
    return list(rows)


def _by_text(res, text):
    return next(r for r in res if r["text"] == text)


def test_block_sum_is_recognised_only_when_it_matches_exactly():
    lines = _lines(
        "Share capital 1,000 1,000", "Reserves 500 450", "Unappropriated profit 2,000 1,800", "3,500 3,250"
    )
    r = _by_text(st.analyse(lines, statement="BS", columns=COLS_BS, page=1), "3,500 3,250")
    assert r["status"] == "recognised" and r["rule"] == "R1_block_sum" and r["covers"] == [0, 1, 2]


def test_a_subtotal_off_by_one_thousand_is_not_recognised():
    lines = _lines("Share capital 1,000 1,000", "Reserves 500 450", "3,501 3,250")
    r = _by_text(st.analyse(lines, statement="BS", columns=COLS_BS, page=1), "3,501 3,250")
    assert r["status"] == "unresolved" and r["code"] is None


def test_two_different_matching_runs_are_ambiguous_and_stay_unresolved():
    lines = _lines("A 50 50", "B -50 -50", "C 50 50", "50 50")
    r = _by_text(st.analyse(lines, statement="BS", columns=COLS_BS, page=1), "50 50")
    assert r["status"] == "unresolved" and r["reason"] == "ambiguous block sum"


def test_a_heading_stops_a_block_sum_from_crossing_two_blocks():
    lines = _lines("Share capital 100 100", "NON CURRENT LIABILITIES", "Reserves 100 100", "200 200")
    r = _by_text(st.analyse(lines, statement="BS", columns=COLS_BS, page=1), "200 200")
    assert r["status"] == "unresolved"


def test_equity_is_named_only_under_its_own_heading():
    body = [
        "Share capital 1,000 1,000",
        "Reserves 500 450",
        "Unappropriated profit 2,000 1,800",
        "3,500 3,250",
    ]
    named = st.analyse(
        ["SHARE CAPITAL AND RESERVES", *body, "NON CURRENT LIABILITIES"],
        statement="BS",
        columns=COLS_BS,
        page=1,
    )
    assert _by_text(named, "3,500 3,250")["code"] == "total_equity"
    unnamed = st.analyse(body, statement="BS", columns=COLS_BS, page=1)
    assert _by_text(unnamed, "3,500 3,250")["code"] is None  # same figures, no heading: no meaning assigned


def test_cost_of_sales_is_named_only_between_revenue_and_gross_profit():
    lines = _lines(
        "Revenue from contracts with customers 1,000 800",
        "Royalty (100) (80)",
        "Operating expenses (200) (160)",
        "(300) (240)",
        "Gross profit 700 560",
    )
    r = _by_text(
        st.analyse(lines, statement="IS", columns=["2026-09-30", "2025-09-30"], page=1), "(300) (240)"
    )
    assert r["status"] == "recognised" and r["code"] == "cost_of_sales" and r["rule"] == "R4_cost_block"
    moved = _lines(
        "Revenue from contracts with customers 1,000 800",
        "Royalty (100) (80)",
        "Gross profit 900 720",
        "Operating expenses (200) (160)",
        "(300) (240)",
    )
    r2 = _by_text(
        st.analyse(moved, statement="IS", columns=["2026-09-30", "2025-09-30"], page=1), "(300) (240)"
    )
    assert r2["code"] is None  # not directly above gross profit: no meaning assigned


def test_a_year_header_row_is_not_treated_as_a_figure_row():
    res = st.analyse(["2026 2026", "Share capital 1,000 1,000"], statement="BS", columns=COLS_BS, page=1)
    assert res == []


def test_side_by_side_balance_sheet_resolves_every_subtotal_and_both_totals(tmp_path):
    """The real pattern of document B: every structural total is recognised, and the grand totals agree with
    the labelled and recognised components."""
    _, parts = pr.split_page(_pdf(tmp_path, [side_by_side_bs()]), 1)
    got = {}
    for p in parts:
        for r in st.analyse(p.lines, statement="BS", columns=COLS_BS, page=1):
            if r["status"] == "recognised":
                got[(r["code"] or r["rule"], r["values"][COLS_BS[0]])] = r
    assert ("total_equity", 3500.0) in got and ("total_assets", 4500.0) in got
    assert ("R5_equity_plus_liabilities", 4500.0) in got
    assert got[("total_assets", 4500.0)]["covers"] and got[("total_equity", 3500.0)]["covers"]


# ---------------------------------------------------------------- intake: layout and subtotals end to end
@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


def _meta(**kw):
    m = {
        "company_ticker": "OGDC",
        "doc_type": "quarterly",
        "period_end": "2026-09-30",
        "scope": "unconsolidated",
        "currency": "PKR",
        "unit_scale": 1000,
        "audit_status": "unaudited",
        "columns": {"BS": COLS_BS},
        "receipt_at_utc": "2026-11-09T10:00:00Z",
        "filed_at_utc": "2026-10-30T00:00:00Z",
        "original_url": "https://example.invalid/synthetic.pdf",
        "statement_pages": {"BS": [1]},
        "split_pages": [1],
    }
    m.update(kw)
    return m


def test_intake_stores_structural_totals_with_their_rule_and_page(db, tmp_path):
    vault = di.vault_dir(tmp_path / "vault")
    pdf = _pdf(tmp_path, [side_by_side_bs()])
    r = di.intake(db, pdf, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    bs = next(c for c in r["import"]["checks"] if c["check"] == "balance_sheet")
    assert bs["result"] == "pass"  # 4,500 = 1,000 + 3,500, from recognised totals
    rows = db.execute(
        "SELECT canonical_code, raw_label, value, page FROM financial_line_items "
        "WHERE canonical_code IN ('total_assets','total_equity')"
    )
    assert {r_["canonical_code"] for r_ in rows} == {"total_assets", "total_equity"}
    assert all(r_["raw_label"].startswith("[structural ") and r_["page"] == 1 for r_ in rows)


def test_the_same_file_for_consolidated_and_unconsolidated_scope_is_not_a_duplicate(db, tmp_path):
    """Document C holds both scopes. Scope is part of the duplicate key, so the second scope is imported."""
    vault = di.vault_dir(tmp_path / "vault")
    pdf = _pdf(tmp_path, [side_by_side_bs()])
    first = di.intake(
        db, pdf, _meta(scope="unconsolidated"), vault=vault, importer="owner", rights_attestation=SYNTH
    )
    second = di.intake(
        db, pdf, _meta(scope="consolidated"), vault=vault, importer="owner", rights_attestation=SYNTH
    )
    assert first["status"] != "duplicate" and second["status"] != "duplicate"
    assert db.execute("SELECT COUNT(*) n FROM financial_reports")[0]["n"] == 2


def test_current_assets_and_current_liabilities_are_named_only_under_their_headings():
    """Block closes under the CURRENT LIABILITIES heading get their code; without the heading: no meaning."""
    cl = [
        "CURRENT LIABILITIES",
        "Short term lease liability 1,726 2,015",
        "Trade and other payables 127,578 150,888",
        "129,304 152,903",
        "TOTAL LIABILITIES 309,156 333,278",
    ]
    named = st.analyse(cl, statement="BS", columns=COLS_BS, page=1)
    assert _by_text(named, "129,304 152,903")["code"] == "current_liabilities"
    unnamed = st.analyse(cl[1:], statement="BS", columns=COLS_BS, page=1)
    assert _by_text(unnamed, "129,304 152,903")["code"] is None


# ---------------------------------------------------------------- audit trail, dates, vault and atomicity
def test_structural_audit_keeps_text_rule_version_and_label_origin(db, tmp_path):
    vault = di.vault_dir(tmp_path / "vault")
    r = di.intake(
        db,
        _pdf(tmp_path, [side_by_side_bs()]),
        _meta(),
        vault=vault,
        importer="owner",
        rights_attestation=SYNTH,
    )
    audit = r["dates"] and None
    rec = db.execute("SELECT source_metadata_json FROM source_items WHERE external_id LIKE 'doc:%'")[0]
    import json as _json

    meta = _json.loads(rec["source_metadata_json"])
    rows = meta["structural_audit"]
    assert audit is None and rows
    recognised = [a for a in rows if a["status"] == "recognised"]
    assert recognised and all(
        a["label_origin"] == "structurally_inferred"
        and a["explicit_label"] is None
        and a["rule_version"] == "1"
        and a["original_text"]
        for a in recognised
    )
    assert any(a["derived_label"] == "total_assets" for a in recognised)


def test_date_only_receipt_is_recorded_with_its_precision_not_as_a_time(db, tmp_path):
    vault = di.vault_dir(tmp_path / "vault")
    r = di.intake(
        db,
        _pdf(tmp_path, [side_by_side_bs()]),
        _meta(receipt_at_utc="2026-11-09"),
        vault=vault,
        importer="owner",
        rights_attestation=SYNTH,
    )
    assert r["dates"]["receipt_precision"] == "date_only" and r["dates"]["receipt_at_utc"].startswith(
        "2026-11-09"
    )


def test_symbolic_link_input_is_refused(db, tmp_path):
    real = _pdf(tmp_path, [side_by_side_bs()])
    link = tmp_path / "link.pdf"
    link.symlink_to(real)
    vault = di.vault_dir(tmp_path / "vault")
    with pytest.raises(di.IntakeError, match="symbolic links"):
        di.intake(db, link, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)


def test_a_group_readable_vault_is_refused(tmp_path):
    v = tmp_path / "open_vault"
    v.mkdir(mode=0o755)
    v.chmod(0o755)
    with pytest.raises(di.IntakeError, match="private"):
        di.vault_dir(v)


def test_a_failed_import_leaves_no_source_record(db, tmp_path):
    """An unknown canonical code is refused before any write: no orphan source item is created."""
    before = db.execute("SELECT COUNT(*) n FROM source_items")[0]["n"]
    rec = {
        "company_ticker": "OGDC",
        "doc_type": "quarterly",
        "period_end": "2026-09-30",
        "scope": "unconsolidated",
        "currency": "PKR",
        "unit_scale": 1000,
        "audit_status": "unaudited",
        "filed_at_utc": "2026-10-30T00:00:00Z",
        "document_sha256": "e" * 64,
        "source": "synthetic_test",
        "original_url": None,
        "source_note": "x",
        "lines": [
            {
                "statement": "IS",
                "raw_label": "Revenue",
                "column_period_end": "2026-09-30",
                "value": 1.0,
                "page": 1,
                "canonical_code": "made_up_code",
            }
        ],
    }
    with pytest.raises(fin.ImportError_):
        fin.import_report(db, rec, importer="o", rights_attestation="s")
    assert db.execute("SELECT COUNT(*) n FROM source_items")[0]["n"] == before


def test_a_label_crossing_the_gutter_is_flagged_not_split(tmp_path):
    items = side_by_side_bs() + [at(280, 300, "Wide label across the gutter"), at_right(560, 300, "1,000")]
    info, parts = pr.split_page(_pdf(tmp_path, [items]), 1)
    assert info["layout"] == "uncertain" and "gutter" in info["reason"]
    assert parts[0].layout_flag == "uncertain"


def test_a_page_wide_signature_or_rule_does_not_make_the_layout_uncertain(tmp_path):
    """Regression: the footer signature row and the dashed header rule span the gutter on the real annexure
    B. They are not table rows and must not block the split."""
    items = side_by_side_bs() + [at(60, 300, "Chief Financial Officer"), at(330, 300, "Chief Executive"),
                                 at(60, 90, "-" * 40 + "(Rupees)" + "-" * 10)]
    info, parts = pr.split_page(_pdf(tmp_path, [items]), 1)
    assert info["layout"] == "two_column", info
