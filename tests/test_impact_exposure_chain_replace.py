"""The 0008 exposure chain cannot be overwritten by REPLACE (migration 0009 guards, SYNTHETIC data only).

Reproduces the three attacks found in the final acceptance audit of e076189:
  1. HIGH: REPLACE INTO exposure_candidates resets a candidate (and, through the inherited conflict policy,
     overwrites its revision-1 history row).
  2. HIGH: REPLACE INTO exposure_candidate_evidence redirects a retracted evidence link (by rowid) to a copied
     record. The candidate could then be re-mapped and re-accepted, and used for a new confirmed assessment.
  3. MEDIUM: REPLACE INTO exposure_candidate_revisions rewrites recorded history.
Every attack runs with foreign keys ON and OFF. Failed attempts must leave the whole chain byte-identical.
"""

from __future__ import annotations

import pytest

import engines.exposure_rules as rules
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines.exposure_mapping import map_event, retract_evidence, review
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
DIRECT = ("SELECT candidate_id FROM exposure_candidates WHERE event_id=? AND company_id='cmp-syn-alpha' "
          "AND exposure_level='direct'")


@pytest.fixture(params=[True, False], ids=["fk-on", "fk-off"])
def db(request):
    d = SQLiteDatabase()
    migrate(d)
    _base(d)
    if not request.param:
        d._conn.execute("PRAGMA foreign_keys = OFF")
    yield d
    d.close()


def _rel(db, modifier):
    return db.execute("SELECT date('now', ?) d", (modifier,))[0]["d"]


def _rows(db, sql, args=()):
    return [tuple(r) for r in db.execute(sql, args)]


def _chain(db):
    """The complete state a failed attack must leave untouched."""
    return {
        "candidates": _rows(db, "SELECT * FROM exposure_candidates ORDER BY candidate_id"),
        "revisions": _rows(db, "SELECT * FROM exposure_candidate_revisions "
                               "ORDER BY candidate_id, revision_no"),
        "links": _rows(db, "SELECT rowid, * FROM exposure_candidate_evidence ORDER BY rowid"),
        "retractions": _rows(db, "SELECT * FROM evidence_retractions ORDER BY retraction_id"),
        "exposures": _rows(db, "SELECT * FROM company_exposures ORDER BY exposure_id"),
        "assessments": _rows(db, "SELECT * FROM impact_assessments ORDER BY assessment_id"),
        "impact_revisions": _rows(db, "SELECT * FROM impact_assessment_revisions "
                                      "ORDER BY assessment_id, revision_no"),
        "effective": _rows(db, "SELECT assessment_id, effective_status FROM impact_assessments_current"),
        "candidate_effective": _rows(db, "SELECT candidate_id, effective_status, evidence_currently_valid "
                                         "FROM exposure_candidates_current"),
    }


def _retracted(db):
    """Audited setup: evidence -> accepted candidate -> eligible assessment -> evidence retracted."""
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db, date=_rel(db, "-10 days"))
    cand = _candidate(db, eid, "cmp-syn-alpha", confirm=True)
    aid = _assess(db, eid, "cmp-syn-alpha")
    _link_candidate(db, aid, cand)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    x = db.execute("SELECT company_exposure_id x FROM exposure_candidate_evidence WHERE candidate_id=? "
                   "AND company_exposure_id IS NOT NULL", (cand,))[0]["x"]
    retract_evidence(db, "company_exposures", x, reason="SYNTHETIC: incorrect", retracted_by="owner")
    return eid, cand, aid, x


def _copy_exposure(db, x):
    """A copied exposure record: same source item, apparently fresh validity (unlinked inserts allowed)."""
    db.execute("INSERT INTO company_exposures(company_id, exposure_kind, subject, confidence, "
               "source_item_id, evidence_excerpt, valid_to, last_verified_utc) "
               "SELECT company_id, exposure_kind, subject, confidence, source_item_id, "
               "evidence_excerpt, '2099-12-31', last_verified_utc "
               "FROM company_exposures WHERE exposure_id=?", (x,))
    return db.execute("SELECT MAX(exposure_id) x FROM company_exposures")[0]["x"]


def _insert(db, verb, table, row, tail=""):
    cols = list(row)
    db.execute(f"{verb} INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) {tail}",  # noqa: S608
               [row[c] for c in cols])


# ------------------------------------------------------------------ 1. exposure_candidates
CAND_PATHS = [("REPLACE", ""), ("INSERT OR REPLACE", ""), ("INSERT", ""), ("INSERT OR IGNORE", ""),
              ("INSERT", "ON CONFLICT DO UPDATE SET evidence_status='unverified'"),
              ("INSERT", "ON CONFLICT DO NOTHING")]


