"""Gate 3 (disposable Turso): migrations 0011-0014 and the M2-M9 engines over real libSQL HTTP.

Runs only against PSXNI_TURSO_DISPOSABLE_* (tests/turso_guard.py refuses production by host, marker and
token).
Run it after tests/test_turso_disposable.py in the same session; if the database is empty it migrates it.
The migration-failure test runs last: it records a throwaway version 15 from a temporary directory, so the
disposable database must be deleted afterwards (MASTER_SECURITY_AND_OPERATIONS.md section 4).
"""

from __future__ import annotations

import os
import shutil

import pytest

from database.connection import DatabaseError, TursoHTTPDatabase
from database.migrate import MIGRATIONS_DIR, MigrationError, discover, migrate
from tests.turso_guard import DISPOSABLE_TOKEN_VAR, DISPOSABLE_URL_VAR, disposable_config_status

URL = os.environ.get(DISPOSABLE_URL_VAR, "").strip()
TOKEN = os.environ.get(DISPOSABLE_TOKEN_VAR, "").strip()
_STATUS, _REASON = disposable_config_status(os.environ)
pytestmark = pytest.mark.skipif(_STATUS == "skip", reason=_REASON)
NOW = "2026-11-09T00:00:00Z"
NEW_TABLES = ("financial_reports", "financial_line_items", "account_mappings", "corporate_actions",
              "dimension_assessments", "valuations", "macro_series", "macro_observations", "validation_runs",
              "report_snapshots")


@pytest.fixture(scope="module")
def db():
    if _STATUS != "ok":
        pytest.fail(_REASON)
    d = TursoHTTPDatabase(URL, TOKEN, purpose="disposable")
    if not d.execute("SELECT COUNT(*) n FROM sqlite_master WHERE type='table'")[0]["n"]:
        migrate(d)
    from database.seed_loader import load
    if not d.execute("SELECT 1 FROM companies WHERE company_id = 'cmp-ogdc'"):
        load(d)
    return d


def test_migrations_tracked_in_order_and_rerun_is_noop(db):
    want = [m.version for m in discover()]
    got = [r["version"] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert got == want and want[-1] == 14
    assert all(line.startswith("skip") for line in migrate(db))


def test_schema_objects_present(db):
    objs = {(r["type"], r["name"]) for r in db.execute("SELECT type, name FROM sqlite_master")}
    for t in NEW_TABLES:
        assert ("table", t) in objs, t
    for trg in ("trg_fin_lines_no_delete", "trg_fin_lines_values_fixed", "trg_account_mappings_no_update",
                "trg_corp_actions_no_delete", "trg_dim_assess_no_update", "trg_valuations_no_update",
                "trg_macro_obs_immutable", "trg_macro_obs_no_delete", "trg_validation_runs_immutable",
                "trg_report_snapshots_immutable"):
        assert ("trigger", trg) in objs, trg
    for ix in ("ix_fin_reports_company", "ix_fin_lines_report", "ix_fin_lines_code", "ix_corp_actions",
               "ix_dim_assess", "ix_valuations", "ix_macro_obs", "ix_report_snapshots"):
        assert ("index", ix) in objs, ix
    cols = {r["name"] for r in db.execute("SELECT name FROM pragma_table_info('financial_metrics')")}
    assert {"report_id", "scope"} <= cols
    assert db.validate()["foreign_keys"] is True


def test_engines_end_to_end_over_http(db):
    from engines import financials as fin
    from engines import fundamentals as fu
    from engines import reports
    from engines import valuation as va
    from tests.test_m2_m3_financials import _corp

    fin.load_mappings(db)
    for rec in (_corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64), _corp()):
        r = fin.import_report(db, rec, importer="rehearsal", rights_attestation="synthetic test fixture")
        assert r["status"] in ("reconciled", "duplicate")
        fin.promote(db, r["report_id"])
    a = fu.analyse(db, "cmp-ogdc", period_end="2025-06-30", as_of="2026-11-09")
    assert a["ratios"]["roe_average_equity"]["state"] == "ok"
    fu.assess(db, "cmp-ogdc", period_end="2025-06-30", as_of_date="2026-11-09")
    va.value(db, "cmp-ogdc", as_of="2026-11-09")
    reports.snapshot(db, "cmp-ogdc", as_of="2026-11-09")
    assert reports.verify_snapshot(db, "cmp-ogdc", as_of="2026-11-09")["state"] == "reproduced"


