"""Regression tests for the independent audit findings on PR #21 (migration 0009).

SYNTHETIC FIXTURES ONLY (fictional cmp-syn-* companies, `syn` sources), throwaway local SQLite.
"""

from __future__ import annotations

import json

import pytest

from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines.exposure_mapping import map_event, review
from tests.test_impact_assessments import (
    NOW,
    _approve,
    _assess,
    _base,
    _candidate,
    _confirm,
    _event,
    _exposure,
    _link_candidate,
    _policy,
    _provisional,
    _retire,
    _review,
    _status,
    _update,
)


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    yield d
    d.close()


def _row(db, table, where, args):
    return db.execute(f"SELECT * FROM {table} WHERE {where}", args)[0]  # noqa: S608 - test-only constants


def _count(db, table):
    return db.execute(f"SELECT COUNT(*) n FROM {table}")[0]["n"]  # noqa: S608 - test-only constants


def _replace(db, verb, table, row, change):
    vals = dict(row, **change)
    cols = list(vals)
    db.execute(f"{verb} INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",  # noqa: S608
               [vals[c] for c in cols])


# ------------------------------------------------------------------ BLOCKER 1: REPLACE bypass
def _populated(db):
    eid, cand, aid = _provisional(db)
    db.execute("INSERT INTO impact_transmission_steps VALUES (?,2,1,'brent','input "
               "cost',-1,'short','x')", (aid,))
    db.execute("INSERT INTO impact_scenarios VALUES (?,2,'base','negative','medium','{}')", (aid,))
    _review(db, aid, "needs_more_evidence")
    _policy(db, "test/1")
    _approve(db, "test/1", "2026-01-01T00:00:00Z")
    return aid


TABLES = [
    ("impact_expiry_policy_versions", "policy_version='test/1'", (), {"rationale": "FORGED"}, None),
    ("impact_expiry_policy_events", "policy_version='test/1'", (),
     {"effective_from_utc": "2020-01-01T00:00:00Z"},
     {"policy_event_id": 999}),                                             # unique (version, event_type)
    ("impact_assessments", "assessment_id=?", "aid", {"direction": "positive"},
     {"assessment_id": 999}),                                               # unique identity key
    ("impact_reviews", "1=1", (), {"notes": "FORGED"}, None),
    ("impact_assessment_inputs", "1=1", (), {"added_at_utc": "2000-01-01T00:00:00Z"}, None),
    ("impact_assessment_revisions", "assessment_id=? AND revision_no=2", "aid",
     {"new_status": "confirmed_conclusion"},
     None),
    ("impact_transmission_steps", "1=1", (), {"explanation": "FORGED"}, None),
    ("impact_scenarios", "1=1", (), {"assumptions_json": '{"forged": true}'}, None),
]


@pytest.mark.parametrize("table,where,args,change,unique_variant", TABLES, ids=[t[0] for t in TABLES])
@pytest.mark.parametrize("verb", ["INSERT OR REPLACE", "REPLACE"])
def test_replace_cannot_overwrite_existing_rows(db, table, where, args, change, unique_variant, verb):
    aid = _populated(db)
    a = (aid,) if args == "aid" else args
    original = _row(db, table, where, a)
    revisions_before = _count(db, "impact_assessment_revisions")
    with pytest.raises(DatabaseError, match="duplicate key"):          # duplicate primary key
        _replace(db, verb, table, original, change)
    if unique_variant:
        with pytest.raises(DatabaseError, match="duplicate key"):      # duplicate unique key, new PK
            _replace(db, verb, table, original, dict(change, **unique_variant))
    assert _row(db, table, where, a) == original
    assert _count(db, "impact_assessment_revisions") == revisions_before


def test_normal_first_inserts_still_work(db):
    _populated(db)
    _policy(db, "test/2")
    assert _count(db, "impact_expiry_policy_versions") == 2


# ------------------------------------------------------------------ BLOCKER 2: policy/freshness on UPDATE
def test_policy_and_freshness_cannot_change_on_update(db):
    eid = _event(db)
    aid = _assess(db, eid, "cmp-syn-alpha", freshness="not_established")
    _policy(db, "draft/1")
    _policy(db, "retired/1")
    _approve(db, "retired/1", "2026-01-01T00:00:00Z")
    _retire(db, "retired/1", "2026-02-01T00:00:00Z")
    before = _status(db, aid)
    for version in ("draft/1", "retired/1"):
        with pytest.raises(DatabaseError, match="fixed at creation"):
            _update(db, aid, expiry_policy_version=version, freshness_basis="policy_expiry")
        with pytest.raises(DatabaseError, match="fixed at creation"):   # combined with an upgrade
            _update(db, aid, expiry_policy_version=version, freshness_basis="policy_expiry",
                    assessment_status="provisional", status_reason="created_eligible")
    with pytest.raises(DatabaseError, match="fixed at creation"):
        _update(db, aid, freshness_basis="explicit_source_expiry")
    assert _status(db, aid) == before


