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
         "retrieved_at_utc": "2026-11-09T10:00:00Z", "filed_at_utc": "2025-09-30T00:00:00Z",
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


def test_retrieval_date_is_kept_separately_from_the_import_time(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "t.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    di.intake(db, pdf, _meta(), vault=vault, importer="owner", rights_attestation=SYNTH)
    row = db.execute("SELECT collected_at_utc FROM source_items WHERE external_id LIKE 'doc:%'")[0]
    assert row["collected_at_utc"] == "2026-11-09T10:00:00Z"


def test_source_and_metadata_are_required(db, tmp_path, vault):
    pdf = _pdf(tmp_path, "m.pdf", [["Statement of profit or loss", "Revenue 1,000 800"]])
    with pytest.raises(di.IntakeError, match="source"):
        di.intake(db, pdf, _meta(original_url=None), vault=vault, importer="owner", rights_attestation=SYNTH)
    with pytest.raises(di.IntakeError, match="missing metadata"):
        di.intake(db, pdf, _meta(currency=None), vault=vault, importer="owner", rights_attestation=SYNTH)
    with pytest.raises(di.IntakeError, match="not in the company master"):
        di.intake(db, pdf, _meta(company_ticker="NOPE"), vault=vault, importer="owner",
                  rights_attestation=SYNTH)
