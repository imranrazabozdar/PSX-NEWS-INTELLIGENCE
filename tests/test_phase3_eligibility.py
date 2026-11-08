"""Phase 3 item eligibility excludes only Phase 3's own processing records (offline, SYNTHETIC data)."""

from __future__ import annotations

import hashlib

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import schema
from engines.pipeline import ITEM_SQL

T0 = "2026-11-05T06:00:00Z"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    d.execute("INSERT INTO sources(source_id, name, source_type, owner, is_synthetic, created_at_utc, "
              "updated_at_utc) VALUES ('syn','SYNTHETIC paper','news_media','Owner',1,?,?)", (T0, T0))
    for k in (1, 2, 3):
        url = f"https://example.invalid/{k}"
        d.execute("INSERT INTO source_items(source_id, canonical_url, title, permitted_excerpt, "
                  "published_at_utc, collected_at_utc, content_sha256) VALUES ('syn',?,?,?,?,?,?)",
                  (url, f"Synthetic headline {k}", f"Synthetic permitted excerpt {k}.", T0, T0,
                   hashlib.sha256(url.encode()).hexdigest()))
    yield d
    d.close()


def _record(db, item_id, schema_version, model):
    db.execute("INSERT INTO event_extractions(source_item_id, schema_version, prompt_version, model, "
               "extracted_json, confidence_explanation, needs_human_review, review_reasons_json, "
               "provenance_json, created_at_utc) VALUES (?,?,'none',?,'{}','synthetic',0,'[]','{}',?)",
               (item_id, schema_version, model, T0))


def test_headline_builder_records_do_not_block_phase3_but_phase3_records_do(db):
    _record(db, 1, "headline-event/1", "deterministic")  # processed only by the headline builder
    _record(db, 2, schema.SCHEMA_VERSION, "fake-model")   # processed by Phase 3 itself
    eligible = [r["source_item_id"] for r in db.execute(ITEM_SQL, (10,))]
    assert eligible == [1, 3]


def test_phase3_exclusion_uses_its_own_schema_version():
    assert schema.SCHEMA_VERSION == "event-extraction/1" and f"'{schema.SCHEMA_VERSION}'" in ITEM_SQL
