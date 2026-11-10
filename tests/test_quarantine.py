"""Quarantine of extraction records that did not originate in this project's pipeline.

Synthetic records only. The tests insert a legacy-shaped row directly and check that it is reported,
never modified, and never reaches scoring."""

from __future__ import annotations

import ast
import pathlib

import pytest

from database import repositories as repo
from database import seed_loader
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import event_intel, headline_events, impact_intel, quarantine, schema

ENGINES = pathlib.Path(__file__).resolve().parents[1] / "engines"
LEGACY = "event_candidate/1"          # the schema id the technical engine wrote before separation
NOW = "2026-11-10T09:00:00Z"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def _source_item(db, url):
    return repo.record_source_item(db, source_id="psx", url=url, content="synthetic",
                                   collected_at_utc=NOW, title="synthetic headline").source_item_id


def _insert_extraction(db, *, source_item_id, schema_version, event_id=None):
    db.execute(
        "INSERT INTO event_extractions(source_item_id, event_id, call_id, schema_version, prompt_version, "
        "model, extracted_json, confidence, confidence_explanation, needs_human_review, review_reasons_json, "
        "provenance_json, created_at_utc) VALUES (?,?,NULL,?,'v1','m','{}',NULL,'synthetic',1,'[]','{}',?)",
        (source_item_id, event_id, schema_version, NOW))


def test_only_this_projects_schema_versions_are_eligible():
    assert quarantine.NEWS_SCHEMA_VERSIONS == frozenset({
        event_intel.SCHEMA_VERSION, schema.SCHEMA_VERSION, headline_events.SCHEMA_VERSION})
    for version in quarantine.NEWS_SCHEMA_VERSIONS:
        assert quarantine.classify(version) == quarantine.ELIGIBLE


@pytest.mark.parametrize("version", [LEGACY, "financial_line_items/1", "", None, "event-intel/2",
                                     "EVENT-INTEL/1"])
def test_legacy_unknown_empty_and_near_miss_versions_are_quarantined(version):
    assert quarantine.classify(version) == quarantine.QUARANTINED
    assert quarantine.is_eligible(version) is False


def test_sql_filter_keeps_only_eligible_versions():
    clause = quarantine.sql_eligible_filter()
    for version in quarantine.NEWS_SCHEMA_VERSIONS:
        assert f"'{version}'" in clause
    assert LEGACY not in clause


def test_report_counts_legacy_records_and_changes_nothing(db):
    news_item = _source_item(db, "https://example.com/news-1")
    legacy_item = _source_item(db, "https://example.com/legacy-1")
    _insert_extraction(db, source_item_id=news_item, schema_version=event_intel.SCHEMA_VERSION)
    _insert_extraction(db, source_item_id=legacy_item, schema_version=LEGACY)
    before = db.execute("SELECT extraction_id, schema_version, extracted_json FROM event_extractions "
                        "ORDER BY extraction_id")
    summary = quarantine.report(db)
    assert summary["by_schema"][LEGACY]["status"] == quarantine.QUARANTINED
    assert summary["by_schema"][event_intel.SCHEMA_VERSION]["status"] == quarantine.ELIGIBLE
    assert summary["totals"] == {quarantine.ELIGIBLE: 1, quarantine.QUARANTINED: 1}
    assert summary["changed_records"] == 0
    after = db.execute("SELECT extraction_id, schema_version, extracted_json FROM event_extractions "
                       "ORDER BY extraction_id")
    assert [dict(r) for r in before] == [dict(r) for r in after]


def test_legacy_records_cannot_be_updated_or_deleted_by_any_path(db):
    item = _source_item(db, "https://example.com/legacy-2")
    _insert_extraction(db, source_item_id=item, schema_version=LEGACY)
    with pytest.raises(DatabaseError):
        db.execute("UPDATE event_extractions SET schema_version = 'event-intel/1' WHERE source_item_id = ?",
                   (item,))
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM event_extractions WHERE source_item_id = ?", (item,))


def test_a_legacy_only_event_is_never_selected_for_impact_scoring(db):
    item = _source_item(db, "https://example.com/legacy-3")
    event_id = repo.create_event(db, {"event_type": "monetary_policy", "headline": "Synthetic legacy event",
                                      "status_stage": "approval"}, changed_by="test")
    _insert_extraction(db, source_item_id=item, schema_version=LEGACY, event_id=event_id)
    assert event_id not in impact_intel._assessed_events(db, 1000)


def test_a_project_event_is_selected_and_legacy_rows_do_not_leak_into_it(db):
    legacy_item = _source_item(db, "https://example.com/legacy-4")
    news_item = _source_item(db, "https://example.com/news-4")
    event_id = repo.create_event(db, {"event_type": "monetary_policy", "headline": "Synthetic mixed event",
                                      "status_stage": "approval"}, changed_by="test")
    _insert_extraction(db, source_item_id=legacy_item, schema_version=LEGACY, event_id=event_id)
    _insert_extraction(db, source_item_id=news_item, schema_version=event_intel.SCHEMA_VERSION,
                       event_id=event_id)
    assert event_id in impact_intel._assessed_events(db, 1000)
    # the filter is built from a module constant, never from input
    eligible = quarantine.sql_eligible_filter()
    sql = f"SELECT DISTINCT schema_version FROM event_extractions WHERE event_id = ? AND {eligible}"  # noqa: S608
    rows = db.execute(sql, (event_id,))
    assert [r["schema_version"] for r in rows] == [event_intel.SCHEMA_VERSION]


def _sql_strings(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_every_read_of_extraction_records_is_schema_scoped():
    """Regression guard: a new query over event_extractions must filter by schema_version, or be the
    quarantine report itself (which only counts)."""
    offenders = []
    for path in sorted(ENGINES.glob("*.py")):
        if path.name == "quarantine.py":
            continue
        for text in _sql_strings(path):
            if "FROM event_extractions" in text and "schema_version" not in text:
                offenders.append(f"{path.name}: {text.strip()[:80]}")
    assert offenders == [], offenders