def test_uniqueness_and_append_only_over_http(db):
    rid = db.execute("SELECT MIN(report_id) r FROM financial_reports")[0]["r"]
    line = db.execute("SELECT * FROM financial_line_items WHERE report_id = ? LIMIT 1", (rid,))[0]
    with pytest.raises(DatabaseError):  # duplicate line position
        db.execute("INSERT INTO financial_line_items(report_id, statement, line_no, raw_label, "
                   "column_period_end, "
                   "value, value_state, extraction_method) VALUES (?,?,?,?,?,1,'reported','manual')",
                   (rid, line["statement"], line["line_no"], "x", line["column_period_end"]))
    for sql in ("UPDATE financial_line_items SET value = 0", "DELETE FROM financial_line_items",
                "UPDATE account_mappings SET canonical_code = 'x'", "UPDATE dimension_assessments SET band "
                    "= 'x'",
                "UPDATE valuations SET state = 'ok'", "UPDATE report_snapshots SET body_json = '{}'"):
        with pytest.raises(DatabaseError):
            db.execute(sql)
    with pytest.raises(DatabaseError):  # value NULL must be not_reported, never a silent zero
        db.execute("INSERT INTO financial_line_items(report_id, statement, line_no, raw_label, "
                   "column_period_end, "
                   "value, value_state, extraction_method) VALUES "
                   "(?,'IS',999,'y','2025-06-30',NULL,'reported',"
                   "'manual')", (rid,))


def test_corporate_actions_macro_and_validation_over_http(db):
    sid = db.execute("SELECT MIN(source_item_id) s FROM source_items")[0]["s"]
    ca = ("INSERT INTO corporate_actions(company_id, action_type, ex_date, ratio, source_item_id, "
          "recorded_at_utc) VALUES ('cmp-ogdc','bonus','2026-01-15',0.25,?,?)")
    db.execute(ca, (sid, NOW))
    with pytest.raises(DatabaseError):
        db.execute(ca, (sid, NOW))  # duplicate
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM corporate_actions")
    with pytest.raises(DatabaseError):  # bonus without ratio
        db.execute("INSERT INTO corporate_actions(company_id, action_type, ex_date, source_item_id, "
                   "recorded_at_utc) VALUES ('cmp-ogdc','bonus','2026-02-01',?,?)", (sid, NOW))
    from engines import macro
    macro.load_registry(db)
    kw = {"importer": "rehearsal", "release_url": None, "rights_attestation": "synthetic"}
    first = [{"reference_period": "2026-06-10", "value": 11.0, "release_date": "2026-06-10"}]
    revised = [{"reference_period": "2026-06-10", "value": 10.5, "release_date": "2026-07-01"}]
    macro.import_observations(db, "sbp_policy_rate", first, release_title="a", **kw)
    r = macro.import_observations(db, "sbp_policy_rate", revised, release_title="b", **kw)
    assert r["added"] == [{"reference_period": "2026-06-10", "vintage": 2}]
    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO macro_observations(series_code, reference_period, value, release_date, "
                   "vintage, "
                   "source_item_id, recorded_at_utc) VALUES "
                   "('sbp_policy_rate','2026-06-10',1,'2026-08-01',2,?,?)",
                   (sid, NOW))  # duplicate vintage
    for sql in ("UPDATE macro_observations SET value = 0", "DELETE FROM macro_observations"):
        with pytest.raises(DatabaseError):
            db.execute(sql)
    from engines import backtest as bt
    rid = bt.record_validation_run(db, kind="labelled_accuracy", data_kind="human_labelled", result={"n": 3},
                                   engine_versions={})
    with pytest.raises(DatabaseError):
        db.execute("UPDATE validation_runs SET status = 'measured' WHERE run_id = ?", (rid,))


def test_invalid_foreign_key_rejected(db):
    sid = db.execute("SELECT MIN(source_item_id) s FROM source_items")[0]["s"]
    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO financial_reports(company_id, source_item_id, doc_type, period_end, "
                   "period_months, "
                   "scope, currency, unit_scale, audit_status, framework, extraction_method, created_at_utc) "
                   "VALUES "
                   "('cmp-nope',?,'annual','2025-06-30',12,'consolidated','PKR',1,'audited','corporate',"
                   "'manual',?)", (sid, NOW))


def test_transaction_failure_rolls_back(db):
    before = db.execute("SELECT COUNT(*) n FROM macro_series")[0]["n"]
    with pytest.raises(DatabaseError):
        db.batch([("INSERT INTO macro_series(series_code, name, unit, frequency, source_id, definition, "
                   "access_state, created_at_utc) VALUES ('rollback_probe','p','x','daily','sbp','d',"
                   "'manual_import',?)", (NOW,)),
                  ("INSERT INTO macro_series(series_code) VALUES ('rollback_probe')", ())])
    assert db.execute("SELECT COUNT(*) n FROM macro_series")[0]["n"] == before


