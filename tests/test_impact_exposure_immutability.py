"""Linked company-specific exposure evidence is immutable (migration 0009, SYNTHETIC data only).

A company_exposures record referenced by exposure_candidate_evidence.company_exposure_id cannot be edited,
replaced or deleted through any write path. Expiry therefore depends only on the database clock and cannot be
reversed. Correction is retraction plus a NEW exposure record, a new candidate and new human review.
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
    _event,
    _exposure,
    _item,
    _link_candidate,
    _review,
    _update,
)

HUMAN = {"actor_type": "human", "changed_by": "human:owner"}
PROTECTED = {
    "valid_to": "2199-12-31", "valid_from": "1990-01-01", "company_id": "cmp-syn-beta",
    "exposure_kind": "energy", "subject": "edited subject", "confidence": "probable",
    "source_item_id": None,   # filled with another real source item in the test
    "evidence_excerpt": "edited excerpt", "last_verified_utc": "2199-01-01T00:00:00Z",
    "scope": "edited scope",
}


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    yield d
    d.close()


def _rel(db, modifier):
    return db.execute("SELECT date('now', ?) d", (modifier,))[0]["d"]


def _record(db, x):
    return dict(db.execute("SELECT * FROM company_exposures WHERE exposure_id=?", (x,))[0])


def _linked(db, valid_to="2099-12-31", event_date=None):
    _exposure(db, "cmp-syn-alpha", valid_to=valid_to)
    x = db.execute("SELECT MAX(exposure_id) x FROM company_exposures")[0]["x"]
    eid = _event(db, date=event_date or _rel(db, "-10 days"))
    map_event(db, eid, synthetic=True)
    cand = db.execute("SELECT candidate_id FROM exposure_candidates WHERE event_id=? "
                      "AND company_id='cmp-syn-alpha' AND exposure_level='direct'", (eid,))[0]["candidate_id"]
    assert db.execute("SELECT 1 FROM exposure_candidate_evidence WHERE candidate_id=? "
                      "AND company_exposure_id=? AND role='company_specific'", (cand, x))
    return x, eid, cand


# ------------------------------------------------------------------ write paths
@pytest.mark.parametrize("field", list(PROTECTED))
def test_update_of_each_protected_field_refused(db, field):
    x, _, _ = _linked(db)
    value = PROTECTED[field]
    if field == "source_item_id":
        value = _item(db, "synapproved", "SYNTHETIC other item")
    before = _record(db, x)
    with pytest.raises(DatabaseError, match="immutable"):
        db.execute(f"UPDATE company_exposures SET {field}=? WHERE exposure_id=?", (value, x))  # noqa: S608
    assert _record(db, x) == before


def test_update_of_several_fields_and_to_null_refused(db):
    x, _, _ = _linked(db)
    before = _record(db, x)
    for sql in ("UPDATE company_exposures SET valid_to='2199-12-31', subject='s', confidence='uncertain' "
                "WHERE exposure_id=?",
                "UPDATE company_exposures SET valid_to=NULL WHERE exposure_id=?",
                "UPDATE company_exposures SET valid_from='2000-01-01' WHERE exposure_id=?",
                "UPDATE OR REPLACE company_exposures SET valid_to='2199-12-31' WHERE exposure_id=?",
                "UPDATE OR IGNORE company_exposures SET valid_to='2199-12-31' WHERE exposure_id=?"):
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(sql, (x,))
    assert _record(db, x) == before


def test_key_change_and_key_takeover_refused(db):
    x, _, _ = _linked(db)
    _exposure(db, "cmp-syn-beta", subject="unrelated")       # unlinked record
    other = db.execute("SELECT MAX(exposure_id) x FROM company_exposures")[0]["x"]
    before = _record(db, x)
    with pytest.raises(DatabaseError, match="immutable"):     # move the linked record's key
        db.execute("UPDATE company_exposures SET exposure_id=999 WHERE exposure_id=?", (x,))
    with pytest.raises(DatabaseError, match="immutable"):     # take over the linked key from an unlinked row
        db.execute("UPDATE OR REPLACE company_exposures SET exposure_id=? WHERE exposure_id=?", (x, other))
    assert _record(db, x) == before


def _upsert_sql(verb, tail=""):
    return (
        f"{verb} INTO company_exposures(exposure_id, company_id, exposure_kind, subject, confidence, "  # noqa: S608
            "source_item_id, evidence_excerpt, valid_to, last_verified_utc) "
            "SELECT exposure_id, company_id, exposure_kind, subject, confidence, source_item_id, "
            "evidence_excerpt, '2199-12-31', last_verified_utc FROM company_exposures "
            f"WHERE exposure_id=? {tail}")


@pytest.mark.parametrize("sql", [
    _upsert_sql("INSERT", "ON CONFLICT(exposure_id) DO UPDATE SET valid_to=excluded.valid_to"),
    _upsert_sql("INSERT", "ON CONFLICT DO UPDATE SET valid_to='2199-12-31'"),
    _upsert_sql("INSERT OR REPLACE"),
    _upsert_sql("REPLACE"),
    _upsert_sql("INSERT OR IGNORE"),
    _upsert_sql("INSERT"),
], ids=["upsert-excluded", "upsert-literal", "insert-or-replace", "replace", "insert-or-ignore",
        "plain-insert"])
@pytest.mark.parametrize("fk", [True, False], ids=["fk-on", "fk-off"])
def test_upsert_and_replace_paths_refused(db, sql, fk):
    x, _, _ = _linked(db)
    if not fk:
        db._conn.execute("PRAGMA foreign_keys = OFF")
    before = _record(db, x)
    n = db.execute("SELECT COUNT(*) n FROM company_exposures")[0]["n"]
    with pytest.raises(DatabaseError, match="cannot be replaced|immutable"):
        db.execute(sql, (x,))
    assert _record(db, x) == before
    assert db.execute("SELECT COUNT(*) n FROM company_exposures")[0]["n"] == n


@pytest.mark.parametrize("fk", [True, False], ids=["fk-on", "fk-off"])
def test_delete_refused(db, fk):
    x, _, _ = _linked(db)
    if not fk:
        db._conn.execute("PRAGMA foreign_keys = OFF")
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        db.execute("DELETE FROM company_exposures WHERE exposure_id=?", (x,))
    assert _record(db, x)


def test_unlinked_record_keeps_correction_behaviour(db):
    _exposure(db, "cmp-syn-beta", subject="not yet linked")
    x = db.execute("SELECT MAX(exposure_id) x FROM company_exposures")[0]["x"]
    db.execute("UPDATE company_exposures SET valid_to='2199-12-31', subject='corrected' "
               "WHERE exposure_id=?", (x,))
    assert _record(db, x)["valid_to"] == "2199-12-31"


def test_retraction_and_new_record_still_work(db):
    x, _, _ = _linked(db)
    retract_evidence(db, "company_exposures", x, reason="SYNTHETIC: superseded", retracted_by="owner")
    assert db.execute("SELECT 1 FROM evidence_retractions WHERE record_table='company_exposures' "
                      "AND record_id=?", (x,))
    _exposure(db, "cmp-syn-alpha", subject="crude oil")
    assert db.execute("SELECT COUNT(*) n FROM company_exposures")[0]["n"] == 2


# ------------------------------------------------------------------ full lifecycle
def test_expiry_is_irreversible_and_replacement_needs_new_evidence_and_review(db):
    clock = DatabaseClock(db)
    # 1-2. a company-specific exposure record, linked to a candidate (valid through tomorrow)
    x, eid, cand = _linked(db, valid_to=_rel(db, "+1 day"))
    review(db, cand, "accept", reviewer="owner", notes="SYNTHETIC check")
    # 3. an assessment established on that evidence, then confirmed by a human
    aid = _assess(db, eid, "cmp-syn-alpha")
    _link_candidate(db, aid, cand)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=rid, **HUMAN)

    def eff():
        return db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                          (aid,))[0]["s"]
    assert eff() == "confirmed_conclusion"
    # 4-5. the database clock passes valid_to: the current view reports needs_revalidation
    clock.advance_days(2)
    assert eff() == "needs_revalidation"
    original = _record(db, x)
    # 6. extending valid_to directly is refused
    with pytest.raises(DatabaseError, match="immutable"):
        db.execute("UPDATE company_exposures SET valid_to=? WHERE exposure_id=?", (_rel(db, "+365 days"), x))
    # 7. other protected fields are refused too, including via REPLACE
    for field, value in (("valid_from", "2000-01-01"), ("subject", "crude oil (edited)"),
                         ("last_verified_utc", "2199-01-01T00:00:00Z"), ("evidence_excerpt", "edited")):
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(f"UPDATE company_exposures SET {field}=? WHERE exposure_id=?", (value, x))  # noqa: S608
    with pytest.raises(DatabaseError, match="cannot be replaced"):
        db.execute(_upsert_sql("REPLACE"), (x,))
    # 8. the expired assessment is not revived; the original evidence is unchanged
    assert eff() == "needs_revalidation"
    assert _record(db, x) == original
    # 9. retraction through the supported mechanism (Phase 4 downgrades the candidate)
    retract_evidence(db, "company_exposures", x, reason="SYNTHETIC: expired, replaced", retracted_by="owner")
    assert db.execute("SELECT evidence_status s FROM exposure_candidates WHERE candidate_id=?",
                      (cand,))[0]["s"] == "unverified"
    assert eff() == "needs_revalidation"
    # the old candidate cannot be restored on the same event: its retracted link is permanent (Phase 4)
    _exposure(db, "cmp-syn-alpha", valid_to="2099-12-31")
    with pytest.raises(DatabaseError, match="currently valid"):
        map_event(db, eid, synthetic=True)
    # 10. a NEW exposure record (just added) and a new event report produce a new candidate and revision
    eid2 = _event(db, headline="Brent crude oil price rises again", date=clock.today())
    map_event(db, eid2, synthetic=True)
    cand2 = db.execute("SELECT candidate_id, current_revision r FROM exposure_candidates WHERE event_id=? "
                       "AND company_id='cmp-syn-alpha' AND exposure_level='direct'", (eid2,))[0]
    assert cand2["candidate_id"] != cand and cand2["r"] >= 2
    x2 = db.execute("SELECT company_exposure_id x FROM exposure_candidate_evidence WHERE candidate_id=? "
                    "AND role='company_specific'", (cand2["candidate_id"],))[0]["x"]
    assert x2 != x
    # 11. new human review of the candidate and of the new assessment before eligibility returns
    review(db, cand2["candidate_id"], "accept", reviewer="owner", notes="SYNTHETIC revalidation")
    aid2 = _assess(db, eid2, "cmp-syn-alpha")
    _link_candidate(db, aid2, cand2["candidate_id"])
    _update(db, aid2, assessment_status="provisional", status_reason="created_eligible")
    rid2 = _review(db, aid2, "accept")
    _update(db, aid2, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=rid2, **HUMAN)
    # 12. the new evidence supports a new eligible assessment; the old one stays invalidated
    assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid2,))[0]["s"] == "confirmed_conclusion"
    assert eff() == "needs_revalidation"
    assert _record(db, x) == original
