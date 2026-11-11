"""Step 3: the full archive status vocabulary is storable, applied, and wired to statement and fact results.

Throwaway in-memory archive; no remote database."""

from pathlib import Path

import pytest

from database import financial_repo as repo
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import statement_pipeline as sp
from engines import status_vocabulary as sv

ARCHIVE = Path(__file__).resolve().parents[1] / "database" / "archive_migrations"
SHA = "c" * 64


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
        "financial_year, "
        "period_end, consolidation, audit_status, original_filename, vault_ref, source_id, retrieved_at_utc, "
        "registered_at_utc) VALUES (?, 'LUCK', 'co-1', 'annual', 2026, '2026-06-30', 'unconsolidated', "
        "'audited', 'r.pdf', ?, 'test', '2026-11-11T00:00:00Z', '2026-11-11T00:00:00Z')",
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


def _row(status, **over):
    base = {
        "statement_type": "BS",
        "consolidation": "unconsolidated",
        "column_period_end": "2026-06-30",
        "status": status,
        "reason": f"test {status}",
    }
    base.update(over)
    return base


def test_the_vocabulary_is_exactly_the_seven_brief_codes(adb):
    codes = {r["code"] for r in adb.execute("SELECT code FROM archive_status_codes")}
    assert (
        codes
        == set(sv.VOCABULARY)
        == {
            "reconciled",
            "reconciled_with_rounding",
            "unreconciled",
            "insufficient_data",
            "not_verifiable_from_disclosure",
            "unmapped",
            "requires_review",
        }
    )


@pytest.mark.parametrize("status", sv.VOCABULARY)
def test_each_status_is_storable_per_statement(adb, status):
    repo.store_statement_statuses(
        adb, _run(adb), [_row(status, statement_type="BS", column_period_end="2026-06-30")]
    )
    stored = adb.execute("SELECT status FROM archive_statement_status")
    assert [r["status"] for r in stored] == [status]


@pytest.mark.parametrize("status", sv.VOCABULARY)
def test_each_status_is_storable_per_fact(adb, status):
    sp_stub = {
        "statement_type": "BS",
        "consolidation": "unconsolidated",
        "column_period_end": "2026-06-30",
        "line_no": 1,
        "line_item_name": "Cash",
        "canonical_code": "cash",
        "reported_amount": 1.0,
        "currency": "PKR",
        "unit_scale": 1000,
        "extraction_method": "pdf_text",
        "value_state": "reported",
        "period_end": "2026-06-30",
        "pdf_page_number": 8,
    }
    repo.store_versioned_lines(
        adb, _run(adb), [sp_stub], extractor_version="test/1", symbol="LUCK", document_id=SHA
    )
    repo.store_fact_statuses(
        adb,
        _run(adb),
        [
            {
                "statement_type": "BS",
                "line_no": 1,
                "column_period_end": "2026-06-30",
                "consolidation": "unconsolidated",
                "status": status,
                "reason": "test",
            }
        ],
    )
    assert [r["status"] for r in adb.execute("SELECT status FROM archive_fact_status")] == [status]


def test_a_status_outside_the_vocabulary_is_refused(adb):
    with pytest.raises(ValueError, match="vocabulary"):
        repo.store_statement_statuses(adb, _run(adb), [_row("RECONCILED")])  # legacy code, not stored raw
    with pytest.raises(DatabaseError):
        adb.execute(
            "INSERT INTO archive_statement_status(run_id, report_sha256, statement_type, consolidation, "
            "column_period_end, status, reason, recorded_at_utc) VALUES (?, ?, 'BS', 'unconsolidated', "
            "'2026-06-30', 'maybe', 'x', '2026-11-11T00:00:00Z')",
            [_run(adb), SHA],
        )


def test_statement_status_rows_are_immutable(adb):
    repo.store_statement_statuses(adb, _run(adb), [_row("reconciled")])
    with pytest.raises(DatabaseError, match="immutable"):
        adb.execute("UPDATE archive_statement_status SET status = 'unreconciled'")