def test_production_configuration_refused():
    prod = {DISPOSABLE_URL_VAR: "libsql://psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io",
            DISPOSABLE_TOKEN_VAR: "x"}
    assert disposable_config_status(prod)[0] == "fail"
    assert disposable_config_status({DISPOSABLE_URL_VAR: URL})[0] == "fail"  # incomplete


def test_zz_failed_migration_rolls_back_and_retries(db, tmp_path):
    """Last: a failing migration leaves nothing behind; a corrected retry then applies cleanly."""
    for p in MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(p, tmp_path / p.name)
    bad = tmp_path / "0015_rehearsal_probe.sql"
    bad.write_text("CREATE TABLE rehearsal_probe (x INTEGER);\nINSERT INTO no_such_table VALUES (1);\n")
    with pytest.raises((DatabaseError, MigrationError)):
        migrate(db, directory=tmp_path)
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'rehearsal_probe'")
    assert not db.execute("SELECT 1 FROM schema_migrations WHERE version = 15")
    bad.write_text("CREATE TABLE rehearsal_probe (x INTEGER);\n")
    assert migrate(db, directory=tmp_path)[-1].startswith("apply  0015")
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name = 'rehearsal_probe'")
    # clean up the probe so the database again matches the repository's migrations 1-14 exactly
    db.execute("DROP TABLE rehearsal_probe")
    db.execute("DELETE FROM schema_migrations WHERE version = 15")


def test_point_in_time_filing_gate_over_http(db):
    """The filing-date SQL added in PR #41 runs on real libSQL: strict vs lenient, restatement visibility,
    unknown dates and the prior-period query. Uses its own company so it does not disturb the others."""
    from engines import financials as fin
    from engines import fundamentals as fu
    from tests.test_m2_m3_financials import _corp, _imp

    # idempotent re-run: each row is checked on its own, so a partial earlier run is completed
    if not db.execute("SELECT 1 FROM companies WHERE company_id = 'cmp-pit-syn'"):
        db.execute("INSERT INTO companies(company_id, legal_name, listing_status, created_at_utc, "
                   "updated_at_utc) VALUES ('cmp-pit-syn','PIT Synthetic Ltd','listed',?,?)", (NOW, NOW))
    if not db.execute("SELECT 1 FROM company_identifiers WHERE company_id = 'cmp-pit-syn' AND "
                      "id_type = 'psx_ticker' AND value = 'PITSYN'"):
        db.execute("INSERT INTO company_identifiers(company_id, id_type, value, valid_from, valid_to, "
                   "verified_at_utc) VALUES ('cmp-pit-syn','psx_ticker','PITSYN',NULL,NULL,?)", (NOW,))
    fin.load_mappings(db)
    rec = _corp(period="2024-06-30", prev="2023-06-30", sha="9" * 64, filed_at_utc="2025-09-30T00:00:00Z")
    rec["company_ticker"] = "PITSYN"
    fin.promote(db, _imp(db, rec)["report_id"])
    rec2 = _corp(filed_at_utc="2026-09-30T00:00:00Z", sha="8" * 64)
    rec2["company_ticker"] = "PITSYN"
    fin.promote(db, _imp(db, rec2)["report_id"])
    unknown = _corp(filed_at_utc=None, sha="7" * 64)
    unknown["company_ticker"] = "PITSYN"
    fin.promote(db, _imp(db, unknown)["report_id"])
    before = fu.analyse(db, "cmp-pit-syn", period_end="2025-06-30", as_of="2026-06-30")
    assert before["state"] == "insufficient_data"  # FY2025 filed 2026-09-30, not yet known on 2026-06-30
    mid = fu.analyse(db, "cmp-pit-syn", period_end="2025-06-30", as_of="2026-10-01")
    assert mid["prior_period_end"] == "2024-06-30" and mid["growth"]["revenue"]["state"] == "ok"
    lenient = fu.analyse(db, "cmp-pit-syn", period_end="2025-06-30", as_of="2026-10-01", strict=False)
    assert lenient["state"] == "ok_with_unknown_filing_dates" and lenient["filing_dates_unknown"]
    scope_rows = db.execute("SELECT COUNT(*) n FROM financial_reports WHERE company_id = 'cmp-pit-syn' AND "
                            "filed_at_utc IS NULL")
    assert scope_rows[0]["n"] == 1  # the unknown-date report is kept in the database, never silently deleted