# ------------------------------------------------------------------ HIGH 1: full transition matrix
STATES = ["scenario_only", "needs_review", "provisional", "needs_revalidation", "confirmed_conclusion",
          "withdrawn_evidence_invalid", "rejected_by_review"]
ALLOWED = {
    "scenario_only": {"needs_review", "provisional", "needs_revalidation", "withdrawn_evidence_invalid",
                      "rejected_by_review"},
    "needs_review": {"scenario_only", "provisional", "needs_revalidation", "withdrawn_evidence_invalid",
                     "rejected_by_review"},
    "provisional": {"scenario_only", "needs_review", "needs_revalidation", "confirmed_conclusion",
                    "withdrawn_evidence_invalid", "rejected_by_review"},
    "needs_revalidation": {"scenario_only", "needs_review", "provisional", "withdrawn_evidence_invalid",
                           "rejected_by_review"},
    "confirmed_conclusion": {"needs_revalidation", "withdrawn_evidence_invalid", "rejected_by_review"},
    "withdrawn_evidence_invalid": {"provisional"},
    "rejected_by_review": {"provisional"},
}


def _in_state(db, state):
    eid, cand, aid = _provisional(db)
    if state == "scenario_only":
        _update(db, aid, assessment_status="scenario_only", status_reason="revalidated")
    elif state == "needs_review":
        rid = _review(db, aid, "needs_more_evidence")
        _update(db, aid, assessment_status="needs_review", status_reason="reviewer_needs_more_evidence",
                actor_type="human", changed_by="human:owner", last_review_id=rid)
    elif state == "needs_revalidation":
        _update(db, aid, assessment_status="needs_revalidation", status_reason="evidence_revoked")
    elif state == "confirmed_conclusion":
        _confirm(db, aid)
    elif state == "withdrawn_evidence_invalid":
        _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="evidence_revoked")
    elif state == "rejected_by_review":
        rid = _review(db, aid, "reject")
        _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
                actor_type="human", changed_by="human:owner", last_review_id=rid)
    assert _status(db, aid)["assessment_status"] == state
    return aid


def _attempt(db, aid, frm, target):
    """Best legitimate attempt to reach target; returns True if the database accepted it."""
    human = {"actor_type": "human", "changed_by": "human:owner"}
    try:
        if target == "scenario_only":
            _update(db, aid, assessment_status=target, status_reason="revalidated")
        elif target == "needs_review":
            rid = _review(db, aid, "needs_more_evidence")
            _update(db, aid, assessment_status=target, status_reason="reviewer_needs_more_evidence",
                    last_review_id=rid, **human)
        elif target == "provisional":
            if frm in ("withdrawn_evidence_invalid", "rejected_by_review", "confirmed_conclusion"):
                rid = _review(db, aid, "accept")
                _update(db, aid, assessment_status=target, status_reason="reinstated", last_review_id=rid,
                        **human)
            else:
                _update(db, aid, assessment_status=target, status_reason="revalidated")
        elif target in ("needs_revalidation", "withdrawn_evidence_invalid"):
            _update(db, aid, assessment_status=target, status_reason="evidence_revoked")
        elif target == "confirmed_conclusion":
            rid = _review(db, aid, "accept")
            _update(db, aid, assessment_status=target, status_reason="reviewer_accepted", last_review_id=rid,
                    **human)
        elif target == "rejected_by_review":
            rid = _review(db, aid, "reject")
            _update(db, aid, assessment_status=target, status_reason="reviewer_rejected", last_review_id=rid,
                    **human)
        return True
    except DatabaseError:
        return False


@pytest.mark.parametrize("frm", STATES)
@pytest.mark.parametrize("target", STATES)
def test_transition_matrix(db, frm, target):
    if frm == target:
        pytest.skip("self-transition")
    aid = _in_state(db, frm)
    before = _status(db, aid)
    ok = _attempt(db, aid, frm, target)
    assert ok == (target in ALLOWED[frm]), f"{frm} -> {target}: {'allowed' if ok else 'refused'}"
    if not ok:
        assert _status(db, aid)["current_revision"] == before["current_revision"]