# --------------------------------------------------------------------------- the rules


@pytest.mark.parametrize(
    "legacy,code",
    [
        ("RECONCILED", "reconciled"),
        ("RECONCILED_WITH_ROUNDING", "reconciled_with_rounding"),
        ("UNRECONCILED", "unreconciled"),
        ("INSUFFICIENT_DATA", "insufficient_data"),
    ],
)
def test_legacy_check_codes_map_to_the_vocabulary(legacy, code):
    assert sv.from_check_status(legacy) == code


def test_unknown_legacy_code_is_refused():
    with pytest.raises(ValueError):
        sv.from_check_status("MAYBE")


@pytest.mark.parametrize(
    "checks,kwargs,expected",
    [
        (["RECONCILED"], {}, "reconciled"),
        (["RECONCILED_WITH_ROUNDING"], {}, "reconciled_with_rounding"),
        (["RECONCILED", "UNRECONCILED"], {}, "unreconciled"),
        (["INSUFFICIENT_DATA"], {}, "insufficient_data"),
        (["RECONCILED"], {"unmapped": 2}, "unmapped"),
        (["RECONCILED"], {"requires_review": ["layout ambiguous"]}, "requires_review"),
        (["RECONCILED"], {"not_verifiable": "IAS 7.7"}, "not_verifiable_from_disclosure"),
        ([], {}, "insufficient_data"),
    ],
)
def test_statement_status_precedence(checks, kwargs, expected):
    status, reason = sv.statement_status(checks, **kwargs)
    assert status == expected and reason


def test_a_failed_identity_is_never_hidden_by_a_weaker_status():
    assert sv.statement_status(["UNRECONCILED"], not_verifiable="IAS 7.7", unmapped=3)[0] == "unreconciled"
    assert (
        sv.statement_status(["RECONCILED"], not_verifiable="IAS 7.7", requires_review=["x"])[0]
        == "not_verifiable_from_disclosure"
    )


def test_not_verifiable_is_wired_to_the_cash_equivalent_fact_when_ias7_cannot_prove_maturity():
    tagged = {
        "lines": [
            {
                "statement_type": "BS",
                "canonical_code": "cash_and_equivalents",
                "line_no": 1,
                "column_period_end": "2026-06-30",
                "consolidation": "unconsolidated",
            },
            {
                "statement_type": "BS",
                "canonical_code": "ppe",
                "line_no": 2,
                "column_period_end": "2026-06-30",
                "consolidation": "unconsolidated",
            },
        ]
    }
    rec = {"checks": [{"check": "balance_sheet", "column_period_end": "2026-06-30", "status": "RECONCILED"}]}
    _, facts = sp.statuses_for(tagged, rec, ias7_status=sv.IAS7_NOT_VERIFIABLE)
    by_line = {f["line_no"]: f["status"] for f in facts}
    assert by_line == {1: "not_verifiable_from_disclosure", 2: "reconciled"}


def test_an_unmapped_line_is_unmapped_and_a_failed_statement_marks_its_facts_unreconciled():
    tagged = {
        "lines": [
            {
                "statement_type": "BS",
                "canonical_code": None,
                "line_no": 1,
                "column_period_end": "2026-06-30",
                "consolidation": "unconsolidated",
            },
            {
                "statement_type": "BS",
                "canonical_code": "ppe",
                "line_no": 2,
                "column_period_end": "2026-06-30",
                "consolidation": "unconsolidated",
            },
        ]
    }
    rec = {
        "checks": [{"check": "balance_sheet", "column_period_end": "2026-06-30", "status": "UNRECONCILED"}]
    }
    statements, facts = sp.statuses_for(tagged, rec)
    assert statements[0]["status"] == "unreconciled"
    assert {f["line_no"]: f["status"] for f in facts} == {1: "unmapped", 2: "unreconciled"}
