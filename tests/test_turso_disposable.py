"""Disposable-Turso verification of migrations 0006-0009 (gate 3). OPT-IN; never production.

Runs only when BOTH of these are set, to a database created solely for this test:
  PSXNI_TURSO_DISPOSABLE_DATABASE_URL, PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN
The gate (tests/turso_guard.py: disposable_config_status) skips when neither is set. It FAILS when the
configuration is incomplete, the URL is not a Turso URL, the URL looks like production or shares the
production host, or the token equals the production token. Production variables are never used to connect.
The target must also be empty. See docs/TURSO_DISPOSABLE_VERIFICATION.md.

The migration 0009 protection tests at the end run over HTTP against the real server clock. All data is
append-only by design and cannot be deleted, so clean up by DESTROYING the disposable database afterwards.

Status: prepared but NOT YET EXECUTED against a real Turso server (no disposable database exists).
All data written is SYNTHETIC; the disposable database should be destroyed afterwards.
"""

from __future__ import annotations

import os
import threading

import pytest

from database.connection import DatabaseError, TursoHTTPDatabase
from database.migrate import discover, migrate
from tests.turso_guard import (
    DISPOSABLE_TOKEN_VAR,
    DISPOSABLE_URL_VAR,
    SUITE_NOT_RUN_MESSAGE,
    disposable_config_status,
)

URL = os.environ.get(DISPOSABLE_URL_VAR, "").strip()
TOKEN = os.environ.get(DISPOSABLE_TOKEN_VAR, "").strip()
NOW = "2026-11-08T00:00:00Z"
_STATUS, _REASON = disposable_config_status(os.environ)
if _STATUS == "skip":  # nothing configured: NOT_RUN, named as such (never a failure offline)
    _REASON = SUITE_NOT_RUN_MESSAGE

pytestmark = pytest.mark.skipif(_STATUS == "skip", reason=_REASON)


def _guard():
    if _STATUS != "ok":
        pytest.fail(_REASON)


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
    latest = max(m.version for m in discover())
    assert db.execute("SELECT MAX(version) v FROM schema_migrations")[0]["v"] == latest
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


# ------------------------------------------------------------------ migration 0009 protections over HTTP
# Reuses the SQL-level fixtures of tests/test_impact_assessments.py through the Database interface, so the
# same statements run on the server. Each test uses its own synthetic company, so tests stay independent
# within the one shared disposable database. Expiry uses the REAL server clock (date('now')): no clock
# helper.
from tests.test_impact_assessments import (  # noqa: E402
    _assess,
    _candidate,
    _event,
    _exposure,
    _link_candidate,
    _review,
    _update,
)

SRC = "synturso"
HUMAN = {"actor_type": "human", "changed_by": "human:owner"}


@pytest.fixture(scope="module")
def seeded(db):
    db.batch([
        ("INSERT INTO sources(source_id, name, source_type, reliability_tier, access_status, terms_status, "
         "lifecycle_status, enabled, is_synthetic, created_at_utc, updated_at_utc) VALUES (?, 'SYNTHETIC "
         "turso', 'other','primary_official','verified_permitted','approved','ACTIVE',1,1,?,?)",
         (SRC, NOW, NOW)),
        ("INSERT INTO sectors(sector_id, scheme, name, created_at_utc) VALUES "
         "('psx-syn-turso','PSX','SYNTHETIC TURSO SECTOR',?)", (NOW,)),
    ])
    return db


def _company(db, tag):
    cid = f"cmp-syn-t{tag}"
    db.batch([
        ("INSERT INTO companies(company_id, legal_name, listing_status, created_at_utc, updated_at_utc) "
         "VALUES (?,?,'listed',?,?)", (cid, f"Synthetic T{tag} Ltd", NOW, NOW)),
        ("INSERT INTO company_identifiers(company_id, id_type, value, verified_at_utc) VALUES (?,?,?,?)",
         (cid, "psx_ticker", f"SYNT{tag.upper()}", NOW)),
        ("INSERT INTO company_classifications(company_id, sector_id, valid_from, verified_at_utc) "
         "VALUES (?, 'psx-syn-turso', '2000-01-01', ?)", (cid, NOW)),
    ])
    return cid


