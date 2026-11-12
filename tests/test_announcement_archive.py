"""Announcement routing, historical non-PDF loader, and the unified history entry point.

Every figure is a SYNTHETIC hand-built summary. No record is fetched from any portal; the routing tests pass
records directly, as an owner-supplied permitted feed would. Two SQLite files stand in for the two Turso
databases. No network access, no production credentials.
"""

from __future__ import annotations

import json

import pytest

from database import financial_repo as repo
from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load
from engines import announcement_routing as ar
from engines import financials as fin
from engines import history as hist
from scripts.load_historical_statements import load_directory

SRC = "company_reports_manual"
PERMITTED = frozenset({SRC})


def _summary(period="2025-06-30", provenance="owner_supplied", **over):
    metrics = {"revenue": 1000.0, "cost_of_sales": -600.0, "gross_profit": 400.0,
               "total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 200.0}
    if period == "2024-06-30":
        metrics = {"revenue": 800.0, "cost_of_sales": -500.0, "gross_profit": 300.0,
                   "total_assets": 450.0, "total_liabilities": 250.0, "total_equity": 200.0}
    s = {"ticker": "OGDC", "period_end": period, "doc_type": "annual", "scope": "unconsolidated",
         "currency": "PKR", "unit_scale": 1000, "audit_status": "audited", "provenance": provenance,
         "source_note": "owner-supplied summary (test)", "metrics": metrics}
    s.update(over)
    return s


@pytest.fixture
def main():
    d = SQLiteDatabase()
    migrate(d)
    load(d)
    fin.load_mappings(d)
    d.role = "main"
    # the seed already holds rows: count only what a test adds
    d.base_source_items = _count(d, "source_items")
    yield d
    d.close()


@pytest.fixture
def archive():
    d = SQLiteDatabase()
    from database.archive_migrations import archive_gate as gate

    gate.apply(_as(d), dry_run=False, purpose=gate.PURPOSE, env={gate.DDL_OPT_IN_VAR: gate.DDL_OPT_IN_VALUE})
    yield d
    d.close()


def _as(db):
    db.role = "archive"
    return db


def _ann(**over):
    a = {"source_id": SRC, "external_id": "ann-1", "ticker": "OGDC", "title": "Annual report 2025",
         "published_at_utc": "2025-09-30T00:00:00Z", "url": "https://example.invalid/ann-1",
         "parsed": {"summary": _summary()}}
    a.update(over)
    return a


def _count(db, table):
    assert table.isidentifier()  # test-only helper; table names are literals below
    return db.execute(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]  # noqa: S608


def _added_items(main):
    return _count(main, "source_items") - main.base_source_items


# ------------------------------------------------------------------ routing: fail closed

def test_no_permitted_source_routes_nothing(main, archive):
    r = ar.route(_ann(), main_db=main, archive_db=archive, permitted_sources=frozenset())
    assert r["status"] == "refused" and _added_items(main) == 0 and _count(archive, "archive_reports") == 0


def test_unpermitted_source_is_refused(main, archive):
    r = ar.route(_ann(source_id="psx_announcements"), main_db=main, archive_db=archive,
                 permitted_sources=PERMITTED)
    assert r["status"] == "refused" and "not a permitted route" in r["reason"]
    assert _added_items(main) == 0


@pytest.mark.parametrize("key", ["pdf", "pdf_bytes", "content", "body", "file"])
def test_binary_or_body_content_is_refused(main, archive, key):
    r = ar.route(_ann(**{key: "x"}), main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r["status"] == "refused" and "not accepted" in r["reason"]
    assert _added_items(main) == 0 and _count(archive, "archive_disclosures") == 0


def test_pdf_reference_must_be_a_hash_not_a_path(main, archive):
    r = ar.route(_ann(pdf_sha256="data/vault/reports/ogdc.pdf"), main_db=main, archive_db=archive,
                 permitted_sources=PERMITTED)
    assert r["status"] == "refused" and "64-character" in r["reason"]


def test_missing_fields_are_refused(main, archive):
    r = ar.route(_ann(external_id=""), main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r["status"] == "refused" and "external_id" in r["reason"]


# ------------------------------------------------------------------ routing: destinations

def test_financial_statement_metadata_goes_to_main_and_structure_to_archive(main, archive):
    r = ar.route(_ann(), main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r["status"] == "routed" and r["kind"] == "financial_statement"
    assert r["main"]["outcome"] == "inserted"
    assert r["archive"]["status"] == "archived" and r["archive"]["archived"] == 6
    assert _added_items(main) == 1
    assert _count(archive, "archive_financial_tuples") == 6
    assert r["history"]["source"] == "archive" and \
        [p["period_end"] for p in r["history"]["periods"]] == ["2025-06-30"]


def test_unbalanced_summary_keeps_metadata_but_is_not_archived(main, archive):
    bad = _summary(metrics={"total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 150.0})
    r = ar.route(_ann(parsed={"summary": bad}), main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r["main"]["outcome"] == "inserted"
    assert r["archive"]["status"] == "refused"
    assert any("identity failed" in x for x in r["archive"]["refused"])
    assert _count(archive, "archive_financial_tuples") == 0 and _count(archive, "archive_reports") == 0


def test_material_disclosure_is_archived_as_bounded_json_with_a_pdf_hash_only(main, archive):
    sha = "c" * 64
    r = ar.route(_ann(title="Material information: board approved dividend", external_id="ann-2",
                      parsed={"fields": {"dividend_per_share": 2.5}}, pdf_sha256=sha),
                 main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r["kind"] == "material_disclosure" and r["archive"]["status"] == "archived"
    row = archive.execute("SELECT kind, payload_json, pdf_sha256 FROM archive_disclosures")[0]
    assert row["kind"] == "material_disclosure" and row["pdf_sha256"] == sha
    assert json.loads(row["payload_json"]) == {"fields": {"dividend_per_share": 2.5}}


def test_repeated_announcement_adds_no_duplicate_rows(main, archive):
    ann = _ann(title="Material information: right issue", external_id="ann-3", parsed={"fields": {}})
    ar.route(ann, main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    r2 = ar.route(ann, main_db=main, archive_db=archive, permitted_sources=PERMITTED)
    assert r2["main"]["outcome"] == "unchanged"
    assert _count(archive, "archive_disclosures") == 1 and _added_items(main) == 1


def test_ticker_outside_the_master_is_not_archived(main, archive):
    r = ar.route(_ann(ticker="ZZZZ", external_id="ann-4"), main_db=main, archive_db=archive,
                 permitted_sources=PERMITTED)
    assert r["archive"]["status"] == "skipped" and _count(archive, "archive_reports") == 0


def test_classification_uses_declared_kind_then_title():
    assert ar.classify("Annual report 2025") == "financial_statement"
    assert ar.classify("Notice of meeting of shareholders") == "material_disclosure"
    assert ar.classify("Share price update") == "other"
    assert ar.classify("Share price update", declared="material_disclosure") == "material_disclosure"


# ------------------------------------------------------------------ historical loader

def test_dry_run_writes_nothing_and_reports_what_would_be_archived(main, archive, tmp_path):
    (tmp_path / "ogdc_2025.json").write_text(json.dumps(_summary()))
    res = load_directory(main, archive, tmp_path, write=False)
    assert res[0]["status"] == "would_archive" and _count(archive, "archive_financial_tuples") == 0


def test_two_years_load_and_give_a_multi_period_trend_from_the_archive(main, archive, tmp_path):
    (tmp_path / "ogdc_2024.json").write_text(json.dumps(_summary("2024-06-30")))
    (tmp_path / "ogdc_2025.json").write_text(json.dumps(_summary()))
    res = load_directory(main, archive, tmp_path, write=True)
    assert [r["status"] for r in res] == ["archived", "archived"]
    h = hist.load_history(main, archive, _company(main), scope="unconsolidated")
    assert h["source"] == "archive" and \
        [p["period_end"] for p in h["periods"]] == ["2024-06-30", "2025-06-30"]
    m25 = h["periods"][1]["metrics"]
    assert m25["gross_profit"] / m25["revenue"] == pytest.approx(0.4)
    assert h["gaps"] == []


def test_rerunning_the_loader_is_idempotent(main, archive, tmp_path):
    (tmp_path / "ogdc_2025.json").write_text(json.dumps(_summary()))
    load_directory(main, archive, tmp_path, write=True)
    n = _count(archive, "archive_financial_tuples")
    load_directory(main, archive, tmp_path, write=True)
    assert _count(archive, "archive_financial_tuples") == n


def test_synthetic_fixtures_are_refused_unless_explicitly_allowed(main, archive, tmp_path):
    (tmp_path / "fx.json").write_text(json.dumps(_summary(provenance="synthetic_fixture")))
    assert load_directory(main, archive, tmp_path, write=True)[0]["status"] == "refused"
    assert _count(archive, "archive_reports") == 0
    ok = load_directory(main, archive, tmp_path, write=True, allow_synthetic=True)
    assert ok[0]["status"] == "archived"


def test_bad_files_are_refused_and_do_not_stop_the_good_ones(main, archive, tmp_path):
    (tmp_path / "a_bad_json.json").write_text("{not json")
    (tmp_path / "b_unbalanced.json").write_text(json.dumps(
        _summary(metrics={"total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 150.0})))
    (tmp_path / "c_unknown.json").write_text(json.dumps(_summary(ticker="ZZZZ")))
    (tmp_path / "d_good.json").write_text(json.dumps(_summary()))
    res = {r["file"]: r for r in load_directory(main, archive, tmp_path, write=True)}
    assert res["a_bad_json.json"]["status"] == "refused"
    assert res["b_unbalanced.json"]["status"] == "refused"
    assert res["c_unknown.json"]["status"] == "refused" and "master" in res["c_unknown.json"]["reasons"][0]
    assert res["d_good.json"]["status"] == "archived"


@pytest.mark.parametrize("bad", [
    {"provenance": "scraped"},
    {"doc_type": "quarterly"},
    {"unit_scale": 7},
    {"metrics": {"revenue": "1,000"}},
    {"metrics": {"revenue": True}},
    {"metrics": {"total_assets": 500.0}},  # no identity can be checked
])
def test_validation_refuses_what_cannot_be_checked(bad):
    v = repo.validate_summary(_summary(**bad))
    assert v["ok"] is False and v["reasons"]


# ------------------------------------------------------------------ unified history entry point

def test_history_says_where_it_came_from(main, archive):
    assert hist.load_history(main, None, _company(main), scope="unconsolidated")["source"] == "none"
    # promoted in the operational database only: a labelled fallback, never presented as archive depth
    from tests import test_m2_m3_financials as m2
    r = m2._imp(main, m2._corp())
    fin.promote(main, r["report_id"])
    h = hist.load_history(main, archive, _company(main), scope="unconsolidated")
    assert h["source"] == "main_fallback" and len(h["periods"]) == 1


def test_archive_disclosure_payload_is_bounded_by_the_database_too(archive):
    with pytest.raises(Exception, match="CHECK|constraint"):
        archive.execute("INSERT INTO archive_disclosures VALUES (?,?,?,?,?,?,?,?)",
                        ("e" * 64, "c", "material_disclosure", "2025-01-01", "t", "{" + "x" * 70000 + "}",
                         None, "2025-01-01"))


def _company(db) -> str:
    return db.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' "
                      "AND value = 'OGDC' AND valid_to IS NULL")[0]["company_id"]
