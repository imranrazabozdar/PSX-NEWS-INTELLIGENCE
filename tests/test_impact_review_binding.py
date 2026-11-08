"""Regression tests for the PR #21 targeted-verification findings (migration 0009, SYNTHETIC data only).

- HIGH: review replay. Every human review is single-use and bound to one transition.
- MEDIUM: `valid_to` must be a real calendar date to establish explicit freshness.
- LOW: direction changes need a new human review (the move to 'unknown' is exempt).
"""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines.exposure_mapping import map_event
from tests.test_impact_assessments import (
    _assess,
    _base,
    _candidate,
    _event,
    _exposure,
    _link_candidate,
    _provisional,
    _review,
    _update,
)

HUMAN = {"actor_type": "human", "changed_by": "human:owner"}


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    yield d
    d.close()


def _snap(db, aid):
    a = db.execute("SELECT assessment_status, status_reason, direction, current_revision, last_review_id "
                   "FROM impact_assessments WHERE assessment_id=?", (aid,))[0]
    revs = db.execute("SELECT COUNT(*) n FROM impact_assessment_revisions WHERE assessment_id=?",
                      (aid,))[0]["n"]
    reviews = db.execute("SELECT COUNT(*) n FROM impact_reviews WHERE assessment_id=?", (aid,))[0]["n"]
    return dict(a), revs, reviews


def _refused(db, aid, match, **kw):
    before = _snap(db, aid)
    with pytest.raises(DatabaseError, match=match):
        _update(db, aid, **kw)
    assert _snap(db, aid) == before   # status, revisions and review history unchanged


# ------------------------------------------------------------------ HIGH: review replay
def test_old_accept_review_cannot_reinstate_again(db):
    _, _, aid = _provisional(db)
    _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="evidence_revoked")
    r1 = _review(db, aid, "accept")
    _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=r1, **HUMAN)
    _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="evidence_retracted")
    r2 = _review(db, aid, "accept")
    _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=r2, **HUMAN)
    _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="source_restricted")
    _refused(db, aid, "already used", assessment_status="provisional", status_reason="reinstated",
             last_review_id=r1, **HUMAN)


def test_old_reject_review_cannot_reject_again(db):
    _, _, aid = _provisional(db)
    rj = _review(db, aid, "reject")
    _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
            last_review_id=rj, **HUMAN)
    ra = _review(db, aid, "accept")
    _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=ra, **HUMAN)
    _refused(db, aid, "already used|stale", assessment_status="rejected_by_review",
             status_reason="reviewer_rejected", last_review_id=rj, **HUMAN)


@pytest.mark.parametrize("decision,target,reason", [
    ("needs_more_evidence", "needs_review", "reviewer_needs_more_evidence"),
    ("request_revalidation", "needs_revalidation", "reviewer_requested_revalidation"),
])
def test_replay_on_other_paths(db, decision, target, reason):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, decision)
    _update(db, aid, assessment_status=target, status_reason=reason, last_review_id=rid, **HUMAN)
    _update(db, aid, assessment_status="provisional", status_reason="revalidated")
    other = _review(db, aid, "needs_more_evidence")   # a later review is linked by a later transition
    _update(db, aid, assessment_status="needs_review", status_reason="reviewer_needs_more_evidence",
            last_review_id=other, **HUMAN)
    _update(db, aid, assessment_status="provisional", status_reason="revalidated")
    # the first review still matches the current status (provisional) but is consumed: replay refused
    _refused(db, aid, "already used|stale", assessment_status=target, status_reason=reason,
             last_review_id=rid, **HUMAN)


def test_stale_unused_review_cannot_authorise(db):
    _, _, aid = _provisional(db)
    old = _review(db, aid, "reject")
    _review(db, aid, "needs_more_evidence")
    _refused(db, aid, "stale", assessment_status="rejected_by_review", status_reason="reviewer_rejected",
             last_review_id=old, **HUMAN)


