"""Regression tests for the PR #21 (950f7be) targeted-verification findings (migration 0009, SYNTHETIC data).

- HIGH: every linked company-specific exposure record must be fresh. One fresh record never compensates.
- MEDIUM: substantive assessment fields change only with a new human review. The exemption is a single
  move towards caution.
"""

from __future__ import annotations

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines.exposure_mapping import map_event, review
from tests.test_impact_assessments import (
    _assess,
    _base,
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


def _eff(db, aid):
    return db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"]


def _snap(db, aid):
    a = dict(db.execute("SELECT * FROM impact_assessments WHERE assessment_id=?", (aid,))[0])
    n = db.execute("SELECT COUNT(*) n FROM impact_assessment_revisions WHERE assessment_id=?", (aid,))[0]["n"]
    return a, n


def _two_records(db):
    """An assessment linked to two confirmed candidates, each backed by its own exposure record."""
    _exposure(db, "cmp-syn-alpha", subject="crude oil")
    _exposure(db, "cmp-syn-alpha", subject="furnace oil")
    eid = _event(db, headline="Brent crude oil and furnace oil prices rise")
    map_event(db, eid, synthetic=True)
    cands = [r["candidate_id"] for r in db.execute(
        "SELECT candidate_id FROM exposure_candidates WHERE event_id=? AND company_id='cmp-syn-alpha' "
        "AND exposure_level='direct'", (eid,))]
    for c in cands:
        review(db, c, "accept", reviewer="owner", notes="SYNTHETIC check")
    aid = _assess(db, eid, "cmp-syn-alpha")
    for c in cands:
        _link_candidate(db, aid, c)
    xs = [r["exposure_id"] for r in db.execute(
        "SELECT DISTINCT exposure_id FROM impact_linked_exposure_freshness WHERE assessment_id=? "
        "ORDER BY exposure_id", (aid,))]
    assert len(xs) == 2
    return aid, xs


def _set_valid_to(db, exposure_id, value):
    db.execute("UPDATE company_exposures SET valid_to=? WHERE exposure_id=?", (value, exposure_id))


# ------------------------------------------------------------------ HIGH: every linked record must be fresh
@pytest.mark.parametrize("second,ok", [
    ("2099-12-31", True),              # all valid
    ("2099-12-31T00:00:00Z", True),    # all valid (timestamp form)
    ("2001-01-01", False),             # one expired
    (None, False),                     # one missing
    ("2099-02-30", False),             # one impossible date
    ("9999-99-99", False),             # one impossible date
    ("2099-12-31garbage", False),      # one malformed
    ("31/12/2099", False),             # one malformed
    ("", False),                       # one malformed (empty)
])
def test_every_linked_record_must_be_fresh(db, second, ok):
    aid, xs = _two_records(db)
    _set_valid_to(db, xs[1], second)
    fresh = bool(db.execute("SELECT 1 FROM impact_explicit_freshness WHERE assessment_id=?", (aid,)))
    assert fresh is ok
    if ok:
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
        assert _eff(db, aid) == "provisional"
    else:
        before = _snap(db, aid)
        with pytest.raises(DatabaseError, match="explicit source expiry not verified"):
            _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
        assert _snap(db, aid) == before


@pytest.mark.parametrize("change", ["2001-01-01", None, "2099-02-30", "not-a-date"])
def test_read_time_invalidation_when_a_record_lapses_or_changes(db, change):
    aid, xs = _two_records(db)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    assert _eff(db, aid) == "provisional"
    _set_valid_to(db, xs[1], change)        # the second record expires or its validity is altered
    assert _eff(db, aid) == "needs_revalidation"
    _set_valid_to(db, xs[1], "2099-12-31")  # a correction restores freshness at read time
    assert _eff(db, aid) == "provisional"


def test_single_record_lapse_invalidates_confirmed(db):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=rid, **HUMAN)
    x = db.execute("SELECT exposure_id FROM impact_linked_exposure_freshness WHERE assessment_id=?",
                   (aid,))[0]["exposure_id"]
    _set_valid_to(db, x, "2001-01-01")
    assert _eff(db, aid) == "needs_revalidation"