@pytest.mark.parametrize("terminal", ["withdrawn_evidence_invalid", "rejected_by_review"])
def test_terminal_reinstatement_bypass_attempts(db, terminal):
    aid = _in_state(db, terminal)
    human = {"actor_type": "human", "changed_by": "human:owner"}
    rid = _review(db, aid, "needs_more_evidence")   # needs_more_evidence cannot authorise reinstatement
    with pytest.raises(DatabaseError):
        _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=rid,
                **human)
    for target, reason in (("scenario_only", "revalidated"),
                           ("needs_review", "reviewer_needs_more_evidence")):
        with pytest.raises(DatabaseError):
            _update(db, aid, assessment_status=target, status_reason=reason, last_review_id=rid, **human)
    other = _in_state(db, "provisional")                     # an accept review of another assessment
    foreign = _review(db, other, "accept")
    with pytest.raises(DatabaseError):
        _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=foreign,
                **human)
    accept = _review(db, aid, "accept")
    with pytest.raises(DatabaseError):                       # system actor cannot reinstate
        _update(db, aid, assessment_status="provisional", status_reason="reinstated", last_review_id=accept)
    with pytest.raises(DatabaseError):                       # wrong reason with a valid accept review
        _update(db, aid, assessment_status="provisional", status_reason="revalidated", last_review_id=accept,
                **human)
    other_terminal = ("rejected_by_review" if terminal == "withdrawn_evidence_invalid"
                      else "withdrawn_evidence_invalid")
    rej = _review(db, aid, "reject")
    with pytest.raises(DatabaseError):                       # terminal -> other terminal
        if other_terminal == "rejected_by_review":
            _update(db, aid, assessment_status=other_terminal, status_reason="reviewer_rejected",
                    last_review_id=rej, **human)
        else:
            _update(db, aid, assessment_status=other_terminal, status_reason="evidence_revoked",
                    last_review_id=rej)
    assert _status(db, aid)["assessment_status"] == terminal


# ------------------------------------------------------------------ HIGH 2: provisional inputs all eligible
def _setup_mixed(db):
    """One event; company alpha gets candidates of several evidence statuses (all SYNTHETIC).

    strong1/strong2: approved same-direction oil exposures; unverified: an exposure from an unapproved
    source; potential: a parent link through a relationship whose evidence status is 'potential'.
    """
    from engines.exposure_mapping import record_relationship
    _exposure(db, "cmp-syn-alpha", "crude oil")
    _exposure(db, "cmp-syn-alpha", "furnace oil fuel")
    _exposure(db, "cmp-syn-alpha", "diesel", source="synreal")
    db.execute("UPDATE company_exposures SET exposure_kind='energy' WHERE subject IN ('furnace oil "
               "fuel','diesel')")
    _exposure(db, "cmp-syn-beta", "crude oil")
    sid = db.execute("SELECT source_item_id FROM company_exposures WHERE company_id='cmp-syn-beta'")[0]
    record_relationship(db, parent_company_id="cmp-syn-alpha", child_company_id="cmp-syn-beta",
                        child_name="Synthetic Beta Ltd", relationship_type="subsidiary",
                        evidence_status="potential",
                        recorded_by="test", change_reason="SYNTHETIC FIXTURE", is_synthetic=True,
                        source_item_id=sid["source_item_id"], evidence_excerpt="SYNTHETIC FIXTURE")
    eid = _event(db)
    map_event(db, eid, synthetic=True)
    rows = db.execute("SELECT candidate_id, evidence_status, mechanism, rule_id FROM exposure_candidates "
                      "WHERE event_id=? AND company_id='cmp-syn-alpha'", (eid,))
    c = {}
    for r in rows:
        key = ("potential" if r["rule_id"] == "R-REL-1" else "strong1" if "crude oil" in r["mechanism"]
               else "strong2" if "furnace" in r["mechanism"] else "unverified" if "diesel" in r["mechanism"]
               else None)
        if key:
            c[key] = (r["candidate_id"], r["evidence_status"])
    return eid, c


def test_mixed_fixture_statuses(db):
    eid, c = _setup_mixed(db)
    assert c["strong1"][1] == "strongly_supported" and c["strong2"][1] == "strongly_supported"
    assert c["potential"][1] == "potential"
    assert c["unverified"][1] == "unverified"