def _rel(db, modifier):
    return db.execute("SELECT date('now', ?) d", (modifier,))[0]["d"]


def _chain(db, tag, valid_to="2099-12-31", upgrade=True):
    company = _company(db, tag)
    _exposure(db, company, source=SRC, valid_to=valid_to)
    eid = _event(db, source=SRC, date=_rel(db, "-10 days"))
    cand = _candidate(db, eid, company, confirm=True)
    aid = _assess(db, eid, company)
    _link_candidate(db, aid, cand)
    if upgrade:
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    x = db.execute("SELECT company_exposure_id x FROM exposure_candidate_evidence WHERE candidate_id=? "
                   "AND company_exposure_id IS NOT NULL", (cand,))[0]["x"]
    return company, eid, cand, aid, x


def _eff(db, aid):
    return db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"]


def test_0009_guards_installed_over_http(seeded):
    names = {r["name"] for r in seeded.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_impact_assessments_update", "trg_company_exposures_linked_immutable",
            "trg_company_exposures_linked_no_replace", "trg_evidence_retractions_no_replace",
            "trg_exposure_candidates_no_replace", "trg_exposure_candidate_evidence_no_replace",
            "trg_exposure_candidate_revisions_no_replace"} <= names
    assert seeded.execute("SELECT 1 FROM sqlite_master WHERE name='ux_impact_revisions_review_once'")


def test_review_single_use_over_http(seeded):
    _, _, _, aid, _ = _chain(seeded, "rev")
    r1 = _review(seeded, aid, "request_revalidation")
    _update(seeded, aid, assessment_status="needs_revalidation",
            status_reason="reviewer_requested_revalidation", last_review_id=r1, **HUMAN)
    _update(seeded, aid, assessment_status="provisional", status_reason="revalidated")
    r2 = _review(seeded, aid, "needs_more_evidence")
    _update(seeded, aid, assessment_status="needs_review", status_reason="reviewer_needs_more_evidence",
            last_review_id=r2, **HUMAN)
    _update(seeded, aid, assessment_status="provisional", status_reason="revalidated")
    with pytest.raises(DatabaseError, match="already used|stale"):
        _update(seeded, aid, assessment_status="needs_revalidation",
                status_reason="reviewer_requested_revalidation", last_review_id=r1, **HUMAN)


def test_every_linked_exposure_freshness_with_server_clock(seeded):
    # linked at the event date (10 days ago) but expired yesterday by the SERVER clock
    _, _, _, aid, _ = _chain(seeded, "exp", valid_to=_rel(seeded, "-1 day"), upgrade=False)
    with pytest.raises(DatabaseError, match="explicit source expiry not verified"):
        _update(seeded, aid, assessment_status="provisional", status_reason="created_eligible")
    _, _, _, aid2, _ = _chain(seeded, "today", valid_to=_rel(seeded, "+0 days"))
    assert _eff(seeded, aid2) == "provisional"                      # valid through today


def test_linked_exposure_immutability_over_http(seeded):
    _, _, _, aid, x = _chain(seeded, "imm")
    before = seeded.execute("SELECT * FROM company_exposures WHERE exposure_id=?", (x,))[0]
    for sql in ("UPDATE company_exposures SET valid_to='2199-12-31' WHERE exposure_id=?",
                "UPDATE company_exposures SET subject='edited' WHERE exposure_id=?",
                "DELETE FROM company_exposures WHERE exposure_id=?",
                "REPLACE INTO company_exposures(exposure_id, company_id, exposure_kind, subject, confidence, "
                "source_item_id, evidence_excerpt, valid_to, last_verified_utc) "
                "SELECT exposure_id, company_id, exposure_kind, subject, confidence, source_item_id, "
                "evidence_excerpt, '2199-12-31', "
                "last_verified_utc FROM company_exposures WHERE exposure_id=?"):
        with pytest.raises(DatabaseError, match="immutable|cannot be replaced|cannot be deleted"):
            seeded.execute(sql, (x,))
    assert seeded.execute("SELECT * FROM company_exposures WHERE exposure_id=?", (x,))[0] == before
    assert _eff(seeded, aid) == "provisional"


