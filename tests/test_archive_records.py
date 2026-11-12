"""Archive records: document registry, extraction evidence, reconciliation and reviews.

Includes one end-to-end path from a SYNTHETIC PDF through the local vault to stored, reconciled evidence.

All data is synthetic. No network, no Turso, no production credentials.
"""

from __future__ import annotations

import hashlib

import pytest

from database import financial_repo as repo
from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase
from engines import document_intake as di
from engines import financials as fin
from engines import pdf_extraction as pe
from tests.pdf_fixture_builder import write_pdf

SYNTH_SHA = hashlib.sha256(b"synthetic document one").hexdigest()


@pytest.fixture
def adb():
    d = SQLiteDatabase()
    d.role = "archive"
    gate.apply(d, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    yield d
    d.close()


def _meta(sha=SYNTH_SHA, **over):
    m = {
        "report_sha256": sha,
        "psx_symbol": "OGDC",
        "company_id": "co-ogdc",
        "doc_type": "annual",
        "financial_year": 2025,
        "period_end": "2025-06-30",
        "consolidation": "unconsolidated",
        "audit_status": "audited",
        "original_filename": "ogdc-2025-synthetic.pdf",
        "vault_ref": f"{sha}.pdf",
        "source_id": "company_reports_manual",
        "retrieved_at_utc": "2026-11-10T10:00:00Z",
    }
    m.update(over)
    return m


def _line(**over):
    ln = {
        "statement": "BS",
        "line_no": 1,
        "raw_label": "Total assets",
        "column_period_end": "2025-06-30",
        "value": 500000.0,
        "extraction_method": "pdf_text",
        "page": 2,
        "note_ref": None,
        "canonical_code": "total_assets",
    }
    ln.update(over)
    return ln


# ------------------------------------------------------------------ registry


def test_registration_is_idempotent_on_the_file_hash(adb):
    assert repo.register_document(adb, _meta())["status"] == "registered"
    assert repo.register_document(adb, _meta())["status"] == "duplicate"
    assert adb.execute("SELECT COUNT(*) AS n FROM archive_document_registry")[0]["n"] == 1


def test_a_new_file_for_the_same_period_is_a_new_version_not_an_overwrite(adb):
    repo.register_document(adb, _meta())
    other = hashlib.sha256(b"restated version").hexdigest()
    out = repo.register_document(adb, _meta(sha=other, vault_ref=f"{other}.pdf"))
    assert out["document_version"] == 2
    assert adb.execute("SELECT COUNT(*) AS n FROM archive_document_registry")[0]["n"] == 2


@pytest.mark.parametrize(
    "over",
    [
        {"report_sha256": "not-a-hash"},
        {"report_sha256": "A" * 64},
        {"original_filename": "../../etc/passwd.pdf"},
        {"vault_ref": "data\\vault\\x.pdf"},
        {"doc_type": "weekly"},
        {"consolidation": "group"},
        {"psx_symbol": ""},
    ],
)
def test_registry_refuses_bad_identifiers_and_paths(adb, over):
    with pytest.raises(ValueError):
        repo.register_document(adb, _meta(**over))
    assert adb.execute("SELECT COUNT(*) AS n FROM archive_document_registry")[0]["n"] == 0


def test_registry_refuses_the_operational_role(adb):
    adb.role = "main"
    with pytest.raises(repo.ArchiveRoutingError):
        repo.register_document(adb, _meta())


# ------------------------------------------------------------------ extraction evidence


def test_line_items_keep_page_and_note_evidence_and_are_not_duplicated_on_reprocessing(adb):
    repo.register_document(adb, _meta())
    lines = [
        _line(note_ref="12", page=3),
        _line(line_no=2, raw_label="Total equity", canonical_code="total_equity"),
    ]
    first = repo.store_line_items(
        adb, SYNTH_SHA, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    again = repo.store_line_items(
        adb, SYNTH_SHA, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    assert first == {"inserted": 2, "already_present": 0} and again == {"inserted": 0, "already_present": 2}
    row = adb.execute("SELECT page, note_ref, value, unit_scale FROM archive_line_items WHERE line_no = 1")[0]
    assert row["page"] == 3 and row["note_ref"] == "12" and row["value"] == 500000.0


def test_missing_value_is_stored_as_not_reported_never_as_zero(adb):
    repo.register_document(adb, _meta())
    repo.store_line_items(
        adb,
        SYNTH_SHA,
        [_line(value=None, value_state="not_reported")],
        consolidation="unconsolidated",
        currency="PKR",
        unit_scale=1000,
    )
    row = adb.execute("SELECT value, value_state FROM archive_line_items")[0]
    assert row["value"] is None and row["value_state"] == "not_reported"


def test_a_reported_value_cannot_be_missing_and_a_zero_cannot_masquerade_as_missing(adb):
    repo.register_document(adb, _meta())
    with pytest.raises(ValueError, match="needs a value"):
        repo.store_line_items(
            adb,
            SYNTH_SHA,
            [_line(value=None, value_state="reported")],
            consolidation="unconsolidated",
            currency="PKR",
            unit_scale=1000,
        )
    with pytest.raises(Exception, match="CHECK constraint"):  # the database refuses a zero for a missing line
        adb.batch(
            [
                (
                    "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, "
                    "canonical_code, column_period_end, is_comparative, value, value_state, currency, "
                    "unit_scale, consolidation, page, note_ref, extraction_method, confidence) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        SYNTH_SHA,
                        "BS",
                        9,
                        "x",
                        None,
                        "2025-06-30",
                        0,
                        0.0,
                        "not_reported",
                        "PKR",
                        1000,
                        "unconsolidated",
                        1,
                        None,
                        "pdf_text",
                        None,
                    ),
                )
            ],
            transactional=True,
        )


def test_line_items_cannot_be_edited_or_deleted(adb):
    repo.register_document(adb, _meta())
    repo.store_line_items(
        adb, SYNTH_SHA, [_line()], consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    with pytest.raises(Exception, match="immutable|append-only"):
        adb.batch([("UPDATE archive_line_items SET value = 1", ())], rollback=True)
    with pytest.raises(Exception, match="immutable|append-only"):
        adb.batch([("DELETE FROM archive_line_items", ())], rollback=True)


def test_a_correction_is_a_review_and_the_original_value_is_kept(adb):
    repo.register_document(adb, _meta())
    repo.store_line_items(
        adb, SYNTH_SHA, [_line()], consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    line_id = adb.execute("SELECT line_id FROM archive_line_items")[0]["line_id"]
    with pytest.raises(ValueError, match="corrected value"):
        repo.record_review(adb, line_id=line_id, decision="corrected", reviewer="owner", note="typo")
    repo.record_review(
        adb,
        line_id=line_id,
        decision="corrected",
        corrected_value=495000.0,
        reviewer="owner",
        note="re-read against page 2",
    )
    assert adb.execute("SELECT value FROM archive_line_items")[0]["value"] == 500000.0
    assert adb.execute("SELECT corrected_value FROM archive_line_reviews")[0]["corrected_value"] == 495000.0


def test_processing_history_is_append_only(adb):
    repo.register_document(adb, _meta())
    repo.record_processing(adb, SYNTH_SHA, "extracting", "start")
    repo.record_processing(adb, SYNTH_SHA, "needs_review", "one check failed")
    assert adb.execute("SELECT COUNT(*) AS n FROM archive_processing_events")[0]["n"] == 3
    with pytest.raises(Exception, match="append-only|immutable"):
        adb.batch([("DELETE FROM archive_processing_events", ())], rollback=True)


# ------------------------------------------------------------------ reconciliation


def test_reconciliation_results_record_differences_and_unverifiable_checks(adb):
    repo.register_document(adb, _meta())
    checks = [
        {"check": "balance_sheet", "result": "fail", "reported": 500.0, "expected": 450.0},
        {"check": "cash_flow", "result": "not_checkable"},
    ]
    repo.store_reconciliation(
        adb, SYNTH_SHA, checks, consolidation="unconsolidated", column_period_end="2025-06-30", tolerance=2.0
    )
    rows = {r["check_name"]: dict(r) for r in adb.execute("SELECT * FROM archive_reconciliation")}
    assert rows["balance_sheet"]["difference"] == 50.0 and rows["balance_sheet"]["result"] == "fail"
    assert rows["cash_flow"]["difference"] is None and rows["cash_flow"]["result"] == "not_checkable"


# ------------------------------------------------------------------ end to end: PDF -> vault -> evidence


def test_synthetic_pdf_to_reconciled_evidence_with_page_references(adb, tmp_path):
    """SYNTHETIC PDF. Proves the path: vault, extraction with pages, identity check, stored evidence, and that
    reprocessing the same file adds nothing."""
    pdf = write_pdf(
        tmp_path / "src.pdf",
        [
            [
                "Statement of financial position",
                "Total assets 1,000 900",
                "Total liabilities 600 500",
                "Total equity 400 400",
            ]
        ],
    )
    vault = di.vault_dir(tmp_path / "vault")
    stored, sha = di.store_original(pdf, vault)
    assert pe.sha256_file(stored) == sha  # the vault copy is byte-identical and named by its hash
    doc = pe.extract(stored)
    parsed = pe.to_statement_lines(doc, "BS", [1], columns=["2025-06-30", "2024-06-30"])
    codes = {
        "Total assets": "total_assets",
        "Total liabilities": "total_liabilities",
        "Total equity": "total_equity",
    }
    lines = [
        {
            "statement": "BS",
            "line_no": i + 1,
            "raw_label": ln["raw_label"],
            "column_period_end": ln["column_period_end"],
            "value": ln["value"],
            "page": ln["page"],
            "extraction_method": "pdf_text",
            "canonical_code": codes.get(ln["raw_label"]),
            "is_comparative": ln["column_period_end"] != "2025-06-30",
        }
        for i, ln in enumerate(parsed["lines"])
    ]
    assert lines and all(x["page"] == 1 for x in lines)  # every value keeps its page
    repo.register_document(adb, _meta(sha=sha, vault_ref=stored.name, original_filename="src.pdf"))
    repo.store_line_items(adb, sha, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000)
    current = {
        x["canonical_code"]: x["value"]
        for x in lines
        if x["column_period_end"] == "2025-06-30" and x["canonical_code"]
    }
    checks = fin.identity_checks(current)
    assert any(c["result"] == "fail" for c in checks) is False  # 600 + 400 = 1,000 balances
    repo.store_reconciliation(
        adb, sha, checks, consolidation="unconsolidated", column_period_end="2025-06-30", tolerance=2.0
    )
    assert (
        repo.store_line_items(
            adb, sha, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000
        )["inserted"]
        == 0
    )


def test_tampered_vault_file_is_detected_by_hash(tmp_path):
    pdf = write_pdf(tmp_path / "src.pdf", [["Statement of financial position", "Total assets 1 2"]])
    vault = di.vault_dir(tmp_path / "vault")
    stored, sha = di.store_original(pdf, vault)
    assert di.verify_vault_file(stored, sha) is True
    stored.write_bytes(stored.read_bytes() + b"tamper")
    assert di.verify_vault_file(stored, sha) is False
    with pytest.raises(di.IntakeError, match="different bytes"):
        di.store_original(tmp_path / "src.pdf", vault)  # a second copy never overwrites the vault file


# ------------------------------------------------------------------ cash-flow identity (pure, no database)

def test_cash_flow_identity_passes_when_opening_plus_movement_equals_closing():
    checks = {c["check"]: c["result"] for c in fin.identity_checks(
        {"opening_cash": 100.0, "net_change_in_cash": -30.0, "closing_cash": 70.0})}
    assert checks["cash_flow"] == "pass"


def test_cash_flow_identity_flags_a_discrepancy_and_never_changes_the_numbers():
    values = {"opening_cash": 100.0, "net_change_in_cash": -30.0, "closing_cash": 80.0}
    check = next(c for c in fin.identity_checks(values) if c["check"] == "cash_flow")
    assert check["result"] == "fail" and check["expected"] == 70.0 and check["reported"] == 80.0
    assert values == {"opening_cash": 100.0, "net_change_in_cash": -30.0, "closing_cash": 80.0}


def test_missing_opening_cash_is_not_checkable_not_zero():
    check = next(c for c in fin.identity_checks({"closing_cash": 70.0, "net_change_in_cash": -30.0})
                 if c["check"] == "cash_flow")
    assert check["result"] == "not_checkable" and check["missing"] == ["opening_cash"]