# ------------------------------------------------------------------ MEDIUM: substantive fields
# Every fixture assessment starts with: direction negative, magnitude medium, horizon medium, confidences
# medium/medium/medium/low, scenario_uncertainty wide, affected_lines [] (see tests/test_impact_assessments).
CAUTIOUS = [
    {"direction": "unknown"},
    {"horizon": "unknown"},
    {"magnitude_level": "not_assessable"},
    {"evidence_confidence": "low"},
    {"exposure_confidence": "low"},
    {"direction_confidence": "low"},
    {"scenario_uncertainty": "undetermined"},
]
NON_CAUTIOUS = [
    {"direction": "positive"},
    {"horizon": "long"},
    {"horizon": "short"},
    {"magnitude_level": "high"},
    {"magnitude_level": "low"},
    {"evidence_confidence": "high"},
    {"exposure_confidence": "high"},
    {"direction_confidence": "high"},
    {"magnitude_confidence": "medium"},
    {"scenario_uncertainty": "narrow"},
    {"affected_lines_json": '["fuel"]'},
    {"magnitude_basis": "deterministic_model"},
]


def _sys_update(db, aid, **fields):
    _update(db, aid, assessment_status="provisional", status_reason="revalidated", **fields)


@pytest.mark.parametrize("fields", CAUTIOUS, ids=lambda f: "-".join(f"{k}={v}" for k, v in f.items()))
def test_single_cautious_move_allowed_without_review(db, fields):
    _, _, aid = _provisional(db)
    _sys_update(db, aid, **fields)
    row = _snap(db, aid)[0]
    assert all(row[k] == v for k, v in fields.items())


@pytest.mark.parametrize("fields", NON_CAUTIOUS, ids=lambda f: "-".join(f"{k}={v}" for k, v in f.items()))
def test_non_cautious_change_refused_without_review(db, fields):
    _, _, aid = _provisional(db)
    before = _snap(db, aid)
    with pytest.raises(DatabaseError, match="substantive change requires a new human review"):
        _sys_update(db, aid, **fields)
    assert _snap(db, aid) == before


@pytest.mark.parametrize("extra", [c for c in CAUTIOUS + NON_CAUTIOUS if "direction" not in c],
                         ids=lambda f: "-".join(f"{k}={v}" for k, v in f.items()))
def test_direction_to_unknown_cannot_be_combined(db, extra):
    _, _, aid = _provisional(db)
    before = _snap(db, aid)
    with pytest.raises(DatabaseError, match="substantive change|only one substantive field"):
        _sys_update(db, aid, direction="unknown", **extra)
    assert _snap(db, aid) == before


def test_two_cautious_moves_refused_together(db):
    _, _, aid = _provisional(db)
    with pytest.raises(DatabaseError, match="only one substantive field"):
        _sys_update(db, aid, horizon="unknown", evidence_confidence="low")


def test_human_without_new_review_cannot_change_fields(db):
    _, _, aid = _provisional(db)
    with pytest.raises(DatabaseError, match="substantive change requires a new human review"):
        _update(db, aid, assessment_status="provisional", status_reason="revalidated", magnitude_level="high",
                **HUMAN)


def test_combined_changes_with_new_human_review(db):
    _, _, aid = _provisional(db)
    rid = _review(db, aid, "request_revalidation")
    _update(db, aid, assessment_status="needs_revalidation", status_reason="reviewer_requested_revalidation",
            last_review_id=rid, magnitude_level="high", evidence_confidence="high", horizon="long",
            affected_lines_json='["fuel"]', scenario_uncertainty="narrow", direction="positive", **HUMAN)
    row = _snap(db, aid)[0]
    assert (row["magnitude_level"], row["horizon"], row["direction"]) == ("high", "long", "positive")
