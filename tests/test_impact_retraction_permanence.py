"""Retractions are permanent: evidence_retractions cannot be replaced (migration 0009, SYNTHETIC data only).

Reproduces the HIGH defect from the final acceptance audit of d4fbd70. Without a guard, a REPLACE reusing the
retraction_id or the (record_table, record_id) pair erased a retraction (REPLACE deletes without firing delete
triggers). The retracted evidence could then be re-mapped and re-accepted with no trace.
"""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines.exposure_mapping import map_event, retract_evidence, review
from tests.db_clock import DatabaseClock
from tests.test_impact_assessments import (
    _assess,
    _base,
    _candidate,
    _event,
    _exposure,
    _link_candidate,
    _review,
    _update,
)

HUMAN = {"actor_type": "human", "changed_by": "human:owner"}
COLS = "retraction_id, record_table, record_id, reason, retracted_by, retracted_at_utc"


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    yield d
    d.close()


def _rel(db, modifier):
    return db.execute("SELECT date('now', ?) d", (modifier,))[0]["d"]


def _confirmed(db, valid_to="2099-12-31"):
    """Company-specific evidence -> accepted candidate -> confirmed assessment."""
    _exposure(db, "cmp-syn-alpha", valid_to=valid_to)
    eid = _event(db, date=_rel(db, "-10 days"))
    cand = _candidate(db, eid, "cmp-syn-alpha", confirm=True)
    aid = _assess(db, eid, "cmp-syn-alpha")
    _link_candidate(db, aid, cand)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=rid, **HUMAN)
    x = db.execute("SELECT company_exposure_id x FROM exposure_candidate_evidence WHERE candidate_id=? "
                   "AND company_exposure_id IS NOT NULL", (cand,))[0]["x"]
    return eid, cand, aid, x


def _unlinked(db):
    _exposure(db, "cmp-syn-beta", subject="unrelated SYNTHETIC record")
    return db.execute("SELECT MAX(exposure_id) x FROM company_exposures")[0]["x"]


def _state(db, cand, aid):
    """Everything a failed attempt must leave unchanged."""
    return (
        [tuple(r) for r in db.execute(
            f"SELECT {COLS} FROM evidence_retractions ORDER BY retraction_id")],  # noqa: S608
        tuple(db.execute("SELECT evidence_status, current_revision, review_status FROM exposure_candidates "
                         "WHERE candidate_id=?", (cand,))[0]),
        db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions WHERE candidate_id=?",
                   (cand,))[0]["n"],
        tuple(db.execute("SELECT assessment_status, current_revision FROM impact_assessments "
                         "WHERE assessment_id=?", (aid,))[0]),
        db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                   (aid,))[0]["s"],
    )


@pytest.fixture
def retracted(db):
    eid, cand, aid, x = _confirmed(db)
    retract_evidence(db, "company_exposures", x, reason="SYNTHETIC: incorrect", retracted_by="owner")
    rid = db.execute("SELECT retraction_id FROM evidence_retractions")[0]["retraction_id"]
    return eid, cand, aid, x, rid


# ------------------------------------------------------------------ guard behaviour
def test_first_retraction_succeeds_and_downgrades(db, retracted):
    eid, cand, aid, x, rid = retracted
    assert db.execute("SELECT record_table, record_id FROM evidence_retractions WHERE retraction_id=?",
                      (rid,))[0]["record_id"] == x
    assert db.execute("SELECT evidence_status s FROM exposure_candidates WHERE candidate_id=?",
                      (cand,))[0]["s"] == "unverified"
    assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"] == "needs_revalidation"


def test_legitimate_retraction_of_another_record_still_works(db, retracted):
    other = _unlinked(db)
    retract_evidence(db, "company_exposures", other, reason="SYNTHETIC: also wrong", retracted_by="owner")
    assert db.execute("SELECT COUNT(*) n FROM evidence_retractions")[0]["n"] == 2


def _attacks(rid, x, other):
    v_same_id = (rid, "company_exposures", other, "erased", "attacker", "t")       # same id, altered target
    v_same_rec = (rid + 100, "company_exposures", x, "erased", "attacker", "t")     # same record, new id
    q = f"INTO evidence_retractions({COLS}) VALUES (?,?,?,?,?,?)"
    return [
        ("insert-dup-id", f"INSERT {q}", v_same_id),
        ("insert-dup-record", f"INSERT {q}", v_same_rec),
        ("insert-or-replace-id", f"INSERT OR REPLACE {q}", v_same_id),
        ("insert-or-replace-record", f"INSERT OR REPLACE {q}", v_same_rec),
        ("replace-id", f"REPLACE {q}", v_same_id),
        ("replace-record", f"REPLACE {q}", v_same_rec),
        ("insert-or-ignore-id", f"INSERT OR IGNORE {q}", v_same_id),
        ("upsert-id", f"INSERT {q} ON CONFLICT(retraction_id) DO UPDATE SET record_id=excluded.record_id, "
                      "reason=excluded.reason", v_same_id),
        ("upsert-record", f"INSERT {q} ON CONFLICT(record_table, record_id) DO UPDATE SET reason='erased', "
                          "retraction_id=excluded.retraction_id", v_same_rec),
        ("upsert-any", f"INSERT {q} ON CONFLICT DO UPDATE SET record_id={other}", v_same_id),
        ("upsert-nothing", f"INSERT {q} ON CONFLICT DO NOTHING", v_same_rec),
    ]


