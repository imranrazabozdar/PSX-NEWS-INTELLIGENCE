"""Step 2: every stored fact and reconciliation result carries the SHA-256 of its source document.

Runs on a throwaway in-memory SQLite archive. The archive migrations are applied in order (0001-0006); nothing
touches a remote database."""

from pathlib import Path

import pytest

from database import financial_repo as repo
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate

ARCHIVE = Path(__file__).resolve().parents[1] / "database" / "archive_migrations"
SHA = "a" * 64
OTHER = "b" * 64
REGISTRY_SQL = (
    "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id, doc_type, "
    "financial_year, "
    "period_end, consolidation, audit_status, original_filename, vault_ref, source_id, retrieved_at_utc, "
    "registered_at_utc) VALUES (?, 'LUCK', 'co-1', 'annual', 2026, '2026-06-30', 'unconsolidated', "
    "'audited', 'report.pdf', ?, 'test', '2026-11-11T00:00:00Z', '2026-11-11T00:00:00Z')"
)
RUN_SQL = (
    "INSERT INTO archive_extraction_runs(report_sha256, extractor_version, started_at_utc) "
    "VALUES (?, 'test-extractor/1', '2026-11-11T00:00:00Z')"
)
RAW_LINE_SQL = (
    "INSERT INTO archive_line_items_v2(run_id, extractor_version, document_id, {extra} symbol, "
    "period_end, statement_type, line_no, line_item_name, column_period_end, reported_amount, value_state, "
    "currency, unit_scale, consolidation, extraction_method, processed_at_utc) "
    "VALUES (?, 'test-extractor/1', ?, {vals} "
    "'LUCK', '2026-06-30', 'BS', 9, 'x', '2026-06-30', 1.0, 'reported', 'PKR', 1000, 'unconsolidated', "
    "'pdf_text', '2026-11-11T00:00:00Z')"
)
RAW_RECON_SQL = (
    "INSERT INTO archive_reconciliation_v2(run_id, check_name, column_period_end, consolidation, tolerance, "
    "status, recorded_at_utc, report_sha256) VALUES (?, 'x', '2026-06-30', 'unconsolidated', 0, "
    "'RECONCILED', '2026-11-11T00:00:00Z', ?)"
)


def _as_role(db, role):
    db.role = role
    return db


@pytest.fixture
def adb():
    db = SQLiteDatabase(":memory:")
    migrate(db, directory=ARCHIVE)
    _as_role(db, "archive")
    db.execute(REGISTRY_SQL, [SHA, f"{SHA}.pdf"])
    db.execute(RUN_SQL, [SHA])
    yield db
    db.close()


def _run_id(db):
    return db.execute("SELECT run_id FROM archive_extraction_runs")[0]["run_id"]


def _line(**over):
    base = {
        "period_end": "2026-06-30",
        "statement_type": "BS",
        "line_no": 1,
        "line_item_name": "Cash",
        "canonical_code": "cash",
        "column_period_end": "2026-06-30",
        "reported_amount": 1000.0,
        "currency": "PKR",
        "unit_scale": 1000,
        "consolidation": "unconsolidated",
        "extraction_method": "pdf_text",
        "pdf_page_number": 8,
        "value_state": "reported",
    }
    base.update(over)
    return base


def test_migration_0006_applies_and_the_provenance_view_exists(adb):
    view = adb.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='v_fact_provenance'")
    assert view
    assert adb.execute("SELECT MAX(version) AS v FROM schema_migrations")[0]["v"] == 6


def test_every_written_fact_carries_the_document_hash(adb):
    repo.store_versioned_lines(
        adb,
        _run_id(adb),
        [_line(line_no=1), _line(line_no=2, line_item_name="Debt")],
        extractor_version="test-extractor/1",
        symbol="LUCK",
        document_id=SHA,
    )
    rows = adb.execute("SELECT report_sha256, document_id FROM archive_line_items_v2")
    assert len(rows) == 2
    assert all(r["report_sha256"] == SHA == r["document_id"] for r in rows)
    prov = adb.execute("SELECT report_sha256, pdf_page_number FROM v_fact_provenance")
    assert all(p["report_sha256"] == SHA and p["pdf_page_number"] == 8 for p in prov)


def test_every_reconciliation_result_carries_the_run_document_hash(adb):
    check = {
        "check": "balance_sheet",
        "column_period_end": "2026-06-30",
        "reported": 10.0,
        "expected": 10.0,
        "discrepancy": 0.0,
        "allowance": 1.0,
        "status": "RECONCILED",
    }
    repo.store_versioned_reconciliation(adb, _run_id(adb), [check], consolidation="unconsolidated")
    assert adb.execute("SELECT report_sha256 FROM archive_reconciliation_v2")[0]["report_sha256"] == SHA


def test_a_fact_without_its_hash_is_refused(adb):
    sql = RAW_LINE_SQL.format(extra="", vals="")
    with pytest.raises(DatabaseError, match="SHA-256"):
        adb.execute(sql, [_run_id(adb), SHA])


def test_a_fact_whose_hash_differs_from_its_document_is_refused(adb):
    sql = RAW_LINE_SQL.format(extra="report_sha256,", vals="?,")
    with pytest.raises(DatabaseError, match="SHA-256"):
        adb.execute(sql, [_run_id(adb), SHA, OTHER])


def test_a_result_whose_hash_differs_from_its_run_is_refused(adb):
    with pytest.raises(DatabaseError, match="SHA-256"):
        adb.execute(RAW_RECON_SQL, [_run_id(adb), OTHER])


def test_rows_are_still_immutable(adb):
    repo.store_versioned_lines(
        adb, _run_id(adb), [_line()], extractor_version="test-extractor/1", symbol="LUCK", document_id=SHA
    )
    with pytest.raises(DatabaseError, match="immutable"):
        adb.execute("UPDATE archive_line_items_v2 SET reported_amount = 2.0")