def test_confirmation_review_cannot_be_reused(db):
    _, _, aid = _provisional(db)
    r = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=r, **HUMAN)
    _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="evidence_revoked")
    _refused(db, aid, "human accept review|already used|matching new review",
             assessment_status="provisional", status_reason="reinstated", last_review_id=r, **HUMAN)


def test_review_cannot_be_linked_by_system_or_removed(db):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, "request_revalidation")
    _refused(db, aid, "human decision", assessment_status="needs_revalidation",
             status_reason="evidence_revoked", last_review_id=rid)
    _update(db, aid, assessment_status="needs_revalidation", status_reason="reviewer_requested_revalidation",
            last_review_id=rid, **HUMAN)
    _refused(db, aid, "cannot be removed", assessment_status="provisional", status_reason="revalidated",
             last_review_id=None)


def test_unique_index_enforces_single_use(db):
    idx = db.execute("SELECT sql FROM sqlite_master WHERE name='ux_impact_revisions_review_once'")
    assert idx and "UNIQUE" in idx[0]["sql"] and "review_id IS NOT NULL" in idx[0]["sql"]


# ------------------------------------------------------------------ MEDIUM: real calendar dates
@pytest.mark.parametrize("valid_to,ok", [
    ("2099-12-31", True),
    ("2099-12-31T00:00:00Z", True),
    ("2028-02-29", True),        # leap day
    ("2027-02-29", False),       # not a leap year
    ("2099-02-30", False),
    ("2099-04-31", False),
    ("9999-99-99", False),
    ("2099-13-01", False),
    ("2099-00-10", False),
    ("2001-01-01", False),       # expired by the database clock
    (None, False),               # missing
])
def test_valid_to_must_be_real_unexpired_date(db, valid_to, ok):
    _exposure(db, "cmp-syn-alpha", valid_to=valid_to)
    eid = _event(db)
    if valid_to == "2001-01-01":
        # Phase 4 already ignores the expired exposure, so no candidate exists that could qualify
        map_event(db, eid, synthetic=True)
        assert not db.execute("SELECT 1 FROM exposure_candidates WHERE event_id=? AND company_id=? "
                              "AND exposure_level='direct'", (eid, "cmp-syn-alpha"))
        return
    cand = _candidate(db, eid, "cmp-syn-alpha", confirm=True)
    aid = _assess(db, eid, "cmp-syn-alpha")
    _link_candidate(db, aid, cand)
    if ok:
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
        assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                          (aid,))[0]["s"] == "provisional"
    else:
        _refused(db, aid, "explicit source expiry not verified", assessment_status="provisional",
                 status_reason="created_eligible")


# ------------------------------------------------------------------ LOW: direction changes
def test_system_cannot_change_direction(db):
    _, _, aid = _provisional(db)
    _refused(db, aid, "direction can only change", assessment_status="provisional",
             status_reason="revalidated", direction="positive")
    _refused(db, aid, "direction can only change", assessment_status="needs_revalidation",
             status_reason="evidence_revoked", direction="mixed")


def test_direction_to_unknown_is_allowed_conservatively(db):
    _, _, aid = _provisional(db)
    _update(db, aid, assessment_status="provisional", status_reason="revalidated", direction="unknown")


def test_human_without_new_review_cannot_change_direction(db):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, "request_revalidation")
    _update(db, aid, assessment_status="needs_revalidation", status_reason="reviewer_requested_revalidation",
            last_review_id=rid, **HUMAN)
    _refused(db, aid, "direction can only change", assessment_status="needs_revalidation",
             status_reason="evidence_revoked", direction="positive", **HUMAN)


def test_direction_change_with_new_human_review(db):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, "request_revalidation")
    _update(db, aid, assessment_status="needs_revalidation", status_reason="reviewer_requested_revalidation",
            last_review_id=rid, direction="positive", **HUMAN)
    assert _snap(db, aid)[0]["direction"] == "positive"
