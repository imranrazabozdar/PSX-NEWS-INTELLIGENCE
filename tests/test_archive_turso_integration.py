"""Archive database: DDL gate, read-only probe, and Turso integration tests.

Two layers:
* Offline tests always run. They prove the target guard refuses the real archive, the operational database and
  look-alike hosts, and that the DDL gate refuses without the exact approval string. No network.
* Turso tests run only when PSXNI_ARCHIVE_TEST_TURSO_URL and PSXNI_ARCHIVE_TEST_TURSO_AUTH_TOKEN name a
  DISPOSABLE archive-test database. They never target the real archive. Persistent writes happen only there.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import pytest

from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase, connect, same_database
from database.migrate import migrate as raw_migrate

TEST_URL_VAR = "PSXNI_ARCHIVE_TEST_TURSO_URL"
TEST_TOKEN_VAR = "PSXNI_ARCHIVE_TEST_TURSO_AUTH_TOKEN"  # noqa: S105 - a variable name
REAL_URL_VAR = "PSXNI_ARCHIVE_TURSO_URL"
REAL_TOKEN_VAR = "PSXNI_ARCHIVE_TURSO_AUTH_TOKEN"  # noqa: S105 - a variable name
MAIN_URL_VAR = "PSXNI_TURSO_DATABASE_URL"
# Host names of the real databases. Any test target containing one of these is refused, even when the real
# variables are not set in this environment.
REAL_HOST_MARKERS = ("psx-data-capture-turso202601", "psx-news-intelligence-imranrazabozdar")


def target_status(env) -> tuple[str, str]:
    """('skip' | 'fail' | 'ok', reason). Decides whether the Turso integration tests may touch a database."""
    url = env.get(TEST_URL_VAR, "")
    if not url:
        return "skip", f"{TEST_URL_VAR} not set: archive Turso integration tests not run"
    if not url.startswith(("libsql://", "https://")):
        return "fail", "the archive test URL must be a libsql:// or https:// Turso URL"
    if any(m in url.lower() for m in REAL_HOST_MARKERS):
        return "fail", "refusing: the test URL names a real database host"
    real = env.get(REAL_URL_VAR, "")
    if real and same_database(url, real):
        return "fail", "refusing: the test URL is the real archive database"
    main = env.get(MAIN_URL_VAR, "")
    if main and same_database(url, main):
        return "fail", "refusing: the test URL is the operational database"
    token = env.get(TEST_TOKEN_VAR, "")
    if not token:
        return "fail", f"{TEST_TOKEN_VAR} not set"
    real_token = env.get(REAL_TOKEN_VAR, "")
    if real_token and hmac.compare_digest(token, real_token):
        return "fail", "refusing: the test token is the real archive token"
    return "ok", ""


# ------------------------------------------------------------------ offline: target guard (always runs)


def test_guard_skips_when_unconfigured():
    assert target_status({})[0] == "skip"


@pytest.mark.parametrize(
    "url",
    [
        "libsql://psx-data-capture-turso202601.aws-us-east-1.turso.io",
        "https://PSX-DATA-CAPTURE-TURSO202601.aws-us-east-1.turso.io/",
        "libsql://psx-news-intelligence-imranrazabozdar.turso.io",
    ],
)
def test_guard_refuses_real_host_names_even_without_real_variables(url):
    status, reason = target_status({TEST_URL_VAR: url, TEST_TOKEN_VAR: "t"})
    assert status == "fail" and "real database" in reason


def test_guard_refuses_the_real_archive_url_by_identity(monkeypatch):
    env = {
        TEST_URL_VAR: "https://other-archive-test.example.invalid/",
        TEST_TOKEN_VAR: "t",
        REAL_URL_VAR: "libsql://other-archive-test.example.invalid",
    }
    assert target_status(env) == ("fail", "refusing: the test URL is the real archive database")


def test_guard_refuses_the_operational_url():
    env = {
        TEST_URL_VAR: "libsql://ops.example.invalid",
        TEST_TOKEN_VAR: "t",
        MAIN_URL_VAR: "https://OPS.example.invalid/",
    }
    assert target_status(env) == ("fail", "refusing: the test URL is the operational database")


def test_guard_refuses_the_real_token_and_a_missing_token():
    env = {TEST_URL_VAR: "libsql://archive-test.example.invalid", REAL_TOKEN_VAR: "same-secret"}
    assert target_status({**env, TEST_TOKEN_VAR: "same-secret"})[0] == "fail"
    assert target_status(env)[0] == "fail"


def test_guard_accepts_a_separate_disposable_target():
    env = {
        TEST_URL_VAR: "libsql://archive-test.example.invalid",
        TEST_TOKEN_VAR: "other-secret",
        REAL_URL_VAR: "libsql://archive.example.invalid",
        REAL_TOKEN_VAR: "real-secret",
        MAIN_URL_VAR: "libsql://ops.example.invalid",
    }
    assert target_status(env) == ("ok", "")


# ------------------------------------------------------------------ offline: DDL gate (always runs)


@pytest.fixture
def empty_archive():
    d = SQLiteDatabase()
    d.role = "archive"
    yield d
    d.close()


def test_ddl_is_refused_without_the_exact_approval_string(empty_archive):
    for env in ({}, {gate.DDL_OPT_IN_VAR: "yes"}, {gate.DDL_OPT_IN_VAR: "YES-EXECUTE-ARCHIVE-MIGRATION-DDL"}):
        with pytest.raises(gate.ArchiveDDLRefused):
            gate.apply(empty_archive, dry_run=False, env=env)
    assert empty_archive.execute("SELECT name FROM sqlite_master WHERE type='table'") == []


def test_ddl_runs_only_with_the_exact_approval_string(empty_archive):
    out = gate.apply(empty_archive, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    assert out["mode"] == "applied" and len(out["log"]) == 2
    assert gate.probe(empty_archive)["expected_schema_present"] is True


def test_dry_run_changes_nothing_and_reports_checksums(empty_archive):
    out = gate.apply(empty_archive, dry_run=True)
    assert out["mode"] == "dry_run" and len(out["pending"]) == 2
    assert all(len(c) == 64 for c in out["checksums"].values())
    assert empty_archive.execute("SELECT name FROM sqlite_master WHERE type='table'") == []


def test_preflight_refuses_operational_tables():
    d = SQLiteDatabase()
    try:
        raw_migrate(d)  # operational schema
        d.role = "archive"
        with pytest.raises(Exception, match="operational tables"):
            gate.apply(d, dry_run=True)
        with pytest.raises(Exception, match="operational tables"):
            gate.apply(d, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    finally:
        d.close()


def test_preflight_refuses_unknown_tables(empty_archive):
    empty_archive.execute("CREATE TABLE someone_elses_table (x INTEGER)")
    with pytest.raises(Exception, match="unknown tables"):
        gate.apply(empty_archive, dry_run=True)


def test_probe_reads_schema_and_writes_nothing(empty_archive):
    gate.apply(empty_archive, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    before = gate.probe(empty_archive)
    after = gate.probe(empty_archive)
    assert before == after
    assert before["blob_columns"] == [] and before["missing_triggers"] == []
    assert before["row_counts"] == {
        "archive_reports": 0,
        "archive_financial_tuples": 0,
        "archive_disclosures": 0,
        "schema_migrations": 2,
    }


# ----------------------------------------- Turso integration (disposable target only)


@pytest.fixture
def turso_test_db(monkeypatch):
    env = dict(os.environ)
    status, reason = target_status(env)
    if status == "skip":
        pytest.skip(reason)
    if status == "fail":
        pytest.fail(reason)
    db = connect(env[TEST_URL_VAR], env[TEST_TOKEN_VAR])
    db.role = "archive"
    yield db
    db.close()


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def test_turso_apply_gate_then_schema_and_ledger(turso_test_db):
    gate.preflight(turso_test_db)
    out = gate.apply(turso_test_db, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    assert out["mode"] == "applied"
    p = gate.probe(turso_test_db)
    assert p["expected_schema_present"] and p["missing_triggers"] == [] and p["blob_columns"] == []
    assert [r["name"] for r in p["ledger"]] == ["financial_archive", "disclosures"]
    # a second application is a no-op: migrations are not applied twice
    assert (
        gate.apply(turso_test_db, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})["log"]
        == []
    )


def test_turso_append_only_triggers(turso_test_db):
    gate.apply(turso_test_db, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    h = _sha("trigger-probe")
    turso_test_db.batch(
        [
            (
                "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, "
                "scope, currency, unit_scale, audit_status, reconciliation, archived_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h,
                    f"{h}.json",
                    "co-test",
                    "annual",
                    "2025-06-30",
                    "unconsolidated",
                    "PKR",
                    1000,
                    "audited",
                    "reconciled",
                    "2026-11-10T00:00:00Z",
                ),
            )
        ],
        transactional=True,
    )
    with pytest.raises(Exception, match="append-only|immutable"):
        turso_test_db.batch([("DELETE FROM archive_reports WHERE report_sha256 = ?", (h,))], rollback=True)
    with pytest.raises(Exception, match="immutable"):
        turso_test_db.batch(
            [("UPDATE archive_reports SET currency = 'USD' WHERE report_sha256 = ?", (h,))], rollback=True
        )


@pytest.mark.parametrize(
    "sql,args",
    [
        (
            "INSERT INTO archive_disclosures VALUES (?,?,?,?,?,?,?,?)",
            ("a" * 64, "co", "material_disclosure", "2025-01-01", "t", "not json", None, "2025-01-01"),
        ),
        (
            "INSERT INTO archive_disclosures VALUES (?,?,?,?,?,?,?,?)",
            (
                "b" * 64,
                "co",
                "material_disclosure",
                "2025-01-01",
                "t",
                "{" + "x" * 70000 + "}",
                None,
                "2025-01-01",
            ),
        ),
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
            "currency, "
            "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "short",
                "x.json",
                "co",
                "annual",
                "2025-06-30",
                "unconsolidated",
                "PKR",
                1000,
                "audited",
                "reconciled",
                "2026-11-10T00:00:00Z",
            ),
        ),
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
            "currency, "
            "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "c" * 64,
                "x.json",
                "co",
                "annual",
                "30/06/2025",
                "unconsolidated",
                "PKR",
                1000,
                "audited",
                "reconciled",
                "2026-11-10T00:00:00Z",
            ),
        ),
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
            "currency, "
            "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "d" * 64,
                "x.json",
                "co",
                "annual",
                "2025-06-30",
                "unconsolidated",
                "PKR",
                1000,
                "audited",
                "unreconciled",
                "2026-11-10T00:00:00Z",
            ),
        ),
    ],
)
def test_turso_check_constraints_refuse_bad_rows(turso_test_db, sql, args):
    gate.apply(turso_test_db, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    with pytest.raises(Exception, match="CHECK|constraint"):
        turso_test_db.batch([(sql, args)], rollback=True)


def test_turso_tuple_insert_is_idempotent(turso_test_db):
    gate.apply(turso_test_db, dry_run=False, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    h = _sha("idempotent-probe")
    report = (
        "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope, "
        "currency, unit_scale, audit_status, reconciliation, archived_at_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(report_sha256) DO NOTHING",
        (
            h,
            f"{h}.json",
            "co-test",
            "annual",
            "2025-06-30",
            "unconsolidated",
            "PKR",
            1000,
            "audited",
            "reconciled",
            "2026-11-10T00:00:00Z",
        ),
    )
    tuple_sql = (
        "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, metric_name, "
        "value, unit, currency, basis, report_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        (
            "co-test",
            "2025-06-30",
            "FY",
            "unconsolidated",
            "revenue",
            1000000.0,
            "PKR",
            "PKR",
            "reported",
            h,
            "2026-11-10T00:00:00Z",
        ),
    )
    for _ in range(2):
        turso_test_db.batch([report, tuple_sql], transactional=True)
    n = turso_test_db.execute(
        "SELECT COUNT(*) AS n FROM archive_financial_tuples WHERE report_sha256 = ?", (h,)
    )[0]["n"]
    assert n == 1