def _prov_with(db, eid, cands):
    aid = _assess(db, eid, "cmp-syn-alpha")
    for cand in cands:
        _link_candidate(db, aid, cand)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    return aid


@pytest.mark.parametrize("combo,ok", [
    (("strong1",), True),
    (("confirmed",), True),
    (("strong1", "confirmed"), True),
    (("strong1", "potential"), False),
    (("strong1", "unverified"), False),
    (("potential",), False),
    (("unverified",), False),
])
def test_provisional_requires_every_exposure_input_eligible(db, combo, ok):
    eid, c = _setup_mixed(db)
    ids = {k: v[0] for k, v in c.items()}
    if "confirmed" in combo:
        review(db, ids["strong2"], "accept", reviewer="owner", notes="SYNTHETIC check")
        ids["confirmed"] = ids["strong2"]
    if ok:
        aid = _prov_with(db, eid, [ids[k] for k in combo])
        assert _status(db, aid)["effective_status"] == "provisional"
    else:
        with pytest.raises(DatabaseError):
            _prov_with(db, eid, [ids[k] for k in combo])


def test_ineligible_input_after_upgrade_and_status_change_detected(db):
    eid, c = _setup_mixed(db)
    aid = _prov_with(db, eid, [c["strong1"][0]])
    with pytest.raises(DatabaseError, match="strongly supported or confirmed"):
        _link_candidate(db, aid, c["potential"][0])
    # the linked exposure loses strength after attachment: event becomes single-source, Phase 4 re-run
    from database import repositories as repo
    repo.revise_event(db, eid, {"verification_state": "single_source"}, reason="SYNTHETIC", changed_by="test")
    map_event(db, eid, synthetic=True)
    st = _status(db, aid)
    assert st["assessment_status"] == "provisional" and st["effective_status"] == "needs_revalidation"


# ------------------------------------------------------------------ HIGH 4: freshness verified by database
def test_unsupported_or_expired_explicit_freshness_cannot_qualify(db):
    for valid_to, label in ((None, "no valid_to"), ("2026-11-06", "expired before now")):
        _exposure(db, "cmp-syn-beta", f"crude oil {label}", valid_to=valid_to)
    eid = _event(db)
    map_event(db, eid, synthetic=True)
    cands = [r["candidate_id"] for r in db.execute(
        "SELECT candidate_id FROM exposure_candidates WHERE event_id=? AND company_id='cmp-syn-beta' "
        "AND exposure_level='direct'", (eid,))]
    assert len(cands) == 2
    for cand in cands:
        aid = _assess(db, eid, "cmp-syn-beta", mechanism=f"T{cands.index(cand) + 2}")
        _link_candidate(db, aid, cand)
        with pytest.raises(DatabaseError, match="explicit source expiry not verified"):
            _update(db, aid, assessment_status="provisional", status_reason="created_eligible")


def test_policy_based_freshness_cannot_unlock_provisional(db):
    _policy(db, "test/1")
    _approve(db, "test/1", "2026-01-01T00:00:00Z")
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db)
    cand = _candidate(db, eid, "cmp-syn-alpha")
    rev = db.execute("SELECT current_revision r FROM events WHERE event_id=?", (eid,))[0]["r"]
    db.execute("INSERT INTO impact_assessments SELECT NULL, ?, ?, 'cmp-syn-alpha', 'T1', 't', 'r', "
               "NULL, 'current', "
               "'needs_review', 'created_needs_review', 'negative', 'low', 'qualitative', 'short', "
               "'low', 'low', "
               "'low', 'low', 'undetermined', '{}', '[]', '[]', '[]', NULL, 'not_evaluable', NULL, 'test/1', "
               "'policy_expiry', 1, 1, NULL, 'c', 'system:test', 'system', ?, ?", (eid, rev, NOW, NOW))
    aid = db.execute("SELECT MAX(assessment_id) i FROM impact_assessments")[0]["i"]
    _link_candidate(db, aid, cand)
    with pytest.raises(DatabaseError, match="not yet database-verifiable"):
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")


# ------------------------------------------------------------------ MEDIUM 3: policy windows use db time
def _insert_with_policy(db, eid, version, created):
    rev = db.execute("SELECT current_revision r FROM events WHERE event_id=?", (eid,))[0]["r"]
    db.execute("INSERT INTO impact_assessments SELECT NULL, ?, ?, 'cmp-syn-alpha', 'T1', ?, 'r', "
               "NULL, 'current', "
               "'needs_review', 'created_needs_review', 'unknown', 'low', 'qualitative', 'short', "
               "'low', 'low', "
               "'low', 'low', 'undetermined', '{}', '[]', '[]', '[]', NULL, 'not_evaluable', NULL, ?, "
               "'policy_expiry', 1, 1, NULL, 'c', 'system:test', 'system', ?, ?",
               (eid, rev, f"t/{version}/{created}", version, created, created))


