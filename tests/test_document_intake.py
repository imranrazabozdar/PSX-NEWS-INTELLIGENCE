"""Owner-assisted document intake. SYNTHETIC PDFs only: these test the logic, not real-document accuracy."""

from __future__ import annotations

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import document_intake as di
from engines import financials as fin
from tests.pdf_fixture_builder import write_pdf

COLS = ["2025-06-30", "2024-06-30"]
SYNTH = "synthetic fixture (not a real document)"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    yield d
    d.close()


@pytest.fixture
def vault(tmp_path):
    return di.vault_dir(tmp_path / "vault")


def _meta(**kw):
    m = {"company_ticker": "OGDC", "doc_type": "annual", "period_end": "2025-06-30",
         "scope": "unconsolidated",
         "currency": "PKR", "unit_scale": 1000, "audit_status": "audited", "columns": COLS,
         "receipt_at_utc": "2026-11-09T10:00:00Z", "filed_at_utc": "2025-09-30T00:00:00Z",
         "original_url": "https://example.invalid/synthetic-report.pdf"}
    m.update(kw)
    return m


def _pdf(tmp_path, name, pages):
    return write_pdf(tmp_path / name, pages)


def test_vault_must_be_absolute_and_outside_the_repository(tmp_path):
    with pytest.raises(di.IntakeError, match="absolute"):
        di.vault_dir("relative/vault")
    with pytest.raises(di.IntakeError, match="outside the Git repository"):
        di.vault_dir(di.REPO_ROOT / "docs" / "vault")
    with pytest.raises(di.IntakeError, match="no vault"):
        di.vault_dir("")  # no explicit vault and none configured


