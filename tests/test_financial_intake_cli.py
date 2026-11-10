"""Real-report intake CLI on SYNTHETIC reports with invented figures. No network; local SQLite only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.archive_migrations import archive_gate as gate
from database.connection import SQLiteDatabase
from scripts import financial_intake as fi
from tests.pdf_fixture_builder import write_pdf
from tests.test_statement_pipeline import _report_pages

REPO = Path(__file__).resolve().parents[1]


def _report(tmp_path, name, **kw):
    return write_pdf(tmp_path / name, _report_pages(**kw))


def _run(argv, capsys):
    code = fi.main(argv)
    return code, json.loads(capsys.readouterr().out)


def _base(pdf, extra=()):
    return [
        "--file",
        str(pdf),
        "--symbol",
        "ogdc",
        "--period-end",
        "2025-06-30",
        "--columns",
        "2025-06-30,2024-06-30",
        "--unit-scale",
        "1000",
        "--consolidation",
        "unconsolidated",
        *extra,
    ]


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("PSXNI_DOCUMENT_VAULT", str(vault))
    monkeypatch.delenv("PSXNI_ARCHIVE_TURSO_URL", raising=False)
    monkeypatch.delenv("PSXNI_ARCHIVE_TURSO_AUTH_TOKEN", raising=False)
    return vault


def test_refuses_without_a_vault_setting(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PSXNI_DOCUMENT_VAULT", raising=False)
    code, out = _run(_base(_report(tmp_path, "r.pdf")), capsys)
    assert code == 2 and out["status"] == "refused" and "PSXNI_DOCUMENT_VAULT" in out["detail"]


def test_refuses_a_vault_inside_the_repository(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PSXNI_DOCUMENT_VAULT", str(REPO / "data" / "vault"))
    code, out = _run(_base(_report(tmp_path, "r.pdf")), capsys)
    assert code == 2 and out["status"] == "refused"
    assert not (REPO / "data" / "vault").exists()


def test_default_run_places_the_pdf_in_the_vault_and_analyses_it(tmp_path, vault_env, capsys):
    pdf = _report(tmp_path, "r.pdf")
    code, out = _run(_base(pdf), capsys)
    assert code == 0 and out["vault"]["status"] == "stored"
    assert (vault_env / out["vault"]["vault_ref"]).is_file()
    assert out["reconciliation"]["overall"] == "RECONCILED"
    assert out["lines"]["statement"] > 0
    # the shared fixture's wording is not the explicit unqualified phrase, so no opinion is assumed
    assert out["auditor"]["opinion"] == "not_found"
    assert "archive" not in out  # no database was written


def test_the_same_file_again_is_a_duplicate_not_a_second_copy(tmp_path, vault_env, capsys):
    pdf = _report(tmp_path, "r.pdf")
    _run(_base(pdf), capsys)
    code, out = _run(_base(pdf), capsys)
    assert code == 0 and out["vault"]["status"] == "duplicate"
    assert len(list(vault_env.glob("*.pdf"))) == 1


def test_prior_filing_comparison_is_reported_and_nothing_is_overwritten(tmp_path, vault_env, capsys):
    cur = _report(tmp_path, "fy25.pdf", revenue=("1,000", "750"))
    prior = _report(tmp_path, "fy24.pdf", revenue=("800", "700"))
    code, out = _run(
        _base(
            cur,
            [
                "--prior-file",
                str(prior),
                "--prior-period",
                "2024-06-30",
                "--prior-columns",
                "2024-06-30,2023-06-30",
                "--prior-unit-scale",
                "1000",
            ],
        ),
        capsys,
    )
    assert code == 0 and out["prior_filing"]["period"] == "2024-06-30"
    rev = next(c for c in out["reconciliation"]["checks"] if c["check"] == "comparative:revenue")
    assert rev["status"] == "UNRECONCILED" and rev["discrepancy"] == -50.0
    assert len(list(vault_env.glob("*.pdf"))) == 2  # both filings kept, neither replaced


def test_prior_file_without_its_settings_is_refused(tmp_path, vault_env, capsys):
    code, out = _run(
        _base(_report(tmp_path, "r.pdf"), ["--prior-file", str(_report(tmp_path, "p.pdf"))]), capsys
    )
    assert code == 2 and out["status"] == "refused"


def test_archive_write_refuses_an_unmigrated_archive_and_writes_nothing(
    tmp_path, vault_env, monkeypatch, capsys
):
    db_path = tmp_path / "empty-archive.db"
    monkeypatch.setenv("PSXNI_ARCHIVE_TURSO_URL", f"sqlite://{db_path}")
    code, out = _run(_base(_report(tmp_path, "r.pdf"), ["--archive"]), capsys)
    assert code == 2 and out["status"] == "archive_refused"
    check = SQLiteDatabase(str(db_path))
    try:
        assert not check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archive_reports'"
        )
    finally:
        check.close()


def test_archive_write_stores_the_analysis_once_on_a_ready_archive(tmp_path, vault_env, monkeypatch, capsys):
    db_path = tmp_path / "ready-archive.db"
    setup = SQLiteDatabase(str(db_path))
    setup.role = "archive"
    gate.apply(setup, dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    setup.close()
    monkeypatch.setenv("PSXNI_ARCHIVE_TURSO_URL", f"sqlite://{db_path}")
    pdf = _report(tmp_path, "r.pdf")
    code, out = _run(_base(pdf, ["--archive", "--company-id", "co-cli"]), capsys)
    assert code == 0 and out["archive"]["status"] == "stored" and out["archive"]["run"] == "created"
    code2, out2 = _run(_base(pdf, ["--archive", "--company-id", "co-cli"]), capsys)
    assert code2 == 0 and out2["archive"]["lines"]["inserted"] == 0 and out2["archive"]["run"] == "existing"
    check = SQLiteDatabase(str(db_path))
    try:
        assert check.execute("SELECT COUNT(*) AS n FROM archive_document_registry")[0]["n"] == 1
    finally:
        check.close()


def test_the_diagnostic_summary_reports_mapping_reconciliation_auditor_and_kams(tmp_path, vault_env, capsys):
    pdf = _report(tmp_path, "diag.pdf")
    code, out = _run(_base(pdf), capsys)
    d = out["diagnostic"]
    assert code == 0
    assert d["statement_lines"]["mapped"] > 0
    assert (
        d["reconciliation"]["balance_sheet"] == "RECONCILED"
        and d["reconciliation"]["cash_flow"] == "RECONCILED"
    )
    assert d["auditor_opinion"] == "not_found"  # the fixture's wording does not carry the explicit phrase
    assert d["contingencies_recognised_on_balance_sheet"] is False


def test_the_text_summary_is_readable_and_mentions_each_section(tmp_path, vault_env, capsys):
    pdf = _report(tmp_path, "text.pdf")
    assert fi.main(_base(pdf) + ["--text"]) == 0
    text = capsys.readouterr().out
    for needle in (
        "Statement lines:",
        "Reconciliation:",
        "Auditor opinion:",
        "Receivables:",
        "Contingent items",
    ):
        assert needle in text
    assert not text.lstrip().startswith("{")  # not JSON
