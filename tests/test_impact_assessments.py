"""Migration 0009 (Phase 5 impact-assessment schema) integrity tests.

SYNTHETIC FIXTURES ONLY: fictional companies (cmp-syn-*, tickers SYN*), `syn`-prefixed synthetic
sources, throwaway local SQLite databases. Nothing here is real company research, and nothing is
written to Turso. These tests exercise the schema; Phase 5 analysis logic is not implemented.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from database import repositories as repo
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import MIGRATIONS_DIR, discover, migrate
from engines.exposure_mapping import map_event, review

NOW = "2026-11-08T00:00:00Z"
SECTOR = "psx-syn-test-sector"


# ------------------------------------------------------------------ fixtures
def _base(db):
    db.execute("INSERT INTO sectors(sector_id, scheme, name, created_at_utc) VALUES (?,?,?,?)",
               (SECTOR, "PSX", "SYNTHETIC TEST SECTOR", NOW))
    db.execute("INSERT INTO sources(source_id, name, source_type, reliability_tier, access_status, "
               "terms_status, "
               "lifecycle_status, enabled, is_synthetic, created_at_utc, updated_at_utc) "
               "VALUES ('synapproved','SYNTHETIC approved','other','primary_official','verified_permitted',"
               "'approved','ACTIVE',1,1,?,?)", (NOW, NOW))
    db.execute("INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, "
               "updated_at_utc) "
               "VALUES ('synreal','non-synthetic test source','other',0,?,?)", (NOW, NOW))
    for cid, status in (("alpha", "listed"), ("beta", "listed"), ("gamma", "unknown"), ("delta", "listed"),
                        ("eps", "listed")):
        db.execute("INSERT INTO companies(company_id, legal_name, listing_status, created_at_utc, "
                   "updated_at_utc) "
                   "VALUES (?,?,?,?,?)", (f"cmp-syn-{cid}", f"Synthetic {cid.title()} Ltd", status, NOW, NOW))
        db.execute("INSERT INTO company_identifiers(company_id, id_type, value, verified_at_utc) "
                   "VALUES (?,?,?,?)", (f"cmp-syn-{cid}", "psx_ticker", f"SYN{cid.upper()}", NOW))
        if cid != "eps":   # eps stays unclassified
            db.execute("INSERT INTO company_classifications(company_id, sector_id, valid_from, "
                       "verified_at_utc) "
                       "VALUES (?,?,?,?)", (f"cmp-syn-{cid}", SECTOR, "2000-01-01", NOW))
    db.execute("INSERT INTO company_status_history(company_id, status, effective_date, "
               "date_precision, details, "
               "recorded_at_utc) VALUES "
               "('cmp-syn-delta','suspended','2026-01-01','exact','SYNTHETIC',?)", (NOW,))


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    yield d
    d.close()


_n = [0]


def _item(db, source, text):
    _n[0] += 1
    return repo.record_source_item(db, source_id=source, url=f"https://syn.example/{source}/{_n[0]}",
                                   content=text, excerpt=text, collected_at_utc=NOW,
                                   published_at_utc=NOW).source_item_id


def _exposure(db, company, subject="crude oil", source="synapproved", valid_to="2099-12-31"):
    text = f"SYNTHETIC FIXTURE: {company} input {subject}"
    sid = _item(db, source, text)
    db.execute("INSERT INTO company_exposures(company_id, exposure_kind, subject, confidence, "
               "source_item_id, evidence_excerpt, valid_to, last_verified_utc) VALUES (?,?,?,?,?,?,?,?)",
               (company, "input", subject, "documented", sid, text, valid_to, NOW))


def _event(db, headline="Brent crude oil price rises", verification="corroborated", stage="confirmed_fact",
           date="2026-11-05", source="synapproved", event_type="commodity_price"):
    sid = _item(db, source, f"SYNTHETIC FIXTURE. {headline}.")
    eid = repo.create_event(db, {"event_type": event_type, "headline": headline, "summary": headline,
                                 "status_stage": stage, "verification_state": verification,
                                 "magnitude": "medium", "confidence": 0.8, "event_date": date},
                            changed_by="test")
    repo.add_evidence(db, event_id=eid, source_item_id=sid, claim=headline, claim_type="news_report",
                      relation="supports", excerpt=f"SYNTHETIC FIXTURE. {headline}.", recorded_by="test")
    return eid


def _candidate(db, eid, company, confirm=False):
    map_event(db, eid, synthetic=True)
    row = db.execute("SELECT candidate_id, evidence_status FROM exposure_candidates WHERE event_id=? "
                     "AND company_id=? AND rule_id='R-OIL-1' AND exposure_level='direct'", (eid, company))[0]
    if confirm:
        review(db, row["candidate_id"], "accept", reviewer="owner", notes="SYNTHETIC check")
    return row["candidate_id"]


def _assess(db, eid, company, *, kind="current", status="needs_review", reason="created_needs_review",
            direction="negative", freshness="explicit_source_expiry", synthetic=1, mechanism="T1"):
    rev = db.execute("SELECT current_revision r FROM events WHERE event_id=?", (eid,))[0]["r"]
    db.execute(
        "INSERT INTO impact_assessments(event_id, event_revision_no, company_id, mechanism_id, "
        "transmission_version, ruleset_version, scenario_kind, assessment_status, status_reason, direction, "
        "magnitude_level, magnitude_basis, horizon, evidence_confidence, exposure_confidence, "
        "direction_confidence, magnitude_confidence, scenario_uncertainty, confidence_reasons_json, "
        "affected_lines_json, counter_evidence_json, missing_inputs_json, freshness_basis, is_synthetic, "
        "change_reason, changed_by, actor_type, created_at_utc, updated_at_utc) "
        "VALUES (?,?,?,?,'transmission/test','exposure-rules/1.0.0',?,?,?,?,'medium','qualitative','medium',"
        "'medium','medium','medium','low','wide','{}','[]','[]','[]',?,?,'created','system:test','system',?,?)",
        (eid, rev, company, mechanism, kind, status, reason, direction, freshness, synthetic, NOW, NOW))
    return db.execute("SELECT MAX(assessment_id) i FROM impact_assessments")[0]["i"]


def _link_candidate(db, aid, cand):
    r = db.execute("SELECT current_revision FROM exposure_candidates WHERE candidate_id=?", (cand,))[0]
    sid = db.execute("SELECT source_item_id FROM exposure_candidate_evidence WHERE candidate_id=? "
                     "AND role='company_specific' LIMIT 1", (cand,))[0]["source_item_id"]
    db.execute("INSERT INTO impact_assessment_inputs(assessment_id, input_kind, exposure_candidate_id, "
               "exposure_candidate_revision, source_item_id, added_at_utc) VALUES (?,?,?,?,?,?)",
               (aid, "exposure_candidate", cand, r["current_revision"], sid, NOW))


def _update(db, aid, **kw):
    cur = db.execute("SELECT current_revision FROM impact_assessments WHERE assessment_id=?", (aid,))[0]
    kw.setdefault("actor_type", "system")
    kw.setdefault("changed_by", "system:test")
    kw.setdefault("change_reason", "test")
    sets = ", ".join(f"{k}=?" for k in kw)
    db.execute(f"UPDATE impact_assessments SET {sets}, current_revision=?, updated_at_utc=? "  # noqa: S608
               "WHERE assessment_id=?", [*kw.values(), cur["current_revision"] + 1, NOW, aid])


def _review(db, aid, decision, reviewer="owner"):
    st = db.execute("SELECT assessment_status s FROM impact_assessments WHERE assessment_id=?",
                    (aid,))[0]["s"]
    db.execute("INSERT INTO impact_reviews(assessment_id, decision, reviewer, notes, decided_at_utc, "
               "status_at_decision) VALUES (?,?,?,?,?,?)", (aid, decision, reviewer, "SYNTHETIC "
                                                                                     "review", NOW, st))
    return db.execute("SELECT MAX(review_id) i FROM impact_reviews")[0]["i"]


def _provisional(db, company="cmp-syn-alpha", confirm_candidate=True):
    _exposure(db, company)
    eid = _event(db)
    cand = _candidate(db, eid, company, confirm=confirm_candidate)
    aid = _assess(db, eid, company)
    _link_candidate(db, aid, cand)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    return eid, cand, aid


def _confirm(db, aid):
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            actor_type="human", changed_by="human:owner", last_review_id=rid)


def _status(db, aid):
    return db.execute("SELECT * FROM impact_assessments_current WHERE assessment_id=?", (aid,))[0]


# ------------------------------------------------------------------ 1-4 migration and foreign keys
def test_fresh_migration_creates_all_objects():
    d = SQLiteDatabase()
    migrate(d)
    names = {r["name"] for r in d.execute("SELECT name FROM sqlite_master")}
    for obj in ("impact_assessments", "impact_assessment_inputs", "impact_assessment_revisions",
                "impact_transmission_steps", "impact_scenarios", "impact_reviews",
                "impact_expiry_policy_versions", "impact_expiry_policy_events", "impact_invalid_inputs",
                "impact_assessments_current", "impact_sector_aggregates_current",
                "impact_event_company_eligibility", "impact_unclassified_companies",
                "impact_expiry_policies_current", "impact_expiry_policy_overlaps",
                "trg_events_refutation_withdraws_assessments", "trg_analyses_no_delete",
                "trg_policy_events_validate"):
        assert obj in names, obj
    assert d.execute("SELECT MAX(version) v FROM schema_migrations")[0]["v"] == 9
    assert migrate(d) and all(line.startswith("skip") for line in migrate(d))


def test_upgrade_from_0008_to_0009_keeps_existing_data():
    tmp = Path(tempfile.mkdtemp())
    for p in MIGRATIONS_DIR.glob("000[1-8]*.sql"):
        shutil.copy(p, tmp)
    d = SQLiteDatabase()
    migrate(d, directory=tmp)
    _base(d)
    _exposure(d, "cmp-syn-alpha")
    eid = _event(d)
    map_event(d, eid, synthetic=True)
    before = d.execute("SELECT COUNT(*) n FROM exposure_candidates")[0]["n"]
    log = migrate(d)
    assert any("apply  0009" in line for line in log)
    assert d.execute("SELECT COUNT(*) n FROM exposure_candidates")[0]["n"] == before
    assert len(discover()) == 9


def test_foreign_keys_reject_invalid_references(db):
    eid = _event(db)
    with pytest.raises(DatabaseError):   # unknown company
        _assess(db, eid, "cmp-syn-nobody")
    with pytest.raises(DatabaseError):   # unknown event revision (composite FK to event_revisions)
        db.execute("INSERT INTO impact_assessments(event_id, event_revision_no, company_id, mechanism_id, "
                   "transmission_version, ruleset_version, scenario_kind, assessment_status, status_reason, "
                   "direction, magnitude_level, magnitude_basis, horizon, evidence_confidence, "
                   "exposure_confidence, direction_confidence, magnitude_confidence, scenario_uncertainty, "
                   "confidence_reasons_json, affected_lines_json, counter_evidence_json, "
                   "missing_inputs_json, "
                   "freshness_basis, is_synthetic, change_reason, changed_by, actor_type, created_at_utc, "
                   "updated_at_utc) VALUES (?,99,'cmp-syn-alpha','T1','t','r','current','needs_review',"
                   "'created_needs_review','unknown','low','qualitative','short','low','low','low','low',"
                   "'undetermined','{}','[]','[]','[]','not_established',1,'c','system:test','system',?,?)",
                   (eid, NOW, NOW))
    with pytest.raises(DatabaseError):   # mechanism outside T1-T9
        _assess(db, eid, "cmp-syn-alpha", mechanism="T0")


def test_composite_fk_requires_existing_candidate_revision(db):
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db)
    cand = _candidate(db, eid, "cmp-syn-alpha")
    aid = _assess(db, eid, "cmp-syn-alpha")
    sid = db.execute("SELECT source_item_id FROM exposure_candidate_evidence WHERE candidate_id=? LIMIT 1",
                     (cand,))[0]["source_item_id"]
    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO impact_assessment_inputs(assessment_id, input_kind, exposure_candidate_id, "
                   "exposure_candidate_revision, source_item_id, added_at_utc) VALUES (?,?,?,?,?,?)",
                   (aid, "exposure_candidate", cand, 999, sid, NOW))
    with pytest.raises(DatabaseError):   # foreign event evidence
        other = _event(db, headline="Unrelated synthetic event")
        ev = db.execute("SELECT evidence_id, source_item_id FROM event_evidence WHERE event_id=?",
                        (other,))[0]
        db.execute("INSERT INTO impact_assessment_inputs(assessment_id, input_kind, event_evidence_id, "
                   "source_item_id, added_at_utc) VALUES (?,?,?,?,?)",
                   (aid, "event_evidence", ev["evidence_id"], ev["source_item_id"], NOW))


# ------------------------------------------------------------------ 5-8 refutation, rollback, audit
def test_event_refutation_cascades_and_spares_terminal_and_non_current(db):
    eid, cand, aid = _provisional(db)
    hyp = _assess(db, eid, "cmp-syn-alpha", kind="hypothetical", status="scenario_only",
                  reason="created_scenario")
    rej = _assess(db, eid, "cmp-syn-beta")
    rid = _review(db, rej, "reject")
    _update(db, rej, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
            actor_type="human", changed_by="human:owner", last_review_id=rid)
    repo.revise_event(db, eid, {"verification_state": "refuted"}, reason="SYNTHETIC refutation",
                      changed_by="test")
    a = _status(db, aid)
    assert a["assessment_status"] == "withdrawn_evidence_invalid" and a["status_reason"] == "event_refuted"
    assert a["actor_type"] == "system" and a["changed_by"] == "system:event_refutation"
    assert _status(db, hyp)["assessment_status"] == "scenario_only"
    assert _status(db, rej)["assessment_status"] == "rejected_by_review"
    rev = db.execute("SELECT * FROM impact_assessment_revisions WHERE assessment_id=? ORDER BY "
                     "revision_no DESC "
                     "LIMIT 1", (aid,))[0]
    assert rev["previous_status"] == "provisional" and rev["new_status"] == "withdrawn_evidence_invalid"
    assert json.loads(rev["input_snapshot_json"])   # inputs recorded with validity
    with pytest.raises(DatabaseError, match="refuted"):   # no new current assessment for a refuted event
        _assess(db, eid, "cmp-syn-delta")
    assert _assess(db, eid, "cmp-syn-delta", kind="historical_test", status="scenario_only",
                   reason="created_scenario")


def test_audit_write_failure_rolls_back_event_refutation(db):
    eid, cand, aid = _provisional(db)
    cur = db.execute("SELECT current_revision FROM impact_assessments WHERE assessment_id=?", (aid,))[0]
    # make the next revision slot impossible to write: forge a duplicate key via the revisions table guard
    with pytest.raises(DatabaseError):
        db.execute("INSERT INTO impact_assessment_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (aid, cur["current_revision"] + 1, NOW, None, "x", "x", "system", "x", None, "{}", "[]"))
    # simulate an audit failure inside the cascade with a temporary trigger in this test database only
    db.execute("CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON impact_assessment_revisions "
               "BEGIN SELECT RAISE(ABORT, 'audit write failed'); END")
    with pytest.raises(DatabaseError, match="audit write failed"):
        repo.revise_event(db, eid, {"verification_state": "refuted"}, reason="SYNTHETIC", changed_by="test")
    db.execute("DROP TRIGGER fail_audit")
    state = db.execute("SELECT verification_state v FROM events WHERE event_id=?", (eid,))[0]["v"]
    assert state == "corroborated"
    assert _status(db, aid)["assessment_status"] == "provisional"


def test_human_rejection_and_system_withdrawal_cannot_be_confused(db):
    eid, cand, aid = _provisional(db)
    with pytest.raises(DatabaseError):   # rejection without a review
        _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
                actor_type="human", changed_by="human:owner")
    with pytest.raises(DatabaseError):   # system cannot reject
        _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected")
    with pytest.raises(DatabaseError):   # withdrawal with a human reason
        _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="reviewer_rejected")
    with pytest.raises(DatabaseError):   # withdrawal by a human actor
        _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="event_refuted",
                actor_type="human", changed_by="human:owner")
    with pytest.raises(DatabaseError):   # withdrawal without a valid reason
        _update(db, aid, assessment_status="withdrawn_evidence_invalid", status_reason="created_eligible")
    rid = _review(db, aid, "accept")   # a review of the wrong decision cannot back a rejection
    with pytest.raises(DatabaseError):
        _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
                actor_type="human", changed_by="human:owner", last_review_id=rid)
    rid = _review(db, aid, "reject")
    _update(db, aid, assessment_status="rejected_by_review", status_reason="reviewer_rejected",
            actor_type="human", changed_by="human:owner", last_review_id=rid)
    assert _status(db, aid)["assessment_status"] == "rejected_by_review"


def test_revisions_are_immutable(db):
    eid, cand, aid = _provisional(db)
    revs = db.execute("SELECT revision_no FROM impact_assessment_revisions WHERE assessment_id=? "
                      "ORDER BY revision_no", (aid,))
    assert [r["revision_no"] for r in revs] == [1, 2]
    _review(db, aid, "needs_more_evidence")   # delete guards fire per row, so every table needs a row
    for sql in ("UPDATE impact_assessment_revisions SET new_status='confirmed_conclusion'",
                "DELETE FROM impact_assessment_revisions", "DELETE FROM impact_assessments",
                "DELETE FROM impact_reviews", "DELETE FROM impact_assessment_inputs"):
        with pytest.raises(DatabaseError):
            db.execute(sql)
    with pytest.raises(DatabaseError, match="next revision"):
        db.execute("UPDATE impact_assessments SET direction='positive' WHERE assessment_id=?", (aid,))
    with pytest.raises(DatabaseError, match="identity"):
        _update(db, aid, company_id="cmp-syn-beta")


# ------------------------------------------------------------------ 9-11 evidence validity, synthetic
def test_read_time_invalidation_and_write_time_protection(db):
    eid, cand, aid = _provisional(db)
    assert _status(db, aid)["effective_status"] == "provisional"
    db.execute("UPDATE sources SET lifecycle_status='DISABLED', enabled=0 WHERE source_id='synapproved'")
    st = _status(db, aid)
    assert st["assessment_status"] == "provisional" and st["effective_status"] == "needs_revalidation"
    assert st["inputs_currently_valid"] == 0
    reasons = {r["invalid_reason"] for r in db.execute("SELECT invalid_reason FROM impact_invalid_inputs "
                                                       "WHERE assessment_id=?", (aid,))}
    assert reasons == {"source_restricted"}
    with pytest.raises(DatabaseError):   # acceptance blocked while inputs are invalid
        _review(db, aid, "accept")
    _update(db, aid, assessment_status="needs_revalidation", status_reason="source_restricted")
    with pytest.raises(DatabaseError, match="valid inputs"):
        _update(db, aid, assessment_status="provisional", status_reason="revalidated")


def test_upgrade_requires_eligible_exposure_and_established_freshness(db):
    _exposure(db, "cmp-syn-alpha", source="synreal")    # unapproved, non-synthetic source
    eid = _event(db)
    aid = _assess(db, eid, "cmp-syn-alpha")
    with pytest.raises(DatabaseError, match="eligible exposure"):   # no exposure input at all
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    _exposure(db, "cmp-syn-beta")
    cand = _candidate(db, eid, "cmp-syn-beta")
    nf = _assess(db, eid, "cmp-syn-beta", freshness="not_established")
    _link_candidate(db, nf, cand)
    with pytest.raises(DatabaseError, match="freshness"):
        _update(db, nf, assessment_status="provisional", status_reason="created_eligible")
    _update(db, nf, assessment_status="needs_review", status_reason="freshness_not_established")


def test_unknown_step_forces_unknown_direction(db):
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db)
    cand = _candidate(db, eid, "cmp-syn-alpha", confirm=True)
    aid = _assess(db, eid, "cmp-syn-alpha", direction="negative")
    _link_candidate(db, aid, cand)
    db.execute("INSERT INTO impact_transmission_steps VALUES (?,1,1,'brent','input "
               "cost',NULL,'short','unknown')",
               (aid,))
    with pytest.raises(DatabaseError, match="unknown direction"):
        _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible", direction="unknown")


def test_synthetic_and_real_records_cannot_mix(db):
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db)
    cand = _candidate(db, eid, "cmp-syn-alpha")
    with pytest.raises(DatabaseError, match="cmp-syn"):   # fictional company on a real assessment
        _assess(db, eid, "cmp-syn-alpha", synthetic=0)
    db.execute("INSERT INTO companies(company_id, legal_name, listing_status, created_at_utc, "
               "updated_at_utc) "
               "VALUES ('cmp-realtest','Non-synthetic test company','listed',?,?)", (NOW, NOW))
    real = _assess(db, eid, "cmp-realtest", synthetic=0)
    ev = db.execute("SELECT evidence_id, source_item_id FROM event_evidence WHERE event_id=?", (eid,))[0]
    with pytest.raises(DatabaseError, match="synthetic input"):
        db.execute("INSERT INTO impact_assessment_inputs(assessment_id, input_kind, event_evidence_id, "
                   "source_item_id, added_at_utc) VALUES (?,?,?,?,?)",
                   (real, "event_evidence", ev["evidence_id"], ev["source_item_id"], NOW))
    syn = _assess(db, eid, "cmp-syn-alpha")
    _link_candidate(db, syn, cand)
    assert _status(db, syn)["data_label"] == "SYNTHETIC TEST DATA"
    assert _status(db, real)["data_label"] == "real"
    seed = json.loads((Path(__file__).resolve().parents[1] / "database/seed/companies.json").read_text())
    assert not [c for c in seed["companies"] if c["ticker"].startswith("SYN")]


# ------------------------------------------------------------------ 12-13 sector coverage
def _sector(db, eid):
    rows = db.execute("SELECT * FROM impact_sector_aggregates_current WHERE event_id=? AND "
                      "scenario_kind='current'",
                      (eid,))
    return rows[0] if rows else None


def test_partial_coverage_never_concludes(db):
    eid, cand, aid = _provisional(db)          # alpha assessed (negative); beta, gamma, delta not
    s = _sector(db, eid)
    assert s["eligible_n"] == 4 and s["assessed_valid_n"] == 1 and s["unassessed_n"] == 3
    assert s["completeness"] == "partial" and s["sector_conclusion"] == "not_concluded_partial_coverage"
    assert s["direction_among_assessed"] == "negative"   # subset only, never presented as the sector view
    excluded = {e["company_id"]: e["reason"] for e in json.loads(s["excluded_json"])}
    assert excluded["cmp-syn-beta"] == "no_assessment"
    assert excluded["cmp-syn-gamma"] == "listing_status_unknown"
    assert excluded["cmp-syn-delta"] == "suspended_at_event_date"
    assert s["suspended_n"] == 1 and s["eligibility_uncertain_n"] == 1
    assert s["data_label"] == "SYNTHETIC TEST DATA"
    unclassified = db.execute("SELECT * FROM impact_unclassified_companies")
    assert unclassified == []   # eps has no assessment, so nothing to report yet
    _assess(db, eid, "cmp-syn-eps")
    un = db.execute("SELECT company_id, reason FROM impact_unclassified_companies WHERE event_id=?", (eid,))
    assert un == [{"company_id": "cmp-syn-eps", "reason": "no_sector_classification"}]


def test_complete_coverage_rules_unknown_and_mixed(db):
    # keep only two listed companies in the sector by closing the others' classifications before the event
    for c in ("cmp-syn-gamma", "cmp-syn-delta"):
        db.execute("UPDATE company_classifications SET valid_to='2010-01-01' WHERE company_id=?", (c,))
    _exposure(db, "cmp-syn-alpha")
    _exposure(db, "cmp-syn-beta")
    eid = _event(db)
    ids = {}
    for c, d in (("cmp-syn-alpha", "negative"), ("cmp-syn-beta", "unknown")):
        cand = _candidate(db, eid, c, confirm=True)
        ids[c] = _assess(db, eid, c, direction=d)
        _link_candidate(db, ids[c], cand)
        _update(db, ids[c], assessment_status="provisional", status_reason="created_eligible")
    s = _sector(db, eid)
    assert s["completeness"] == "complete" and s["sector_conclusion"] == "unknown"   # unknown stays unknown
    # a direction change needs a new human review: revalidation request, then system revalidation
    rid = _review(db, ids["cmp-syn-beta"], "request_revalidation")
    _update(db, ids["cmp-syn-beta"], direction="positive", status_reason="reviewer_requested_revalidation",
            assessment_status="needs_revalidation", actor_type="human", changed_by="human:owner",
            last_review_id=rid)
    _update(db, ids["cmp-syn-beta"], status_reason="revalidated", assessment_status="provisional")
    assert _sector(db, eid)["sector_conclusion"] == "mixed"


def test_delisted_company_uses_event_date_status(db):
    db.execute("INSERT INTO company_status_history(company_id, status, effective_date, "
               "date_precision, details, "
               "recorded_at_utc) VALUES ('cmp-syn-beta','listed','2000-01-01','exact','SYNTHETIC',?)", (NOW,))
    db.execute("INSERT INTO company_status_history(company_id, status, effective_date, "
               "date_precision, details, "
               "recorded_at_utc) VALUES "
               "('cmp-syn-beta','delisted','2026-12-31','exact','SYNTHETIC',?)", (NOW,))
    db.execute("UPDATE companies SET listing_status='delisted' WHERE company_id='cmp-syn-beta'")
    eid, cand, aid = _provisional(db)          # event 2026-11-05, before the delisting
    rows = {r["company_id"]: r["listing_at_event"] for r in db.execute(
        "SELECT company_id, listing_at_event FROM impact_event_company_eligibility WHERE event_id=?", (eid,))}
    assert rows["cmp-syn-beta"] == "listed" and rows["cmp-syn-delta"] == "suspended"
    later = _event(db, headline="Brent crude oil price rises again", date="2027-02-01")
    _assess(db, later, "cmp-syn-alpha")
    rows = {r["company_id"]: r["listing_at_event"] for r in db.execute(
        "SELECT company_id, listing_at_event FROM impact_event_company_eligibility WHERE event_id=?",
        (later,))}
    assert rows["cmp-syn-beta"] == "not_listed"


# ------------------------------------------------------------------ reinstatement
def test_reinstatement_of_confirmed_chain_requires_human_review(db):
    eid, cand, aid = _provisional(db)
    _confirm(db, aid)
    db.execute("UPDATE sources SET terms_status='restricted' WHERE source_id='synapproved'")
    _update(db, aid, assessment_status="needs_revalidation", status_reason="source_restricted")
    db.execute("UPDATE sources SET terms_status='approved' WHERE source_id='synapproved'")
    with pytest.raises(DatabaseError, match="reinstatement"):   # automatic revalidation not allowed
        _update(db, aid, assessment_status="provisional", status_reason="revalidated")
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="provisional", status_reason="reinstated", actor_type="human",
            changed_by="human:owner", last_review_id=rid)
    hist = [r["new_status"] for r in db.execute("SELECT new_status FROM impact_assessment_revisions "
                                                 "WHERE assessment_id=? ORDER BY revision_no", (aid,))]
    assert hist == ["needs_review", "provisional", "confirmed_conclusion", "needs_revalidation",
                    "provisional"]


# ------------------------------------------------------------------ 14-17 expiry policies
def _policy(db, version):
    db.execute("INSERT INTO impact_expiry_policy_versions VALUES (?,?,?,?,?,NULL)",
               (version, '{"TEST PARAMETER": "not production policy"}', "SYNTHETIC test", "tester", NOW))


def _approve(db, version, start):
    db.execute("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, "
               "effective_from_utc, "
               "recorded_at_utc, notes) VALUES (?,?,?,?,?,?)",
               (version, "approved", "tester", start, NOW, "test"))


def _retire(db, version, end):
    db.execute("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, effective_to_utc, "
               "recorded_at_utc, notes) VALUES (?,?,?,?,?,?)",
               (version, "retired", "tester", end, NOW, "test"))


def test_registry_ships_empty_and_lifecycle_is_immutable(db):
    assert db.execute("SELECT COUNT(*) n FROM impact_expiry_policy_versions")[0]["n"] == 0
    assert db.execute("SELECT COUNT(*) n FROM impact_expiry_policy_events")[0]["n"] == 0
    _policy(db, "test/1")
    assert db.execute("SELECT status FROM impact_expiry_policies_current")[0]["status"] == "draft"
    with pytest.raises(DatabaseError, match="retired after"):
        _retire(db, "test/1", "2027-01-01T00:00:00Z")
    _approve(db, "test/1", "2026-01-01T00:00:00Z")
    with pytest.raises(DatabaseError):    # one approval per version
        _approve(db, "test/1", "2026-02-01T00:00:00Z")
    for sql in ("UPDATE impact_expiry_policy_versions SET rationale='x'", "DELETE FROM "
                                                                          "impact_expiry_policy_events",
                "UPDATE impact_expiry_policy_events SET actor='x'"):
        with pytest.raises(DatabaseError):
            db.execute(sql)
    with pytest.raises(DatabaseError, match="precede"):
        _retire(db, "test/1", "2025-01-01T00:00:00Z")
    _retire(db, "test/1", "2026-06-01T00:00:00Z")
    assert db.execute("SELECT status FROM impact_expiry_policies_current")[0]["status"] == "retired"


def test_overlapping_approvals_are_refused(db):
    _policy(db, "test/1")
    _policy(db, "test/2")
    _approve(db, "test/1", "2026-01-01T00:00:00Z")
    with pytest.raises(DatabaseError, match="overlapping"):     # open-ended policy blocks
        _approve(db, "test/2", "2027-01-01T00:00:00Z")
    with pytest.raises(DatabaseError, match="overlapping"):     # earlier start also overlaps
        _approve(db, "test/2", "2025-01-01T00:00:00Z")
    db.batch([("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, effective_to_utc, "
               "recorded_at_utc, notes) VALUES "
               "('test/1','retired','tester','2027-01-01T00:00:00Z',?, 't')", (NOW,)),
              ("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, "
               "effective_from_utc, "
               "recorded_at_utc, notes) VALUES "
               "('test/2','approved','tester','2027-01-01T00:00:00Z',?, 't')", (NOW,))])
    assert db.execute("SELECT * FROM impact_expiry_policy_overlaps") == []


def test_retired_policy_cannot_be_selected_and_null_is_recorded(db):
    eid = _event(db)
    aid = _assess(db, eid, "cmp-syn-alpha")
    assert _status(db, aid)["expiry_policy_version"] is None
    _policy(db, "test/1")
    _approve(db, "test/1", "2026-01-01T00:00:00Z")
    _retire(db, "test/1", "2026-06-01T00:00:00Z")
    with pytest.raises(DatabaseError, match="expiry policy"):
        db.execute("INSERT INTO impact_assessments SELECT NULL, event_id, event_revision_no, 'cmp-syn-beta', "
                   "mechanism_id, transmission_version, ruleset_version, calculation_version, scenario_kind, "
                   "assessment_status, status_reason, direction, magnitude_level, magnitude_basis, horizon, "
                   "evidence_confidence, exposure_confidence, direction_confidence, magnitude_confidence, "
                   "scenario_uncertainty, confidence_reasons_json, affected_lines_json, "
                   "counter_evidence_json, "
                   "missing_inputs_json, quantification_json, market_check, analysis_id, 'test/1', "
                   "'policy_expiry', is_synthetic, 1, NULL, change_reason, changed_by, actor_type, "
                   "'2026-11-08T00:00:00Z', updated_at_utc FROM impact_assessments WHERE "
                   "assessment_id=?", (aid,))


def test_two_connection_concurrent_approval_race():
    path = os.path.join(tempfile.mkdtemp(), "race.db")
    d = SQLiteDatabase(path)
    migrate(d)
    d.close()
    a = sqlite3.connect(path, isolation_level=None)
    b = sqlite3.connect(path, isolation_level=None, timeout=0.2)
    a.execute("INSERT INTO impact_expiry_policy_versions VALUES "
              "('race/1','{}','SYNTHETIC','tester',?,NULL)", (NOW,))
    a.execute("INSERT INTO impact_expiry_policy_versions VALUES "
              "('race/2','{}','SYNTHETIC','tester',?,NULL)", (NOW,))
    ins = ("INSERT INTO impact_expiry_policy_events(policy_version, event_type, actor, effective_from_utc, "
           "recorded_at_utc, notes) VALUES (?, 'approved', 'tester', ?, ?, 'race')")
    a.execute("BEGIN IMMEDIATE")
    a.execute(ins, ("race/1", "2027-01-01T00:00:00Z", NOW))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        b.execute("BEGIN IMMEDIATE")
        b.execute(ins, ("race/2", "2027-06-01T00:00:00Z", NOW))
    a.execute("COMMIT")
    try:
        b.execute("ROLLBACK")
    except sqlite3.OperationalError:
        pass
    with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
        b.execute(ins, ("race/2", "2027-06-01T00:00:00Z", NOW))
    approvals = a.execute("SELECT COUNT(*) FROM impact_expiry_policy_events "
                          "WHERE event_type='approved'").fetchone()[0]
    assert approvals == 1
    assert a.execute("SELECT COUNT(*) FROM impact_expiry_policy_overlaps").fetchone()[0] == 0


# ------------------------------------------------------------------ 18 existing schema still protected
def test_analyses_are_delete_protected_and_market_check_fixed(db):
    eid = _event(db)
    db.execute("INSERT INTO analyses(event_id, company_id, analysis_version, label, created_at_utc) "
               "VALUES (?,?,?,?,?)", (eid, "cmp-syn-alpha", 1, "qualitative", NOW))
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM analyses")
    aid = _assess(db, eid, "cmp-syn-alpha")
    with pytest.raises(DatabaseError):
        _update(db, aid, market_check="positive reaction")
