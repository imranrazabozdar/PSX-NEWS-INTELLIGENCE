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
from database.connection import DatabaseError, SQLiteDatabase, connect, same_database
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
            gate.apply(empty_archive, dry_run=False, purpose=gate.PURPOSE, env=env)
    assert empty_archive.execute("SELECT name FROM sqlite_master WHERE type='table'") == []


def test_ddl_runs_only_with_the_exact_approval_string(empty_archive):
    out = gate.apply(
        empty_archive, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    assert out["mode"] == "applied" and len(out["log"]) == 5
    assert gate.probe(empty_archive)["fully_migrated"] is True


def test_dry_run_changes_nothing_and_reports_checksums(empty_archive):
    out = gate.apply(empty_archive, dry_run=True)
    assert out["mode"] == "dry_run" and len(out["pending"]) == 5
    assert all(len(m["checksum"]) == 64 for m in out["pending"])
    assert empty_archive.execute("SELECT name FROM sqlite_master WHERE type='table'") == []


def test_preflight_refuses_operational_tables():
    d = SQLiteDatabase()
    try:
        raw_migrate(d)  # operational schema
        d.role = "archive"
        with pytest.raises(Exception, match="operational tables"):
            gate.apply(d, dry_run=True)
        with pytest.raises(Exception, match="operational tables"):
            gate.apply(
                d, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
            )
    finally:
        d.close()


def test_preflight_refuses_unknown_tables(empty_archive):
    empty_archive.execute("CREATE TABLE someone_elses_table (x INTEGER)")
    with pytest.raises(Exception, match="unknown schema objects"):
        gate.apply(empty_archive, dry_run=True)


def test_probe_reads_schema_and_writes_nothing(empty_archive):
    gate.apply(
        empty_archive, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    before = gate.probe(empty_archive)
    after = gate.probe(empty_archive)
    assert before == after
    assert before["blob_columns"] == [] and before["structure_drift_for_ledger_state"] == {}
    assert before["fully_migrated"] is True and len(before["ledger"]) == 5
    assert set(before["row_counts"]) == {
        "archive_reports",
        "archive_financial_tuples",
        "archive_disclosures",
        "archive_document_registry",
        "archive_processing_events",
        "archive_line_items",
        "archive_notes",
        "archive_reconciliation",
        "archive_line_reviews",
        "archive_extraction_runs",
        "archive_line_items_v2",
        "archive_reconciliation_v2",
        "archive_document_files",
    } and all(v == 0 for v in before["row_counts"].values())


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
    out = gate.apply(
        turso_test_db, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    assert out["mode"] == "applied"
    p = gate.probe(turso_test_db)
    assert (
        p["fully_migrated"] is True
        and p["structure_drift_for_ledger_state"] == {}
        and p["blob_columns"] == []
    )
    assert [r["name"] for r in p["ledger"]] == [
        "financial_archive",
        "disclosures",
        "document_registry",
        "extraction_evidence",
        "extractor_versioning",
    ]
    # a second application is a no-op: migrations are not applied twice
    assert (
        gate.apply(
            turso_test_db,
            dry_run=False,
            purpose=gate.PURPOSE,
            env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE},
        )["log"]
        == []
    )


def test_turso_append_only_triggers(turso_test_db):
    gate.apply(
        turso_test_db, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    h = _sha("trigger-probe-" + _run_id())  # unique per run: the disposable database keeps rows between runs
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
    gate.apply(
        turso_test_db, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    with pytest.raises(Exception, match="CHECK|constraint"):
        turso_test_db.batch([(sql, args)], rollback=True)


def test_turso_tuple_insert_is_idempotent(turso_test_db):
    gate.apply(
        turso_test_db, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    h = _sha("idempotent-probe-" + _run_id())
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


# ============================================================================================================
# LIVE GROUPS (disposable archive-test database only). Each test needs the target guard to return "ok".
# They never run against the real archive or the operational database: the guard refuses those URLs first.
# ============================================================================================================

import uuid  # noqa: E402

from database import financial_repo as repo  # noqa: E402

ARCHIVE_OBJECT_NAMES = None  # filled from the reference schema on first use


def _expected_names() -> set[str]:
    ref = gate.reference_fingerprint(len(gate._migrations()))
    names = set(ref["tables"]) | set(ref["indexes"]) | set(ref["triggers"]) | {"schema_migrations"}
    return names


DROP_ORDER = [
    "archive_line_reviews",
    "archive_line_items",
    "archive_notes",
    "archive_reconciliation",
    "archive_processing_events",
    "archive_document_registry",
    "archive_financial_tuples",
    "archive_reports",
    "archive_disclosures",
    "schema_migrations",
]


def reset_disposable(db) -> dict:
    """TEST-ONLY. Empties the disposable archive-test database.

    Drops the archive's own objects so the migration sequence can run from zero. Refuses unless the guard
    passes and every object present is an archive object. Tables are dropped children first."""
    status, reason = target_status(dict(os.environ))
    if status != "ok":
        raise RuntimeError(f"reset refused: {reason}")
    present = db.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    unknown = sorted(r["name"] for r in present if r["name"] not in _expected_names())
    if unknown:
        raise RuntimeError(f"reset refused: unknown objects present {unknown}")
    drops = [
        (f"DROP TRIGGER IF EXISTS {r['name']}", ())  # noqa: S608 - names come from sqlite_master
        for r in present
        if r["type"] == "trigger"
    ]
    tables = [r["name"] for r in present if r["type"] == "table"]
    for name in DROP_ORDER:  # children before parents: no reliance on foreign key switches inside a batch
        if name in tables:
            drops.append((f"DROP TABLE IF EXISTS {name}", ()))  # noqa: S608 - a literal name from DROP_ORDER
    if drops:
        db.batch(drops, transactional=True)
    left = db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    return {"dropped": len(present), "left": [r["name"] for r in left]}


@pytest.fixture
def live(turso_test_db):
    """A migrated disposable database. Migration is applied only through the approved gate."""
    gate.apply(
        turso_test_db, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    return turso_test_db


@pytest.fixture
def zero(turso_test_db):
    """An empty disposable database, for the full migration sequence and the partial-DDL tests."""
    reset_disposable(turso_test_db)
    yield turso_test_db


def _run_id() -> str:
    return uuid.uuid4().hex[:12]


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _objects(db) -> list[tuple]:
    return sorted(
        tuple(r)
        for r in db.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    )


def _count(db, table) -> int:
    assert table.replace("_", "").isalnum()  # test-only helper; table names are literals
    return db.execute(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]  # noqa: S608


# ------------------------------------------------------------------ 1. full migration sequence, live


def test_live_full_migration_sequence_from_zero(zero):
    before = reset_disposable(zero)
    assert before["left"] == []
    out = gate.apply(
        zero, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    assert out["mode"] == "applied" and len(out["log"]) == 5
    p = gate.probe(zero)
    assert p["fully_migrated"] is True
    assert [r["name"] for r in p["ledger"]] == [
        "financial_archive",
        "disclosures",
        "document_registry",
        "extraction_evidence",
        "extractor_versioning",
    ]
    assert len(p["triggers"]) == 26 and len(p["tables"]) == 13
    assert p["structure_drift_for_ledger_state"] == {} and p["blob_columns"] == []
    again = gate.apply(
        zero, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
    )
    assert again["log"] == []  # re-running the sequence changes nothing


# ------------------------------------------------------------------ 2. foreign-key enforcement, live


def test_live_foreign_keys_are_on_for_the_connection(live):
    assert live.execute("PRAGMA foreign_keys")[0]["foreign_keys"] == 1
    assert live.execute("PRAGMA foreign_keys")[0]["foreign_keys"] == 1  # still on in a later call


ORPHAN_LINE = (
    "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, "
    "column_period_end, is_comparative, value, value_state, currency, unit_scale, consolidation, "
    "extraction_method) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    (
        "f" * 64,
        "BS",
        1,
        "Total assets",
        "2025-06-30",
        0,
        1.0,
        "reported",
        "PKR",
        1000,
        "unconsolidated",
        "pdf_text",
    ),
)


@pytest.mark.parametrize("pragma", [False, True])
def test_live_orphan_line_item_is_refused(live, pragma):
    stmts = ([("PRAGMA foreign_keys = ON", ())] if pragma else []) + [ORPHAN_LINE]
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        live.batch(stmts, rollback=True)  # rollback: even a wrongly accepted row could not persist


def test_live_orphan_child_rows_are_refused_in_every_evidence_table(live):
    orphan_sha = "a" * 64
    cases = {
        "archive_processing_events": (
            "INSERT INTO archive_processing_events(report_sha256, status, detail, "
            "recorded_at_utc) VALUES (?,?,?,?)",
            (orphan_sha, "registered", "x", "t"),
        ),
        "archive_notes": (
            "INSERT INTO archive_notes(report_sha256, note_no, note_title, body_json, "
            "extraction_method) VALUES (?,?,?,?,?)",
            (orphan_sha, "1", "t", "{}", "pdf_text"),
        ),
        "archive_reconciliation": (
            "INSERT INTO archive_reconciliation(report_sha256, check_name, "
            "column_period_end, consolidation, tolerance, result, recorded_at_utc) "
            "VALUES (?,?,?,?,?,?,?)",
            (orphan_sha, "balance_sheet", "2025-06-30", "unconsolidated", 2.0, "pass", "t"),
        ),
        "archive_line_reviews": (
            "INSERT INTO archive_line_reviews(line_id, decision, reviewer, note, "
            "reviewed_at_utc) VALUES (?,?,?,?,?)",
            (999999, "accepted", "owner", "n", "t"),
        ),
    }
    for sql, args in cases.values():
        with pytest.raises(DatabaseError, match="FOREIGN KEY"):
            live.batch([(sql, args)], rollback=True)


def test_live_valid_chain_is_accepted_and_the_rollback_leaves_nothing(live):
    """Parent then child in one rolled-back batch: accepted in the batch, and nothing persists afterwards."""
    sha = _sha("fk-valid-chain-" + _run_id())
    before = _count(live, "archive_line_items")
    registry = (
        "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id, doc_type,"
        "financial_year, "
        "period_end, consolidation, audit_status, original_filename, vault_ref, source_id, retrieved_at_utc, "
        "document_version, registered_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sha,
            "OGDC",
            "co-fk",
            "annual",
            2025,
            "2025-06-30",
            "unconsolidated",
            "audited",
            "f.pdf",
            f"{sha}.pdf",
            "company_reports_manual",
            "t",
            1,
            "t",
        ),
    )
    line = (
        "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, column_period_end, "
        "is_comparative, value, value_state, currency, unit_scale, consolidation, extraction_method) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            sha,
            "BS",
            1,
            "Total assets",
            "2025-06-30",
            0,
            1.0,
            "reported",
            "PKR",
            1000,
            "unconsolidated",
            "pdf_text",
        ),
    )
    live.batch([registry, line], rollback=True)  # accepted inside the batch
    assert _count(live, "archive_line_items") == before  # the rollback removed it


def test_live_foreign_key_violation_in_a_separate_call_is_refused(live):
    with pytest.raises(DatabaseError, match="FOREIGN KEY"):
        live.execute(ORPHAN_LINE[0], ORPHAN_LINE[1])


# ----------------------------------- 3. interrupted migration and partial DDL, live


def test_live_failed_transactional_batch_leaves_no_partial_objects(live):
    run = _run_id()
    a, b = f"tmp_{run}_a", f"tmp_{run}_b"
    before = _objects(live)
    with pytest.raises(DatabaseError):
        live.batch(
            [
                (f"CREATE TABLE {a} (x INTEGER)", ()),  # noqa: S608 - names are literals in this test file or from sqlite_master
                (f"CREATE TABLE {b} (y INTEGER)", ()),  # noqa: S608 - names are literals in this test file or from sqlite_master
                (f"INSERT INTO missing_{run} (z) VALUES (1)", ()),  # noqa: S608 - a literal name; fails here
            ],
            transactional=True,
        )
    assert _objects(live) == before, "a failed batch must leave no partial objects behind"


def test_live_duplicate_object_in_the_middle_rolls_back_the_earlier_statements(live):
    run = _run_id()
    t = f"tmp_{run}"
    before = _objects(live)
    with pytest.raises(DatabaseError):
        live.batch(
            [(f"CREATE TABLE {t} (x INTEGER)", ()), (f"CREATE TABLE {t} (x INTEGER)", ())],
            transactional=True,  # noqa: S608 - names are literals in this test file or from sqlite_master
        )  # second one fails
    assert _objects(live) == before


def test_live_interrupted_migration_leaves_ledger_and_schema_unchanged(live):
    """A migration whose statements succeed, then fail, must not record a ledger row or keep its objects."""
    run = _run_id()
    before_probe = gate.probe(live)
    fake_version = 5
    stmts = [
        (f"CREATE TABLE fake_mig_{run} (id INTEGER PRIMARY KEY, note TEXT)", ()),  # noqa: S608 - names are literals in this test file or from sqlite_master
        (f"CREATE INDEX ix_fake_{run} ON fake_mig_{run}(note)", ()),  # noqa: S608 - names are literals in this test file or from sqlite_master
        (f"INSERT INTO fake_mig_{run} (id, note, missing_column) VALUES (1, 'x', 2)", ()),  # noqa: S608
        (
            "INSERT INTO schema_migrations(version, name, checksum, applied_at_utc, result) "
            "VALUES (?,?,?,?,'applied')",
            (fake_version, "fake", "0" * 64, "t"),
        ),
    ]
    with pytest.raises(DatabaseError):
        live.batch(stmts, transactional=True)
    after_probe = gate.probe(live)
    assert after_probe["ledger"] == before_probe["ledger"], "ledger must not record an interrupted migration"
    assert (
        after_probe["tables"] == before_probe["tables"] and after_probe["indexes"] == before_probe["indexes"]
    )
    assert after_probe["row_counts"] == before_probe["row_counts"]
    assert after_probe["fully_migrated"] is True


def test_live_sequence_is_not_partially_applied_on_refusal(zero):
    """Approval refused: nothing changes on the live database at all."""
    before = _objects(zero)
    with pytest.raises(gate.ArchiveDDLRefused):
        gate.apply(zero, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: "yes"})
    assert _objects(zero) == before


# ------------------------------------------------------------------ 4. recovery detection, live


def test_live_partial_state_is_detected_refused_and_restorable(live):
    row = live.execute(
        "SELECT version, name, checksum, applied_at_utc, result FROM schema_migrations WHERE version = 4"
    )[0]
    objects_before = _objects(live)
    live.execute(
        "DELETE FROM schema_migrations WHERE version = 4"
    )  # objects of 4 exist, its ledger row does not
    try:
        p = gate.probe(live)
        assert p["fully_migrated"] is False
        assert p["structure_drift_for_ledger_state"], (
            "extra objects of an unrecorded migration must be reported"
        )
        with pytest.raises(gate.SchemaDrift, match="pre-state drift"):
            gate.apply(
                live, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE}
            )
        with pytest.raises(repo.ArchiveNotReady):
            repo.require_archive_ready(live)
        assert _objects(live) == objects_before, "detection must not change the schema"
    finally:
        live.batch(
            [
                (
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at_utc, result) "
                    "VALUES (?,?,?,?,?)",
                    (row["version"], row["name"], row["checksum"], row["applied_at_utc"], row["result"]),
                )
            ],
            transactional=True,
        )
    assert gate.probe(live)["fully_migrated"] is True


def test_live_tampered_ledger_checksum_is_refused_and_restorable(live):
    row = live.execute("SELECT checksum FROM schema_migrations WHERE version = 2")[0]
    live.execute("UPDATE schema_migrations SET checksum = ? WHERE version = 2", ("0" * 64,))
    try:
        assert gate.probe(live)["ledger_checksums_match_repository"] is False
        with pytest.raises(repo.ArchiveNotReady, match="checksums"):
            repo.require_archive_ready(live)
    finally:
        live.execute("UPDATE schema_migrations SET checksum = ? WHERE version = 2", (row["checksum"],))
    assert gate.probe(live)["ledger_checksums_match_repository"] is True


# ------------------------------------------------------------------ 5. append-only triggers and checks, live

EVIDENCE_TABLES = [
    "archive_reports",
    "archive_financial_tuples",
    "archive_disclosures",
    "archive_document_registry",
    "archive_processing_events",
    "archive_line_items",
    "archive_notes",
    "archive_reconciliation",
    "archive_line_reviews",
]


def _seed(sha: str) -> list[tuple]:
    """Valid rows for every evidence table, one synthetic document.
    Used inside rolled-back batches."""
    ts = "2026-11-10T00:00:00Z"
    return [
        (
            "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id, doc_type,"
            "financial_year, "
            "period_end, consolidation, audit_status, original_filename, vault_ref, source_id,"
            "retrieved_at_utc, "
            "document_version, registered_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sha,
                "OGDC",
                "co-seed",
                "annual",
                2025,
                "2025-06-30",
                "unconsolidated",
                "audited",
                "s.pdf",
                f"{sha}.pdf",
                "company_reports_manual",
                ts,
                1,
                ts,
            ),
        ),
        (
            "INSERT INTO archive_processing_events(report_sha256, status, detail, recorded_at_utc) "
            "VALUES (?,?,?,?)",
            (sha, "registered", "seed", ts),
        ),
        (
            "INSERT INTO archive_reports(report_sha256, vault_ref, company_id, doc_type, period_end, scope,"
            "currency, "
            "unit_scale, audit_status, reconciliation, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                sha,
                f"{sha}.json",
                "co-seed",
                "annual",
                "2025-06-30",
                "unconsolidated",
                "PKR",
                1000,
                "audited",
                "reconciled",
                ts,
            ),
        ),
        (
            "INSERT INTO archive_financial_tuples(company_id, period_end_date, period_type, scope, "
            "metric_name,"
            ""
            "value, unit, currency, basis, report_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "co-seed",
                "2025-06-30",
                "FY",
                "unconsolidated",
                "revenue",
                1.0,
                "PKR",
                "PKR",
                "reported",
                sha,
                ts,
            ),
        ),
        (
            "INSERT INTO archive_disclosures(disclosure_sha256, company_id, kind, published_at_utc, title, "
            "payload_json, pdf_sha256, archived_at_utc) VALUES (?,?,?,?,?,?,?,?)",
            (sha, "co-seed", "material_disclosure", ts, "t", "{}", None, ts),
        ),
        (
            "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, column_period_end, "
            "is_comparative, value, value_state, currency, unit_scale, consolidation, extraction_method) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sha,
                "BS",
                1,
                "Total assets",
                "2025-06-30",
                0,
                1.0,
                "reported",
                "PKR",
                1000,
                "unconsolidated",
                "pdf_text",
            ),
        ),
        (
            "INSERT INTO archive_line_reviews(line_id, decision, reviewer, note, reviewed_at_utc) "
            "VALUES ((SELECT line_id FROM archive_line_items WHERE report_sha256 = ?), ?,?,?,?)",
            (sha, "accepted", "owner", "seed", ts),
        ),
        (
            "INSERT INTO archive_notes(report_sha256, note_no, note_title, body_json, extraction_method) "
            "VALUES (?,?,?,?,?)",
            (sha, "1", "t", "{}", "pdf_text"),
        ),
        (
            "INSERT INTO archive_reconciliation(report_sha256, check_name, column_period_end, consolidation, "
            "tolerance, result, recorded_at_utc) VALUES (?,?,?,?,?,?,?)",
            (sha, "balance_sheet", "2025-06-30", "unconsolidated", 2.0, "pass", ts),
        ),
    ]


