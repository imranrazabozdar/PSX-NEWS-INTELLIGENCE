"""Dual-database configuration: operational (main) and archive handles, routing and the archive schema.

Two separate SQLite files stand in for the two Turso databases. The handlers are exercised through their real
environment variables. No network access and no production credentials are used. Financial values are the
SYNTHETIC hand-built fixtures from tests/test_m2_m3_financials.py.
"""

from __future__ import annotations

import pytest

from database import financial_repo as repo
from database.connection import (
    DatabaseConfigError,
    SQLiteDatabase,
    connect_archive,
    connect_main,
)
from database.migrate import migrate
from database.seed_loader import load
from engines import financials as fin
from tests import test_m2_m3_financials as m2
from tests.test_financial_pipeline import _import

MAIN_ENV = "PSXNI_TURSO_DATABASE_URL"
MAIN_TOK = "PSXNI_TURSO_AUTH_TOKEN"
ARC_ENV = "PSXNI_ARCHIVE_TURSO_URL"
ARC_TOK = "PSXNI_ARCHIVE_TURSO_AUTH_TOKEN"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (MAIN_ENV, MAIN_TOK, ARC_ENV, ARC_TOK, "PSXNI_KILL_SWITCH"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def files(tmp_path):
    main_path, arc_path = tmp_path / "main.db", tmp_path / "archive.db"
    m = SQLiteDatabase(str(main_path))
    migrate(m)
    load(m)
    fin.load_mappings(m)
    m.close()
    a = SQLiteDatabase(str(arc_path))
    _apply_approved(_as_role(a, "archive"))
    a.close()
    return main_path, arc_path


def _apply_approved(db):
    """Test setup applies the schema through the approved gate, with the approval string."""
    from database.archive_migrations import archive_gate as gate
    env = {gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    return gate.apply(db, dry_run=False, purpose=gate.PURPOSE, env=env)


def _as_role(db, role):
    db.role = role
    return db


def _url(path) -> str:
    return f"sqlite://{path}"  # sqlite:///abs/path -> /abs/path


# ------------------------------------------------------------------ handler configuration (fail closed)

def test_archive_needs_its_own_url(monkeypatch):
    with pytest.raises(DatabaseConfigError, match="PSXNI_ARCHIVE_TURSO_URL"):
        connect_archive()


def test_archive_never_falls_back_to_the_main_token(monkeypatch):
    monkeypatch.setenv(MAIN_TOK, "main-token-value")  # must not be used by the archive handler
    with pytest.raises(DatabaseConfigError, match="PSXNI_ARCHIVE_TURSO_AUTH_TOKEN"):
        connect_archive("https://archive-example.invalid")  # refused before any network call


def test_archive_refuses_the_main_database_even_under_another_spelling(monkeypatch):
    monkeypatch.setenv(MAIN_ENV, "libsql://psx-main.example.invalid")
    with pytest.raises(DatabaseConfigError, match="must be separate"):
        connect_archive("https://PSX-MAIN.example.invalid/", "t")


def test_main_refuses_the_archive_url(monkeypatch):
    monkeypatch.setenv(ARC_ENV, "libsql://psx-archive.example.invalid")
    with pytest.raises(DatabaseConfigError, match="must be separate"):
        connect_main("https://psx-archive.example.invalid", "t")


def test_main_refuses_a_database_holding_archive_tables(files):
    _, arc_path = files
    with pytest.raises(DatabaseConfigError, match="archive tables"):
        connect_main(_url(arc_path), "")


def test_archive_refuses_a_database_holding_operational_tables(files):
    main_path, _ = files
    with pytest.raises(DatabaseConfigError, match="operational tables"):
        connect_archive(_url(main_path), "")


def test_handles_carry_their_role_and_the_archive_uses_its_own_ledger(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        assert mdb.role == "main" and adb.role == "archive"
        arc_versions = [r["name"] for r in adb.execute("SELECT name FROM schema_migrations")]
        main_versions = [r["name"] for r in mdb.execute("SELECT name FROM schema_migrations")]
        assert arc_versions == ["financial_archive", "disclosures", "document_registry",
                                "extraction_evidence"]
        assert "financial_documents" in main_versions and len(main_versions) == 14
    finally:
        mdb.close()
        adb.close()


# ------------------------------------------------------------- routing: each repository binds to its role

def test_repositories_refuse_a_handle_with_the_wrong_role(files):
    main_path, arc_path = files
    m = SQLiteDatabase(str(main_path))
    a = SQLiteDatabase(str(arc_path))
    m.role, a.role = "main", "archive"
    try:
        with pytest.raises(repo.ArchiveRoutingError):
            repo.annual_series(m, "x", scope="unconsolidated")  # history read from the main database
        with pytest.raises(repo.ArchiveRoutingError):
            repo.archive_promoted(a, a, 1)  # the operational side must be the main handle
        with pytest.raises(repo.ArchiveRoutingError):
            repo.require_archive_ready(m)  # the operational database is refused before anything else
    finally:
        m.close()
        a.close()


# ------------------------------------------------------------------ archiving and multi-period reads

def _promote_two_years(main_db):
    r24 = _import(main_db, m2._corp(period="2024-06-30", prev="2023-06-30"), "p24")
    r25 = _import(main_db, m2._corp(), "p25")
    fin.promote(main_db, r24["report_id"])
    fin.promote(main_db, r25["report_id"])
    return r24["report_id"], r25["report_id"]


def _company(db):
    return db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' "
                      "AND value = 'OGDC' AND valid_to IS NULL")[0]["company_id"]


def test_archived_tuples_match_the_promoted_metrics_and_are_idempotent(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        r24, r25 = _promote_two_years(mdb)
        assert repo.archive_promoted(mdb, adb, r25)["archived"] > 0
        promoted = mdb.execute("SELECT COUNT(*) AS n FROM financial_metrics WHERE report_id = ?",
                               (r25,))[0]["n"]
        assert adb.execute("SELECT COUNT(*) AS n FROM archive_financial_tuples")[0]["n"] == promoted
        repo.archive_promoted(mdb, adb, r25)  # a second run adds nothing
        assert adb.execute("SELECT COUNT(*) AS n FROM archive_financial_tuples")[0]["n"] == promoted
        row = adb.execute("SELECT value, unit FROM archive_financial_tuples "
                          "WHERE metric_name = 'total_assets' "
                          "AND period_end_date = '2025-06-30'")[0]
        assert row["value"] == pytest.approx(500_000.0) and row["unit"] == "PKR"  # 500 thousand, scaled once
    finally:
        mdb.close()
        adb.close()


def test_unreconciled_report_is_not_archived(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        bad = _import(mdb, m2._corp(overrides={("Total equity", "2025-06-30"): 1.0}), "bad")
        out = repo.archive_promoted(mdb, adb, bad["report_id"])
        assert out["archived"] == 0 and "refused" in out
        assert adb.execute("SELECT COUNT(*) AS n FROM archive_reports")[0]["n"] == 0
    finally:
        mdb.close()
        adb.close()


def test_multi_period_series_is_read_from_the_archive_only(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        r24, r25 = _promote_two_years(mdb)
        repo.archive_promoted(mdb, adb, r24)
        repo.archive_promoted(mdb, adb, r25)
        s = repo.annual_series(adb, _company(mdb), scope="unconsolidated")
        assert [p["period_end"] for p in s["periods"]] == ["2024-06-30", "2025-06-30"]
        p25 = s["periods"][1]["metrics"]
        assert p25["gross_profit"] / p25["revenue"] == pytest.approx(0.4)
        assert s["gaps"] == [] and s["conflicts"] == []
        # the archive, not the operational database, holds the history: main has no archive tables
        assert "archive_financial_tuples" not in {r["name"] for r in mdb.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        mdb.close()
        adb.close()


def test_single_archived_year_gives_one_period_and_no_gap(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        r24 = _import(mdb, m2._corp(period="2024-06-30", prev="2023-06-30"), "g24")
        fin.promote(mdb, r24["report_id"])
        repo.archive_promoted(mdb, adb, r24["report_id"])
        s = repo.annual_series(adb, _company(mdb), scope="unconsolidated")
        assert len(s["periods"]) == 1 and s["gaps"] == []
    finally:
        mdb.close()
        adb.close()


# ------------------------------------------------------------------ archive schema: no bloat, append-only

def test_archive_schema_holds_no_binary_content_and_no_file_paths(files):
    _, arc_path = files
    adb = SQLiteDatabase(str(arc_path))
    try:
        for table in ("archive_reports", "archive_financial_tuples"):
            cols = adb.execute(f"PRAGMA table_info({table})")
            for c in cols:
                assert "BLOB" not in (c["type"] or "").upper(), f"{table}.{c['name']} stores binary data"
                assert c["name"] not in {"content", "data", "pdf", "path", "file_path", "bytes"}, c["name"]
    finally:
        adb.close()


def test_archive_rows_hold_the_hash_and_a_file_name_never_a_path(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        _, r25 = _promote_two_years(mdb)
        repo.archive_promoted(mdb, adb, r25)
        row = adb.execute("SELECT report_sha256, vault_ref FROM archive_reports")[0]
        assert len(row["report_sha256"]) == 64 and row["vault_ref"] == f"{row['report_sha256']}.pdf"
        assert "/" not in row["vault_ref"] and "\\" not in row["vault_ref"]
    finally:
        mdb.close()
        adb.close()


def test_archive_tuples_are_append_only(files):
    main_path, arc_path = files
    mdb = connect_main(_url(main_path), "")
    adb = connect_archive(_url(arc_path), "")
    try:
        _, r25 = _promote_two_years(mdb)
        repo.archive_promoted(mdb, adb, r25)
        with pytest.raises(Exception, match="append-only|immutable"):
            adb.execute("DELETE FROM archive_financial_tuples")
        with pytest.raises(Exception, match="immutable"):
            adb.execute("UPDATE archive_financial_tuples SET value = 0")
    finally:
        mdb.close()
        adb.close()
