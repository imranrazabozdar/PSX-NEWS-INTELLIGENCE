"""Disposable-Turso verification of migrations 0006-0009 (gate 3). OPT-IN; never production.

Runs only when BOTH of these are set, to a database created solely for this test:
  PSXNI_TURSO_DISPOSABLE_DATABASE_URL, PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN
It refuses to run if the URL matches the production database or PSXNI_TURSO_DATABASE_URL, or if the
target already has tables (it must be empty). See docs/TURSO_DISPOSABLE_VERIFICATION.md.

Status: prepared but NOT YET EXECUTED against a real Turso server (no disposable database exists).
All data written is SYNTHETIC; the disposable database should be destroyed afterwards.
"""

from __future__ import annotations

import os
import threading

import pytest

from database.connection import DatabaseError, TursoHTTPDatabase
from database.migrate import migrate

URL = os.environ.get("PSXNI_TURSO_DISPOSABLE_DATABASE_URL", "")
TOKEN = os.environ.get("PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN", "")
PRODUCTION_MARKERS = ("psx-news-intelligence-imranrazabozdar",)
NOW = "2026-11-08T00:00:00Z"

pytestmark = pytest.mark.skipif(not (URL and TOKEN),
                                reason="disposable Turso database not configured: gate 3 not run")


def _guard():
    prod = os.environ.get("PSXNI_TURSO_DATABASE_URL", "")
    if any(m in URL for m in PRODUCTION_MARKERS) or (prod and prod.rstrip("/") == URL.rstrip("/")):
        pytest.fail("refusing to run: the disposable URL points at the production database")


@pytest.fixture(scope="module")
def db():
    _guard()
    d = TursoHTTPDatabase(URL, TOKEN)
    existing = d.execute("SELECT COUNT(*) n FROM sqlite_master WHERE type='table'")[0]["n"]
    if existing:
        pytest.fail("refusing to run: the disposable database is not empty")
    migrate(d)
    return d


def test_all_migrations_apply_and_foreign_keys_enforced(db):
    assert db.execute("SELECT MAX(version) v FROM schema_migrations")[0]["v"] == 9
    assert db.validate()["foreign_keys"] is True


def _setup_event(db):
    db.batch([
        ("INSERT INTO sources(source_id, name, source_type, reliability_tier, access_status, terms_status, "
         "lifecycle_status, enabled, is_synthetic, created_at_utc, updated_at_utc) VALUES ('synapproved', "
         "'SYNTHETIC','other','primary_official','verified_permitted','approved','ACTIVE',1,1,?,?)",
         (NOW, NOW)),
        ("INSERT INTO companies(company_id, legal_name, listing_status, created_at_utc, updated_at_utc) "
         "VALUES ('cmp-syn-alpha','Synthetic Alpha Ltd','listed',?,?)", (NOW, NOW)),
        ("INSERT INTO events(event_id, event_type, headline, status_stage, verification_state, "
         "first_seen_at_utc, created_at_utc, updated_at_utc) VALUES (1,'commodity_price','SYNTHETIC',"
         "'confirmed_fact','corroborated',?,?,?)", (NOW, NOW, NOW)),
        ("INSERT INTO event_revisions VALUES (1,1,?,'confirmed_fact','corroborated','SYNTHETIC',NULL,'{}',"
         "'created','test',NULL,NULL)", (NOW,)),
    ])


ASSESS = ("INSERT INTO impact_assessments(event_id, event_revision_no, company_id, mechanism_id, "
          "transmission_version, ruleset_version, scenario_kind, assessment_status, status_reason, "
          "direction, "
          "magnitude_level, magnitude_basis, horizon, evidence_confidence, exposure_confidence, "
          "direction_confidence, magnitude_confidence, scenario_uncertainty, confidence_reasons_json, "
          "affected_lines_json, counter_evidence_json, missing_inputs_json, freshness_basis, is_synthetic, "
          "change_reason, changed_by, actor_type, created_at_utc, updated_at_utc) "
          "VALUES (1,1,'cmp-syn-alpha',"
          "'T1','t','r',?,'needs_review','created_needs_review','unknown','low','qualitative','short',"
          "'low','low',"
          "'low','low','undetermined','{}','[]','[]','[]','not_established',1,'c','system:test','system',?,?)")


def test_composite_fk_and_cascade_over_http(db):
    _setup_event(db)
    db.execute(ASSESS, ("current", NOW, NOW))
    with pytest.raises(DatabaseError):   # composite FK to event_revisions
        db.execute(ASSESS.replace("VALUES (1,1,", "VALUES (1,99,"), ("hypothetical", NOW, NOW))
    db.batch([("INSERT INTO event_revisions VALUES (1,2,?,'confirmed_fact','refuted','SYNTHETIC',NULL,'{}',"
               "'refuted','test',NULL,NULL)", (NOW,)),
              ("UPDATE events SET verification_state='refuted', current_revision=2, updated_at_utc=? "
               "WHERE event_id=1", (NOW,))])
    row = db.execute("SELECT assessment_status, status_reason FROM impact_assessments WHERE event_id=1")[0]
    assert (row["assessment_status"], row["status_reason"]) == ("withdrawn_evidence_invalid", "event_refuted")
    revs = db.execute("SELECT COUNT(*) n FROM impact_assessment_revisions WHERE assessment_id=1")[0]["n"]
    assert revs == 2


def test_policy_approval_race_over_http(db):
    db.batch([("INSERT INTO impact_expiry_policy_versions VALUES ('race/1','{}','SYNTHETIC','tester',?,NULL)",
               (NOW,)),
              ("INSERT INTO impact_expiry_policy_versions VALUES ('race/2','{}','SYNTHETIC','tester',?,NULL)",
               (NOW,))])
    results = {}

    def approve(version):
        conn = TursoHTTPDatabase(URL, TOKEN)
        try:
            conn.execute("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, "
                         "effective_from_utc, recorded_at_utc, notes) "
                         "VALUES (?,'approved','tester',?,?,'race')",
                         (version, "2027-01-01T00:00:00Z", NOW))
            results[version] = "ok"
        except DatabaseError as exc:
            results[version] = str(exc)

    threads = [threading.Thread(target=approve, args=(v,)) for v in ("race/1", "race/2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results.values()).count("ok") == 1, results
    assert db.execute("SELECT COUNT(*) n FROM impact_expiry_policy_overlaps")[0]["n"] == 0