@pytest.mark.parametrize("verb,tail", CAND_PATHS, ids=[f"{v}{'-' + t.split()[3] if t else ''}"
                                                       for v, t in CAND_PATHS])
@pytest.mark.parametrize("identity", ["candidate_id", "unique_key"])
def test_attack1_candidate_reset_refused(db, verb, tail, identity):
    eid, cand, aid, x = _retracted(db)
    row = dict(db.execute("SELECT * FROM exposure_candidates WHERE candidate_id=?", (cand,))[0])
    row.update(evidence_status="unverified", current_revision=1, review_status="pending", last_review_id=None,
               change_reason="reset by attacker")
    if identity == "unique_key":
        # same (event, company, category, subtype, mechanism, ruleset) under a new candidate_id
        row["candidate_id"] = cand + 100
    before = _chain(db)
    with pytest.raises(DatabaseError, match="existing candidates cannot be replaced"):
        _insert(db, verb, "exposure_candidates", row, tail)
    assert _chain(db) == before


# ------------------------------------------------------------------ 2. exposure_candidate_evidence
def _link_row(db, x):
    return dict(db.execute("SELECT rowid AS rowid_, * FROM exposure_candidate_evidence "
                           "WHERE company_exposure_id=?", (x,))[0])


LINK_PATHS = [("REPLACE", ""), ("INSERT OR REPLACE", ""), ("INSERT", ""), ("INSERT OR IGNORE", ""),
              ("INSERT", "ON CONFLICT DO UPDATE SET company_exposure_id=excluded.company_exposure_id"),
              ("INSERT", "ON CONFLICT DO NOTHING")]


@pytest.mark.parametrize("verb,tail", LINK_PATHS, ids=[f"{v}{'-' + t.split()[3] if t else ''}"
                                                       for v, t in LINK_PATHS])
@pytest.mark.parametrize("identity", ["rowid_redirect", "unique_key"])
def test_attack2_evidence_link_redirect_refused(db, verb, tail, identity):
    eid, cand, aid, x = _retracted(db)
    link = _link_row(db, x)
    row = {"candidate_id": cand, "role": "company_specific", "event_evidence_id": None,
           "company_exposure_id": x, "relationship_id": None, "source_item_id": link["source_item_id"],
           "added_at_utc": "t"}
    if identity == "rowid_redirect":                  # the audited attack: same rowid, copied record
        row = dict(row, rowid=link["rowid_"], company_exposure_id=_copy_exposure(db, x))
    before = _chain(db)
    with pytest.raises(DatabaseError, match="existing evidence links cannot be replaced"):
        _insert(db, verb, "exposure_candidate_evidence", row, tail)
    assert _chain(db) == before
    assert _link_row(db, x)["rowid_"] == link["rowid_"]       # the link to the retracted record is intact


def test_attack2_end_to_end_no_confirmed_assessment_from_substituted_evidence(db):
    eid, cand, aid, x = _retracted(db)
    link = _link_row(db, x)
    copy = _copy_exposure(db, x)                                             # step 2
    before = _chain(db)
    with pytest.raises(DatabaseError, match="existing evidence links cannot be replaced"):   # step 3
        db.execute("REPLACE INTO exposure_candidate_evidence(rowid, candidate_id, role, company_exposure_id, "
                   "source_item_id, added_at_utc) VALUES (?,?,?,?,?,?)",
                   (link["rowid_"], cand, "company_specific", copy, link["source_item_id"], "t"))
    assert _chain(db) == before
    try:                                                                     # step 4: remap ...
        map_event(db, eid, synthetic=True)
    except DatabaseError:
        pass
    try:                                                                     # ... and re-accept
        review(db, cand, "accept", reviewer="owner", notes="SYNTHETIC re-accept attempt")
    except (DatabaseError, ValueError):
        pass
    c = db.execute("SELECT effective_status s, evidence_currently_valid v FROM exposure_candidates_current "
                   "WHERE candidate_id=?", (cand,))[0]
    assert c["s"] not in ("strongly_supported", "confirmed") and c["v"] == 0
    # the link still names the retracted record
    assert db.execute("SELECT 1 FROM exposure_candidate_evidence WHERE candidate_id=? "
                      "AND company_exposure_id=?", (cand, x))
    assert not db.execute("SELECT 1 FROM exposure_candidate_evidence WHERE company_exposure_id=?", (copy,))
    with pytest.raises(DatabaseError, match="immutable"):                   # retracted record stays linked
        db.execute("UPDATE company_exposures SET subject='x' WHERE exposure_id=?", (x,))
    new = _assess(db, eid, "cmp-syn-alpha", mechanism="T3")                 # step 5
    _link_candidate(db, new, cand)
    with pytest.raises(DatabaseError):
        _update(db, new, assessment_status="provisional", status_reason="created_eligible")
    with pytest.raises(DatabaseError):
        rid = _review(db, new, "accept")
        _update(db, new, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
                last_review_id=rid, **HUMAN)
    assert db.execute("SELECT COUNT(*) n FROM impact_assessments_current WHERE effective_status IN "
                      "('provisional','confirmed_conclusion')")[0]["n"] == 0