@pytest.mark.parametrize("window,created,ok", [
    (("2026-01-01T00:00:00Z", None), "2026-11-08T00:00:00Z", True),          # current window
    (("2026-01-01T00:00:00Z", None), "2099-01-01T00:00:00Z", True),          # future-dated created_at ignored
    (("2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"), "2026-03-01T00:00:00Z", False),   # backdated
    (("2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"), "2026-11-08T00:00:00Z", False),   # retired window
    (("2099-01-01T00:00:00Z", None), "2099-06-01T00:00:00Z", False),          # not yet effective
])
def test_policy_selection_uses_database_time(db, window, created, ok):
    eid = _event(db)
    _policy(db, "p/1")
    _approve(db, "p/1", window[0])
    if window[1]:
        _retire(db, "p/1", window[1])
    if ok:
        _insert_with_policy(db, eid, "p/1", created)
    else:
        with pytest.raises(DatabaseError, match="expiry policy"):
            _insert_with_policy(db, eid, "p/1", created)


# ------------------------------------------------------------------ MEDIUM 1: sector weakest status
def _two_company_sector(db):
    for c in ("cmp-syn-gamma", "cmp-syn-delta"):
        db.execute("UPDATE company_classifications SET valid_to='2010-01-01' WHERE company_id=?", (c,))
    for c in ("cmp-syn-alpha", "cmp-syn-beta"):
        _exposure(db, c)
    eid = _event(db)
    map_event(db, eid, synthetic=True)
    cands = {r["company_id"]: r["candidate_id"] for r in db.execute(
        "SELECT company_id, candidate_id FROM exposure_candidates WHERE event_id=? AND rule_id='R-OIL-1' "
        "AND exposure_level='direct'", (eid,))}
    return eid, cands


def _company(db, eid, cand, company, kind):
    if kind == "confirmed":   # confirm the exposure first, so the link records its current revision
        review(db, cand, "accept", reviewer="owner", notes="SYNTHETIC check")
    aid = _assess(db, eid, company, status="scenario_only", reason="created_scenario")
    _link_candidate(db, aid, cand)
    if kind in ("provisional", "confirmed"):
        _update(db, aid, assessment_status="provisional", status_reason="revalidated")
        if kind == "confirmed":
            _confirm(db, aid)
    return aid


def _sector_row(db, eid):
    return db.execute("SELECT * FROM impact_sector_aggregates_current WHERE event_id=?", (eid,))[0]


@pytest.mark.parametrize("kinds,weakest,conclusion", [
    (("scenario", "scenario"), "scenario_only", "not_concluded_scenario_only_components"),
    (("scenario", "provisional"), "scenario_only", "not_concluded_scenario_only_components"),
    (("scenario", "confirmed"), "scenario_only", "not_concluded_scenario_only_components"),
    (("provisional", "provisional"), "provisional", "negative"),
    (("confirmed", "confirmed"), "confirmed_conclusion", "negative"),
])
def test_sector_weakest_status(db, kinds, weakest, conclusion):
    eid, cands = _two_company_sector(db)
    for company, kind in zip(("cmp-syn-alpha", "cmp-syn-beta"), kinds, strict=True):
        _company(db, eid, cands[company], company, kind)
    s = _sector_row(db, eid)
    assert s["completeness"] == "complete" and s["weakest_status"] == weakest
    assert s["sector_conclusion"] == conclusion
    assert s["scenario_only_n"] == kinds.count("scenario")
    assert s["evidence_backed_n"] == 2 - kinds.count("scenario")


def test_sector_partial_coverage_still_wins(db):
    eid, cand, aid = _provisional(db)      # gamma (unknown), delta (suspended), beta (unassessed) present
    s = _sector_row(db, eid)
    assert s["completeness"] == "partial" and s["sector_conclusion"] == "not_concluded_partial_coverage"
    reasons = {e["company_id"]: e["reason"] for e in json.loads(s["excluded_json"])}
    assert reasons["cmp-syn-beta"] == "no_assessment"
    assert reasons["cmp-syn-gamma"] == "listing_status_unknown"
    assert reasons["cmp-syn-delta"] == "suspended_at_event_date"