def test_original_is_stored_byte_for_byte_by_hash(tmp_path, vault):
    pdf = _pdf(tmp_path, "a.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    stored, sha = di.store_original(pdf, vault)
    assert stored.name == f"{sha}.pdf" and stored.read_bytes() == pdf.read_bytes()
    assert not any(p for p in di.REPO_ROOT.glob("vault*"))  # nothing written into the repository


def test_unreadable_file_is_refused_and_nothing_is_stored(tmp_path, vault):
    bad = tmp_path / "not.pdf"
    bad.write_bytes(b"plain text, not a pdf")
    with pytest.raises(ValueError):
        di.store_original(bad, vault)
    assert list(vault.iterdir()) == []


def test_intake_extracts_lines_with_page_references_and_keeps_bracket_and_dash_rules(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "is.pdf", [["Statement of profit or loss", "Revenue 1,000 800",
                                     "Cost of sales (600) -"], ["Gross profit 400 800"]])
    r = di.intake(db, pdf, _meta(statement_pages={"IS": [1, 2]}), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    assert r["status"] in ("needs_review", "reconciled") and r["lines_extracted"] == 6
    rows = {(x["raw_label"], x["column_period_end"]): x for x in db.execute(
        "SELECT raw_label, column_period_end, value, value_state, page FROM financial_line_items")}
    assert rows[("Cost of sales", "2025-06-30")]["value"] == -600.0
    assert rows[("Cost of sales", "2024-06-30")]["value_state"] == "not_reported"  # dash: never zero
    assert rows[("Gross profit", "2025-06-30")]["page"] == 2
    assert all(x["page"] is not None for x in rows.values())  # every line keeps its page


def test_same_file_twice_is_a_duplicate_and_adds_no_rows(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "dup.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    first = di.intake(db, pdf, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    n_before = db.execute("SELECT COUNT(*) n FROM financial_line_items")[0]["n"]
    second = di.intake(db, pdf, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    assert first["status"] != "duplicate" and second["status"] == "duplicate"
    assert db.execute("SELECT COUNT(*) n FROM financial_line_items")[0]["n"] == n_before


def test_different_bytes_for_same_period_is_reported_as_possible_revision_not_imported(db, tmp_path, vault):
    a = _pdf(tmp_path, "orig.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    di.intake(db, a, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    before = db.execute("SELECT COUNT(*) n FROM financial_reports")[0]["n"]
    b = _pdf(tmp_path, "revised.pdf", [["Statement of profit or loss", "Revenue 1,000 900"]])
    r = di.intake(db, b, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    assert r["status"] == "possible_revision" and r["existing_reports"]
    assert db.execute("SELECT COUNT(*) n FROM financial_reports")[0]["n"] == before


def test_scanned_page_is_flagged_and_no_figures_are_invented(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "scan.pdf", [["Statement of profit or loss", "Revenue 1,000 800"], None])
    r = di.intake(db, pdf, _meta(statement_pages={"IS": [1, 2]}), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    assert r["scanned_pages"] == [2] and r["status"] == "needs_review"
    assert any(u["page"] == 2 and "OCR" in u["reason"] for u in r["unparsed"])
    assert all(x["page"] == 1 for x in db.execute("SELECT page FROM financial_line_items"))


def test_receipt_date_is_kept_and_an_unknown_download_date_is_never_filled_in(db, tmp_path, vault):
    """The upload/receipt date is recorded as receipt; a download date that was not supplied is 'unknown',
    never the receipt date."""
    pdf = _pdf(tmp_path, "t.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    r = di.intake(db, pdf, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    row = db.execute("SELECT collected_at_utc, source_metadata_json FROM source_items "
                     "WHERE external_id LIKE 'doc:%'")[0]
    assert row["collected_at_utc"] == "2026-11-09T10:00:00Z"
    assert '"download_at_utc": "unknown"' in row["source_metadata_json"]
    assert r["dates"]["download_at_utc"] == "unknown"


def test_a_supplied_download_date_is_recorded_as_supplied(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "d.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    di.intake(db, pdf, _meta(download_at_utc="2026-11-08T18:30:00Z"), vault=vault, importer="owner",
              rights_attestation=SYNTH)
    meta_json = db.execute("SELECT source_metadata_json FROM source_items WHERE external_id LIKE 'doc:%'")[0][
        "source_metadata_json"]
    assert '"download_at_utc": "2026-11-08T18:30:00Z"' in meta_json


def test_source_and_metadata_are_required(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "m.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    with pytest.raises(di.IntakeError, match="source"):
        di.intake(db, pdf, _meta(original_url=None), vault=vault, importer="owner", rights_attestation=SYNTH)
    with pytest.raises(di.IntakeError, match="missing metadata"):
        di.intake(db, pdf, _meta(currency=None), vault=vault, importer="owner", rights_attestation=SYNTH)
    with pytest.raises(di.IntakeError, match="receipt_at_utc"):
        di.intake(db, pdf, _meta(receipt_at_utc=None), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    with pytest.raises(di.IntakeError, match="not in the company master"):
        di.intake(db, pdf, _meta(company_ticker="NOPE"), vault=vault, importer="owner",
                  rights_attestation=SYNTH)


# ------------------------------------------- pilot regressions (found on real OGDCL pages)
def test_comparative_columns_are_per_statement_not_shared(db, tmp_path, vault):
    """Real OGDCL interim report: the quarterly profit or loss compares with 30 Sep 2025, while the balance
    sheet compares with 30 Jun 2026. A single shared column list stored the P&L comparative as 30 Jun 2026."""
    pdf = _pdf(tmp_path, "pl.pdf", [["Statement of profit or loss", "Revenue 132,418,817 96,191,968"]])
    meta = _meta(columns={"IS": ["2026-09-30", "2025-09-30"], "BS": ["2026-09-30", "2026-06-30"]},
                 statement_pages={"IS": [1]})
    di.intake(db, pdf, meta, vault=vault, importer="owner", rights_attestation=SYNTH)
    rows = db.execute("SELECT column_period_end, value FROM financial_line_items WHERE raw_label='Revenue'")
    assert {r["column_period_end"]: r["value"] for r in rows} == {"2026-09-30": 132418817.0,
                                                                  "2025-09-30": 96191968.0}


def test_label_containing_numbers_is_flagged_not_stored(db, tmp_path, vault):
    """Real OGDCL balance sheet (side-by-side layout): the text layer puts a figure of the left column inside
    the label of the right column. Such a line must be reported, never stored under a guessed label."""
    line = ("Provision for decommissioning cost 5 62,186,348 6 0,720,610 "
            "Trade debts 14 595,587,753 594,845,141")
    r = fin.parse_statement_text(line, statement="BS", columns=["2026-09-30", "2026-06-30"], page=2)
    assert r["lines"] == [] and r["unparsed"] and "numbers" in r["unparsed"][0]["reason"]


def test_failed_extraction_imports_nothing(db, tmp_path, vault):
    """A scanned-only document must not leave an empty report in the database."""
    pdf = _pdf(tmp_path, "scan2.pdf", [None, None])
    before = db.execute("SELECT COUNT(*) n FROM financial_reports")[0]["n"]
    r = di.intake(db, pdf, _meta(statement_pages={"IS": [1], "BS": [2]}), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
    assert r["status"] == "extraction_failed" and r["scanned_pages"] == [1, 2]
    assert db.execute("SELECT COUNT(*) n FROM financial_reports")[0]["n"] == before


def test_section_heading_from_the_other_column_is_not_kept_in_the_label():
    """Real OGDCL announcement annexure: 'CURRENT LIABILITIES' from the left column sat on the same text line
    as 'Deposits and short term prepayments' from the right column. The value was right; the label was not."""
    line = "CURRENT LIABILITIES Deposits and short term prepayments 2,331,896 1,915,330"
    r = fin.parse_statement_text(line, statement="BS", columns=["2026-09-30", "2026-06-30"], page=2)
    assert r["lines"] == [] and "section heading" in r["unparsed"][0]["reason"]
    ok = fin.parse_statement_text("Deposits and short term prepayments 2,331,896 1,915,330", statement="BS",
                                  columns=["2026-09-30", "2026-06-30"], page=2)
    assert [x["raw_label"] for x in ok["lines"]][0] == "Deposits and short term prepayments"