def test_permanent_retraction_and_read_time_revalidation_over_http(seeded):
    from engines.exposure_mapping import retract_evidence
    _, _, cand, aid, x = _chain(seeded, "ret")
    retract_evidence(seeded, "company_exposures", x, reason="SYNTHETIC: incorrect", retracted_by="owner")
    assert _eff(seeded, aid) == "needs_revalidation"                # read-time invalidation
    rid = seeded.execute("SELECT retraction_id r FROM evidence_retractions "
                         "WHERE record_table='company_exposures' AND record_id=?", (x,))[0]["r"]
    q = ("REPLACE INTO evidence_retractions(retraction_id, record_table, record_id, reason, retracted_by, "
         "retracted_at_utc) VALUES (?,?,?,?,?,?)")
    for vals in ((rid, "company_exposures", x + 100000, "erased", "attacker", NOW),
                 (rid + 100000, "company_exposures", x, "erased", "attacker", NOW)):
        with pytest.raises(DatabaseError, match="retractions are permanent"):
            seeded.execute(q, vals)
    with pytest.raises(DatabaseError, match="append-only"):
        seeded.execute("DELETE FROM evidence_retractions WHERE retraction_id=?", (rid,))
    assert seeded.execute("SELECT record_id FROM evidence_retractions WHERE retraction_id=?",
                          (rid,))[0]["record_id"] == x
    assert _eff(seeded, aid) == "needs_revalidation"


def test_exposure_chain_replace_guards_over_http(seeded):
    _, _, cand, _, x = _chain(seeded, "chain")
    row = seeded.execute("SELECT * FROM exposure_candidates WHERE candidate_id=?", (cand,))[0]
    reset = dict(row, evidence_status="unverified", current_revision=1, review_status="pending",
                 last_review_id=None, change_reason="reset")
    cols = list(reset)
    with pytest.raises(DatabaseError, match="existing candidates cannot be replaced"):
        seeded.execute(f"REPLACE INTO exposure_candidates({', '.join(cols)}) "  # noqa: S608
                       f"VALUES ({', '.join('?' * len(cols))})", [reset[c] for c in cols])
    link = seeded.execute("SELECT rowid AS rid, source_item_id FROM exposure_candidate_evidence "
                          "WHERE company_exposure_id=?", (x,))[0]
    with pytest.raises(DatabaseError, match="existing evidence links cannot be replaced"):
        seeded.execute("REPLACE INTO exposure_candidate_evidence(rowid, candidate_id, role, "
                       "company_exposure_id, source_item_id, added_at_utc) VALUES (?,?,?,?,?,?)",
                       (link["rid"], cand, "company_specific", x, link["source_item_id"], NOW))
    rev = seeded.execute("SELECT * FROM exposure_candidate_revisions WHERE candidate_id=? "
                         "ORDER BY revision_no DESC LIMIT 1", (cand,))[0]
    rewritten = dict(rev, evidence_status="confirmed", change_reason="rewritten")
    cols = list(rewritten)
    with pytest.raises(DatabaseError, match="existing revisions cannot be replaced"):
        seeded.execute(f"REPLACE INTO exposure_candidate_revisions({', '.join(cols)}) "  # noqa: S608
                       f"VALUES ({', '.join('?' * len(cols))})", [rewritten[c] for c in cols])
    assert seeded.execute("SELECT * FROM exposure_candidates WHERE candidate_id=?", (cand,))[0] == row
    assert seeded.execute("SELECT * FROM exposure_candidate_revisions WHERE candidate_id=? AND revision_no=?",
                          (cand, rev["revision_no"]))[0] == rev