# ------------------------------------------------------------------ 3. exposure_candidate_revisions
REV_PATHS = [("REPLACE", ""), ("INSERT OR REPLACE", ""), ("INSERT", ""), ("INSERT OR IGNORE", ""),
             ("INSERT", "ON CONFLICT DO UPDATE SET evidence_status='confirmed'"),
             ("INSERT", "ON CONFLICT DO NOTHING")]


@pytest.mark.parametrize("verb,tail", REV_PATHS, ids=[f"{v}{'-' + t.split()[3] if t else ''}"
                                                      for v, t in REV_PATHS])
@pytest.mark.parametrize("which", ["current", "first"])
def test_attack3_revision_rewrite_refused(db, verb, tail, which):
    eid, cand, aid, x = _retracted(db)
    order = "DESC" if which == "current" else "ASC"
    rev = dict(db.execute(f"SELECT * FROM exposure_candidate_revisions WHERE candidate_id=? "  # noqa: S608
                          f"ORDER BY revision_no {order} LIMIT 1", (cand,))[0])
    rev.update(evidence_status="confirmed", change_reason="history rewritten by attacker")
    before = _chain(db)
    with pytest.raises(DatabaseError, match="existing revisions cannot be replaced|current revision only"):
        _insert(db, verb, "exposure_candidate_revisions", rev, tail)
    assert _chain(db) == before


# ------------------------------------------------------------------ legitimate operations still work
def test_legitimate_chain_operations_still_work(db, monkeypatch):
    # first-time candidate creation, first-time evidence links and new revisions
    _exposure(db, "cmp-syn-alpha")
    eid = _event(db, date=_rel(db, "-10 days"))
    res = map_event(db, eid, synthetic=True)
    assert res.stored["created"] >= 1
    cand = db.execute(DIRECT, (eid,))[0]["candidate_id"]
    revs = db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions WHERE candidate_id=?",
                      (cand,))[0]["n"]
    review(db, cand, "accept", reviewer="owner", notes="SYNTHETIC check")          # new revision
    assert db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions WHERE candidate_id=?",
                      (cand,))[0]["n"] == revs + 1
    x = db.execute("SELECT company_exposure_id x FROM exposure_candidate_evidence WHERE candidate_id=? "
                   "AND company_exposure_id IS NOT NULL", (cand,))[0]["x"]
    # retraction (revalidation writes a further revision)
    retract_evidence(db, "company_exposures", x, reason="SYNTHETIC: replaced", retracted_by="owner")
    assert db.execute("SELECT evidence_status s FROM exposure_candidates WHERE candidate_id=?",
                      (cand,))[0]["s"] == "unverified"
    # a genuinely new exposure record, mapped under a NEW ruleset version on the same event
    _exposure(db, "cmp-syn-alpha")
    monkeypatch.setattr(rules, "RULESET_VERSION", "exposure-rules/1.0.1-synthetic")
    assert map_event(db, eid, synthetic=True).stored["created"] >= 1
    monkeypatch.undo()
    cand_rs = db.execute(DIRECT + " AND ruleset_version='exposure-rules/1.0.1-synthetic'",
                         (eid,))[0]["candidate_id"]
    linked = {r["company_exposure_id"] for r in db.execute(
        "SELECT company_exposure_id FROM exposure_candidate_evidence WHERE candidate_id=? "
        "AND company_exposure_id IS NOT NULL", (cand_rs,))}
    assert x not in linked                                  # the retracted record is not reused
    # a replacement event produces another new candidate on the new evidence
    eid2 = _event(db, headline="Brent crude oil price rises again", date=_rel(db, "+0 days"))
    map_event(db, eid2, synthetic=True)
    cand2 = db.execute(DIRECT, (eid2,))[0]["candidate_id"]
    # human review of the genuinely new candidate, then a new eligible (and confirmed) assessment
    review(db, cand2, "accept", reviewer="owner", notes="SYNTHETIC revalidation")
    aid = _assess(db, eid2, "cmp-syn-alpha")
    _link_candidate(db, aid, cand2)
    _update(db, aid, assessment_status="provisional", status_reason="created_eligible")
    rid = _review(db, aid, "accept")
    _update(db, aid, assessment_status="confirmed_conclusion", status_reason="reviewer_accepted",
            last_review_id=rid, **HUMAN)
    assert db.execute("SELECT effective_status s FROM impact_assessments_current WHERE assessment_id=?",
                      (aid,))[0]["s"] == "confirmed_conclusion"