@pytest.mark.parametrize("table", EVIDENCE_TABLES)
def test_live_append_only_refuses_update_and_delete(live, table):
    """Rows are seeded inside the same batch so the triggers really fire. The batch always rolls back."""
    sha = _sha("append-only-" + table + "-" + _run_id())
    seed = _seed(sha)
    for attack in (f"DELETE FROM {table}", f"UPDATE {table} SET rowid = rowid"):  # noqa: S608 - literal names
        with pytest.raises(DatabaseError, match="append-only|immutable"):
            live.batch(seed + [(attack, ())], rollback=True)


def test_live_idempotent_registration_lines_and_reconciliation(live):
    run = _run_id()
    sha = _sha("idem-" + run)
    meta = {
        "report_sha256": sha,
        "psx_symbol": "OGDC",
        "company_id": "co-idem-" + run,
        "doc_type": "annual",
        "financial_year": 2025,
        "period_end": "2025-06-30",
        "consolidation": "unconsolidated",
        "audit_status": "audited",
        "original_filename": "idem.pdf",
        "vault_ref": f"{sha}.pdf",
        "source_id": "company_reports_manual",
        "retrieved_at_utc": "2026-11-10T00:00:00Z",
    }
    assert repo.register_document(live, meta)["status"] == "registered"
    assert repo.register_document(live, meta)["status"] == "duplicate"
    lines = [
        {
            "statement": "BS",
            "line_no": 1,
            "raw_label": "Total assets",
            "column_period_end": "2025-06-30",
            "value": 500.0,
            "extraction_method": "pdf_text",
            "page": 2,
            "canonical_code": "total_assets",
        },
        {
            "statement": "BS",
            "line_no": 2,
            "raw_label": "Total liabilities",
            "column_period_end": "2025-06-30",
            "value": None,
            "value_state": "not_reported",
            "extraction_method": "pdf_text",
            "page": 2,
        },
    ]
    first = repo.store_line_items(
        live, sha, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    again = repo.store_line_items(
        live, sha, lines, consolidation="unconsolidated", currency="PKR", unit_scale=1000
    )
    assert first == {"inserted": 2, "already_present": 0} and again == {"inserted": 0, "already_present": 2}
    assert (
        live.execute("SELECT value FROM archive_line_items WHERE report_sha256 = ? AND line_no = 2", (sha,))[
            0
        ]["value"]
        is None
    )  # not reported is NULL on the live database, never zero
    checks = [{"check": "balance_sheet", "result": "pass", "reported": 500.0, "expected": 500.0}]
    repo.store_reconciliation(
        live, sha, checks, consolidation="unconsolidated", column_period_end="2025-06-30", tolerance=2.0
    )
    n = _count(live, "archive_reconciliation")
    repo.store_reconciliation(
        live, sha, checks, consolidation="unconsolidated", column_period_end="2025-06-30", tolerance=2.0
    )
    assert _count(live, "archive_reconciliation") == n


@pytest.mark.parametrize(
    "sql,args",
    [
        (
            "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, column_period_end, "
            "is_comparative, value, value_state, currency, unit_scale, consolidation, extraction_method) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _sha("c1"),
                "BS",
                1,
                "x",
                "2025-06-30",
                0,
                0.0,
                "not_reported",
                "PKR",
                1000,
                "unconsolidated",
                "pdf_text",
            ),
        ),
        (
            "INSERT INTO archive_line_items(report_sha256, statement, line_no, raw_label, column_period_end, "
            "is_comparative, value, value_state, currency, unit_scale, consolidation, extraction_method) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _sha("c2"),
                "XX",
                1,
                "x",
                "2025-06-30",
                0,
                1.0,
                "reported",
                "PKR",
                1000,
                "unconsolidated",
                "pdf_text",
            ),
        ),
        (
            "INSERT INTO archive_document_registry(report_sha256, psx_symbol, company_id, doc_type,"
            "financial_year, "
            "period_end, consolidation, audit_status, original_filename, vault_ref, source_id,"
            "retrieved_at_utc, "
            "document_version, registered_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _sha("c3"),
                "OGDC",
                "co",
                "annual",
                2025,
                "2025-06-30",
                "unconsolidated",
                "audited",
                "../x.pdf",
                "v.pdf",
                "s",
                "t",
                1,
                "t",
            ),
        ),
        (
            "INSERT INTO archive_notes(report_sha256, note_no, note_title, body_json, extraction_method) "
            "VALUES (?,?,?,?,?)",
            (_sha("c4"), "1", "t", "not json", "pdf_text"),
        ),
        (
            "INSERT INTO archive_line_reviews(line_id, decision, corrected_value, reviewer, note,"
            "reviewed_at_utc) "
            "VALUES (?,?,?,?,?,?)",
            (1, "corrected", None, "owner", "n", "t"),
        ),
    ],
)
def test_live_check_constraints_refuse_bad_rows(live, sql, args):
    with pytest.raises(DatabaseError, match="CHECK|FOREIGN KEY|constraint"):
        live.batch([(sql, args)], rollback=True)
