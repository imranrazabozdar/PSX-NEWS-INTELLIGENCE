"""Step 5: reconciliation identities are enforced, stored with their result and delta, and exceptions are
disclosed, never hidden. Throwaway in-memory archive; no remote database."""

from pathlib import Path

import pytest

from database import financial_repo as repo
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import statement_pipeline as sp
from tests.test_real_report_regression import _pipeline

ARCHIVE = Path(__file__).resolve().parents[1] / "database" / "archive_migrations"
SHA = "d" * 64


def _as_role(db, role):
    db.role = role
    return db


@pytest.fixture
def adb():
    db = SQLiteDatabase(":memory:")
    migrate(db, directory=ARCHIVE)
    _as_role(db, "archive")
    db.execute(
        "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id, doc_type, "
        "financial_year, period_end, consolidation, audit_status, original_filename, vault_ref, source_id, "
        "retrieved_at_utc, registered_at_utc) VALUES (?, 'UBL', 'co-1', 'annual', 2025, '2025-12-31', "
        "'unconsolidated', 'audited', 'r.pdf', ?, 'test', '2026-11-11T00:00:00Z', '2026-11-11T00:00:00Z')",
        [SHA, f"{SHA}.pdf"],
    )
    db.execute(
        "INSERT INTO archive_extraction_runs(report_sha256, extractor_version, started_at_utc) "
        "VALUES (?, 'test/1', '2026-11-11T00:00:00Z')",
        [SHA],
    )
    yield db
    db.close()


def _run(db):
    return db.execute("SELECT run_id FROM archive_extraction_runs")[0]["run_id"]


def _row(**over):
    base = {
        "identity": "assets_equal_liabilities_plus_equity",
        "consolidation": "unconsolidated",
        "column_period_end": "2025-12-31",
        "left_value": 100.0,
        "right_value": 100.0,
        "delta": 0.0,
        "tolerance": 1.0,
        "status": "reconciled",
        "reason": "test",
    }
    base.update(over)
    return base


def test_migration_0008_applies(adb):
    assert adb.execute("SELECT name FROM sqlite_master WHERE name = 'archive_identity_checks'")


def test_a_reconciled_identity_is_stored_with_its_zero_delta(adb):
    repo.store_identity_checks(adb, _run(adb), [_row()])
    row = adb.execute("SELECT status, delta, report_sha256 FROM archive_identity_checks")[0]
    assert row["status"] == "reconciled" and row["delta"] == 0.0 and row["report_sha256"] == SHA


def test_an_unreconciled_identity_keeps_its_delta(adb):
    """The exception is disclosed: stored as unreconciled with the discrepancy, never forced to pass."""
    repo.store_identity_checks(
        adb, _run(adb), [_row(right_value=90.0, delta=10.0, status="unreconciled", reason="exception")]
    )
    row = adb.execute("SELECT status, delta FROM archive_identity_checks")[0]
    assert row["status"] == "unreconciled" and row["delta"] == 10.0


def test_insufficient_inputs_carry_no_delta(adb):
    repo.store_identity_checks(
        adb,
        _run(adb),
        [
            _row(
                left_value=None,
                right_value=None,
                delta=None,
                status="insufficient_data",
                reason="not extracted",
            )
        ],
    )
    row = adb.execute("SELECT status, delta FROM archive_identity_checks")[0]
    assert row["status"] == "insufficient_data" and row["delta"] is None


def test_a_reconciled_result_outside_its_tolerance_is_refused_by_the_schema(adb):
    with pytest.raises(DatabaseError):
        adb.execute(
            "INSERT INTO archive_identity_checks(run_id, report_sha256, identity, consolidation, "
            "column_period_end, left_value, right_value, delta, tolerance, status, reason, recorded_at_utc) "
            "VALUES (?, ?, 'pbt_less_tax_equals_pat', 'unconsolidated', '2025-12-31', 1, 2, 1, 0, "
            "'reconciled', "
            "'x', '2026-11-11T00:00:00Z')",
            [_run(adb), SHA],
        )


def test_an_unknown_identity_is_refused(adb):
    with pytest.raises(ValueError, match="unknown identity"):
        repo.store_identity_checks(adb, _run(adb), [_row(identity="assets_equal_something_else")])


def test_identity_results_are_immutable(adb):
    repo.store_identity_checks(adb, _run(adb), [_row()])
    with pytest.raises(DatabaseError, match="immutable"):
        adb.execute("UPDATE archive_identity_checks SET delta = 5")


def test_each_reconciliation_check_maps_to_its_identity_and_keeps_the_delta():
    recon = {
        "checks": [
            {
                "check": "balance_sheet",
                "column_period_end": "2025-12-31",
                "reported": 10.0,
                "expected": 12.0,
                "discrepancy": 2.0,
                "allowance": 1.0,
                "status": "UNRECONCILED",
                "missing": [],
            },
            {
                "check": "income_statement",
                "column_period_end": "2025-12-31",
                "reported": 5.0,
                "expected": 5.0,
                "discrepancy": 0.0,
                "allowance": 1.0,
                "status": "RECONCILED",
                "missing": [],
            },
            {
                "check": "cash_flow",
                "column_period_end": "2025-12-31",
                "reported": None,
                "expected": None,
                "discrepancy": None,
                "allowance": 0.0,
                "status": "INSUFFICIENT_DATA",
                "missing": ["opening_cash"],
            },
        ]
    }
    rows = {r["identity"]: r for r in sp.identity_rows(recon, consolidation="unconsolidated")}
    assert rows["assets_equal_liabilities_plus_equity"]["status"] == "unreconciled"
    assert rows["assets_equal_liabilities_plus_equity"]["delta"] == 2.0
    assert rows["pbt_less_tax_equals_pat"]["status"] == "reconciled"
    assert rows["pbt_less_tax_equals_pat"]["delta"] == 0.0
    cash = rows["opening_cash_plus_movement_equals_closing_cash"]
    assert cash["status"] == "insufficient_data" and cash["delta"] is None
    assert "opening_cash" in cash["reason"]


def test_the_real_ubl_statements_store_their_identities_with_zero_deltas(adb):
    rec = _pipeline("ubl_ar2025")
    rows = sp.identity_rows(rec, consolidation="unconsolidated")
    repo.store_identity_checks(adb, _run(adb), rows)
    stored = {
        r["identity"]: r for r in adb.execute("SELECT identity, status, delta FROM archive_identity_checks")
    }
    for name in (
        "assets_equal_liabilities_plus_equity",
        "pat_plus_oci_equals_total_comprehensive_income",
        "pbt_less_tax_equals_pat",
        "opening_cash_plus_movement_equals_closing_cash",
        "equity_closing_equals_balance_sheet_equity",
    ):
        assert stored[name]["status"] == "reconciled", name
        assert stored[name]["delta"] == 0.0, name