ATTACK_IDS = [a[0] for a in _attacks(1, 1, 2)]


@pytest.mark.parametrize("attack", ATTACK_IDS)
@pytest.mark.parametrize("fk", [True, False], ids=["fk-on", "fk-off"])
def test_replace_and_upsert_cannot_overwrite_a_retraction(db, retracted, attack, fk):
    eid, cand, aid, x, rid = retracted
    other = _unlinked(db)
    if not fk:
        db._conn.execute("PRAGMA foreign_keys = OFF")
    _, sql, vals = next(a for a in _attacks(rid, x, other) if a[0] == attack)
    before = _state(db, cand, aid)
    with pytest.raises(DatabaseError, match="retractions are permanent"):
        db.execute(sql, vals)
    # the retraction is byte-identical; candidate, revisions and assessment are unchanged
    assert _state(db, cand, aid) == before


def test_update_and_delete_protections_unchanged(db, retracted):
    eid, cand, aid, x, rid = retracted
    for sql in ("UPDATE evidence_retractions SET record_id=record_id+1",
                "DELETE FROM evidence_retractions",
                "UPDATE OR REPLACE evidence_retractions SET retraction_id=999"):
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(sql)


# ------------------------------------------------------------------ the original attack, end to end
def test_original_attack_is_blocked_and_evidence_never_regains_eligibility(db, retracted):
    eid, cand, aid, x, rid = retracted
    original = _state(db, cand, aid)
    other = _unlinked(db)
    q = f"REPLACE INTO evidence_retractions({COLS}) VALUES (?,?,?,?,?,?)"  # noqa: S608
    # 1. same retraction_id, altered target and reason (the audited attack)
    with pytest.raises(DatabaseError, match="retractions are permanent"):
        db.execute(q, (rid, "company_exposures", other, "erased by attacker", "attacker", "t"))
    # 2. same (record_table, record_id), different retraction_id
    with pytest.raises(DatabaseError, match="retractions are permanent"):
        db.execute(q, (rid + 1, "company_exposures", x, "erased by attacker", "attacker", "t"))
    assert _state(db, cand, aid) == original
    # 3. re-mapping the original event cannot restore the candidate
    try:
        map_event(db, eid, synthetic=True)
    except DatabaseError:
        pass
    # 4. human re-acceptance cannot restore it either
    try:
        review(db, cand, "accept", reviewer="owner", notes="SYNTHETIC re-accept attempt")
    except (DatabaseError, ValueError):
        pass
    assert db.execute("SELECT 1 FROM evidence_retractions WHERE retraction_id=? "   # permanent
                      "AND record_table='company_exposures' AND record_id=?", (rid, x))
    c = db.execute("SELECT effective_status s, evidence_currently_valid v FROM exposure_candidates_current "
                   "WHERE candidate_id=?", (cand,))[0]
    assert c["s"] not in ("strongly_supported", "confirmed") and c["v"] == 0
    assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"] == "needs_revalidation"
    # 5. no new eligible (let alone confirmed) assessment can be built from the retracted evidence
    new = _assess(db, eid, "cmp-syn-alpha", mechanism="T2")
    _link_candidate(db, new, cand)
    with pytest.raises(DatabaseError):
        _update(db, new, assessment_status="provisional", status_reason="created_eligible")
    with pytest.raises(DatabaseError):
        rid2 = _review(db, new, "accept")
        _update(db, new, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
                last_review_id=rid2, **HUMAN)
    assert db.execute("SELECT COUNT(*) n FROM impact_assessments_current WHERE effective_status IN "
                      "('provisional','confirmed_conclusion')")[0]["n"] == 0


# ------------------------------------------------------------------ database clock (retained caveat)
def test_expiry_decision_uses_the_database_clock(db):
    clock = DatabaseClock(db)                       # installed before any statement under test is prepared
    eid, cand, aid, x = _confirmed(db, valid_to=_rel(db, "+1 day"))
    for days, expected in ((0, "confirmed_conclusion"), (1, "confirmed_conclusion"),
                           (2, "needs_revalidation")):
        clock.advance_days(days)
        assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                          (aid,))[0]["s"] == expected, days
    clock.now = None                                # back to the real clock: still fresh today
    assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"] == "confirmed_conclusion"
