"""Phase 4 company exposure mapping tests.

All company exposures, relationships, sources and events here are SYNTHETIC FIXTURES created in a
throwaway local SQLite database. They are not real-world evidence about any company. The
company master (tickers, names, sectors) is the project's existing seed.
"""

from __future__ import annotations

import inspect
import json

import pytest

from database import repositories as repo
from database import seed_loader
from database.connection import DatabaseError, SQLiteDatabase
from database.migrate import migrate
from engines import entity_resolution, exposure_mapping, exposure_rules
from engines import exposure_taxonomy as tax
from engines.entity_resolution import resolve
from engines.exposure_mapping import map_event, record_relationship, review, suggest_with_llm
from engines.llm import ClaudeProvider, FixtureProvider, LLMGateway, Pricing

NOW = "2026-11-07T00:00:00Z"
PRICE = Pricing(4.0, 20.0)


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    for sid, approved in (("fxapproved", True), ("fxunapproved", False)):
        if approved:   # test-only source satisfying the ACTIVE rules; exists only in this throwaway DB
            d.execute("INSERT INTO sources(source_id, name, source_type, reliability_tier, access_status, "
                      "terms_status, lifecycle_status, enabled, is_synthetic, created_at_utc, "
                      "updated_at_utc) "
                      "VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                      (sid, "SYNTHETIC approved fixture", "other", "primary_official", "verified_permitted",
                       "approved", "ACTIVE", 1, NOW, NOW))
        else:
            d.execute("INSERT INTO sources(source_id, name, source_type, is_synthetic, created_at_utc, "
                      "updated_at_utc) VALUES (?,?,?,1,?,?)", (sid, "SYNTHETIC unapproved fixture", "other",
                                                               NOW, NOW))
    yield d
    d.close()


def item(db, source, n, text):
    return repo.record_source_item(db, source_id=source, url=f"https://fixture.example/{source}/{n}",
                                   content=text, excerpt=text[:900], title=f"fixture {n}",
                                   collected_at_utc=NOW, published_at_utc=NOW).source_item_id


def exposure(db, ticker, kind, subject, *, source="fxapproved", confidence="documented"):
    cid = repo.company_by_ticker(db, ticker)["company_id"]
    text = f"SYNTHETIC FIXTURE: {ticker} {kind} {subject}"
    sid = item(db, source, f"x-{ticker}-{kind}-{subject}".replace(" ", "-"), text)
    db.execute("INSERT INTO company_exposures(company_id, exposure_kind, subject, confidence, "
               "source_item_id, evidence_excerpt, last_verified_utc) VALUES (?,?,?,?,?,?,?)",
               (cid, kind, subject, confidence, sid, text, NOW))
    return db.execute("SELECT MAX(exposure_id) i FROM company_exposures")[0]["i"]


def event(db, headline, *, event_type="commodity_price", verification="corroborated", stage="confirmed_fact",
          magnitude="medium", entities=(), source="fxapproved", claim_type="news_report", n=None):
    sid = item(db, source, n or headline.replace(" ", "-"), f"SYNTHETIC FIXTURE. {headline}.")
    eid = repo.create_event(db, {"event_type": event_type, "headline": headline, "summary": headline,
                                 "status_stage": stage, "verification_state": verification,
                                 "magnitude": magnitude, "confidence": 0.8, "event_date": "2026-11-05"},
                            changed_by="test")
    repo.add_evidence(db, event_id=eid, source_item_id=sid, claim=headline, claim_type=claim_type,
                      relation="supports", excerpt=f"SYNTHETIC FIXTURE. {headline}.", recorded_by="test")
    ents = [{"name": e, "entity_type": "company", "quote": e} for e in entities]
    db.execute("INSERT INTO event_extractions(source_item_id, event_id, schema_version, prompt_version, "
               "model, extracted_json, confidence, confidence_explanation, needs_human_review, "
               "review_reasons_json, provenance_json, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (sid, eid, "event-extraction/1", "1.0.0", "fixture-model",
                json.dumps({"event": {"entities": ents, "indicators": [],
                                      "claims": [{"claim": headline, "claim_type": claim_type,
                                                  "quote": headline}]}}),
                0.8, "fixture", 0, "[]", "{}", NOW))
    return eid


def by_symbol(result, symbol):
    return [c for c in result.candidates if c.company.get("psx_symbol") == symbol]


# ------------------------------------------------------------------ entity resolution
def test_exact_ticker_alias_and_short_name(db):
    assert resolve(db, "LUCK").company["psx_symbol"] == "LUCK"
    assert resolve(db, "Lucky Cement Limited").company["psx_symbol"] == "LUCK"
    r = resolve(db, "Lucky Cement")
    assert r.status == "resolved" and r.method == "alias:short_name" and r.needs_review  # derived alias


def test_lowercase_words_never_match_tickers(db):
    assert resolve(db, "luck").status == "unresolved"
    assert resolve(db, "Luck").status == "unresolved"


def test_ambiguous_partial_name_is_not_auto_selected(db):
    r = resolve(db, "Engro")
    assert r.status == "ambiguous" and r.company is None
    assert {c["psx_symbol"] for c in r.candidates} == {"EFERT", "ENGROH", "EPCL"}


def test_similar_names_resolve_to_the_right_company(db):
    assert resolve(db, "Fauji Fertilizer Company").company["psx_symbol"] == "FFC"
    assert resolve(db, "Engro Fertilizers").company["psx_symbol"] == "EFERT"


def test_unknown_company_is_unresolved_and_nothing_is_created(db):
    before = db.execute("SELECT COUNT(*) n FROM companies")[0]["n"]
    r = resolve(db, "Acme Widgets Pakistan")
    assert r.status == "unresolved" and r.company is None
    assert db.execute("SELECT COUNT(*) n FROM companies")[0]["n"] == before
    assert resolve(db, "ZZZZ").status == "unresolved"   # an unknown symbol is never invented


def test_delisted_company_resolves_only_historically(db):
    assert resolve(db, "FFBL", as_of="2024-06-01").status == "historical"
    later = resolve(db, "FFBL", as_of="2025-03-01")
    assert later.status == "unresolved" and any("successor cmp-ffc" in x for x in later.reasons)
    assert later.company is None   # never silently re-pointed to the successor


def test_former_name_is_matched_with_review_and_dates(db):
    cid = repo.company_by_ticker(db, "LUCK")["company_id"]
    db.execute("INSERT INTO company_aliases(company_id, alias, alias_normalized, alias_type, confidence, "
               "valid_from, valid_to, evidence) VALUES (?,?,?,?,?,?,?,?)",
               (cid, "Old Lucky Name", "old lucky name", "former_name", "verified", "1990-01-01",
                "2000-12-31", "SYNTHETIC FIXTURE"))
    r = resolve(db, "Old Lucky Name", as_of="1995-06-01")
    assert r.status == "resolved" and r.company["psx_symbol"] == "LUCK"
    assert any("former name" in x for x in r.reasons) and r.needs_review
    assert resolve(db, "Old Lucky Name", as_of="2010-01-01").status == "unresolved"


# ------------------------------------------------------------------ taxonomy
def test_direction_lookup_and_neutral_distinct_from_unknown():
    assert tax.to_direction("UNCERTAIN") == "unknown" and tax.to_direction("NEUTRAL") == "neutral"
    assert tax.to_direction("POSITIVE") == "positive" and tax.to_direction("mixed") == "mixed"
    with pytest.raises(ValueError):
        tax.to_direction("bullish")
    assert tax.combine([0]) == "neutral" and tax.combine([None]) == "unknown"
    assert tax.combine([1, -1]) == "mixed" and tax.combine([-1]) == "negative"
    assert set(tax.CATEGORIES) == {"operational", "financial", "regulatory", "macroeconomic", "geopolitical",
                                   "sector"}
    assert all(defn for subs in tax.TAXONOMY.values() for defn in subs.values())


# ------------------------------------------------------------------ rule-based mapping
def test_oil_rise_maps_by_documented_exposure_not_by_sector(db):
    exposure(db, "ATRL", "input", "crude oil")
    exposure(db, "OGDC", "product", "crude oil")
    eid = event(db, "Brent crude oil price rises sharply")
    r = map_event(db, eid, synthetic=True)
    atrl = by_symbol(r, "ATRL")[0]
    ogdc = by_symbol(r, "OGDC")[0]
    assert atrl.direction == "negative" and atrl.level == "direct" and atrl.rule_id == "R-OIL-1"
    assert ogdc.direction == "positive"
    pso = by_symbol(r, "PSO")
    assert pso and all(c.direction == "unknown" and c.level == "indirect"
                       and c.evidence_status == "unverified" for c in pso)   # no blanket "every OMC benefits"
    assert any("sector membership alone is not proof" in m for m in pso[0].missing)


def test_oil_fall_reverses_and_unclear_change_stays_unknown(db):
    exposure(db, "ATRL", "input", "crude oil")
    down = map_event(db, event(db, "Brent crude oil price falls"), synthetic=True)
    assert by_symbol(down, "ATRL")[0].direction == "positive"
    unclear = map_event(db, event(db, "Brent crude oil price outlook reviewed"), synthetic=True)
    c = by_symbol(unclear, "ATRL")[0]
    assert c.direction == "unknown" and any("does not state the direction" in m for m in c.missing)


def test_rate_rise_does_not_assume_every_bank_benefits(db):
    exposure(db, "HBL", "product", "lending")
    exposure(db, "LUCK", "debt", "KIBOR-linked borrowings")
    eid = event(db, "SBP raises policy rate by 100 basis points", event_type="monetary_policy")
    r = map_event(db, eid, synthetic=True)
    assert by_symbol(r, "HBL")[0].direction == "unknown"
    assert by_symbol(r, "LUCK")[0].direction == "negative"
    other_banks = [c for c in r.candidates if c.basis == "sector_only"]
    assert other_banks and all(c.direction == "unknown" for c in other_banks)


def test_pkr_depreciation_splits_exporters_and_importers(db):
    exposure(db, "SYS", "market", "export sales")
    exposure(db, "PSO", "input", "imported petroleum products")
    eid = event(db, "Rupee depreciates against the US dollar", event_type="economic_indicator")
    r = map_event(db, eid, synthetic=True)
    assert by_symbol(r, "SYS")[0].direction == "positive"
    assert by_symbol(r, "PSO")[0].direction == "negative"
    assert not [c for c in r.candidates if c.basis == "sector_only"]   # no sector blanket for PKR
    # word boundaries: "against" must not read as "gain"
    assert exposure_rules.change_of("Rupee depreciates against the dollar", "pkr_depreciation") == 1
    assert exposure_rules.change_of("Rupee gains against the dollar", "pkr_depreciation") == -1


def test_duty_rule_maps_only_companies_in_scope(db):
    exposure(db, "LUCK", "product", "cement")
    exposure(db, "EFERT", "product", "urea")
    eid = event(db, "Government raises federal excise duty on cement", event_type="tax_policy")
    r = map_event(db, eid, synthetic=True)
    assert by_symbol(r, "LUCK") and not by_symbol(r, "EFERT")


def test_contradictory_exposure_evidence_is_flagged(db):
    exposure(db, "PPL", "input", "crude oil")
    exposure(db, "PPL", "product", "crude oil")
    r = map_event(db, event(db, "Brent crude oil price rises"), synthetic=True)
    ppl = by_symbol(r, "PPL")
    assert {c.direction for c in ppl} == {"positive", "negative"}
    assert all(any("contradictory" in x for x in c.review_reasons) for c in ppl)
    assert all(c.evidence_status == "potential" for c in ppl)


# ------------------------------------------------------------------ evidence status
def test_unapproved_evidence_stays_unverified(db):
    exposure(db, "ATRL", "input", "crude oil", source="fxunapproved")
    r = map_event(db, event(db, "Brent crude oil price rises", source="fxunapproved"), synthetic=True)
    c = by_symbol(r, "ATRL")[0]
    assert c.evidence_status == "unverified" and any("not approved" in m for m in c.missing)
    assert any("material (direct) mapping" in x for x in c.review_reasons)


def test_strong_and_potential_depend_on_event_verification(db):
    exposure(db, "ATRL", "input", "crude oil")
    strong = map_event(db, event(db, "Brent crude oil price rises"), synthetic=True)
    assert by_symbol(strong, "ATRL")[0].evidence_status == "strongly_supported"
    single = map_event(db, event(db, "Brent crude oil price jumps", verification="single_source",
                                 magnitude="high"), synthetic=True)
    c = by_symbol(single, "ATRL")[0]
    assert c.evidence_status == "potential"
    assert any("single or unverified source" in x for x in c.review_reasons)


def test_rumour_and_disputed_events_need_review(db):
    exposure(db, "ATRL", "input", "crude oil")
    r = map_event(db, event(db, "Crude oil price may rise, sources said", stage="rumour", claim_type="rumour",
                            verification="disputed"), synthetic=True)
    c = by_symbol(r, "ATRL")[0]
    assert c.evidence_status == "potential"
    assert any("rumour" in x for x in c.review_reasons) and any("disputed" in x for x in c.review_reasons)


def test_confidence_is_not_proof(db):
    r = map_event(db, event(db, "Brent crude oil price rises"), synthetic=True)
    for c in r.candidates:   # no company exposure documented: nothing may be stronger than unverified
        assert c.evidence_status == "unverified" and "Confidence is not proof" in c.explanation


# ------------------------------------------------------------------ named companies
def test_named_companies_resolve_or_are_reported_unresolved(db):
    eid = event(db, "Lucky Cement Limited announces plant expansion; Engro comments",
                event_type="corporate_action", entities=("Lucky Cement Limited", "Engro", "Acme Widgets"))
    r = map_event(db, eid, synthetic=True)
    luck = by_symbol(r, "LUCK")[0]
    assert luck.level == "direct" and luck.direction == "unknown" and luck.exposure_evidence
    assert luck.evidence_status == "strongly_supported"   # named in approved, corroborated SYNTHETIC evidence
    statuses = {m["mention"]: m["status"] for m in r.unresolved_mentions}
    assert statuses == {"Engro": "ambiguous", "Acme Widgets": "unresolved"}


# ------------------------------------------------------------------ relationships
def test_unverified_subsidiary_maps_parent_indirectly_with_review(db):
    parent = repo.company_by_ticker(db, "ENGROH")["company_id"]
    child = repo.company_by_ticker(db, "EFERT")["company_id"]
    record_relationship(db, parent_company_id=parent, child_company_id=child, child_name="Engro Fertilizers",
                        relationship_type="subsidiary", evidence_status="unverified", recorded_by="test",
                        change_reason="SYNTHETIC FIXTURE", is_synthetic=True)
    exposure(db, "EFERT", "input", "natural gas")
    r = map_event(db, event(db, "OGRA raises natural gas price for fertiliser plants",
                            event_type="energy_policy"), synthetic=True)
    assert by_symbol(r, "EFERT")[0].direction == "negative"
    p = [c for c in by_symbol(r, "ENGROH") if c.rule_id == "R-REL-1"][0]
    assert p.level == "indirect" and p.evidence_status == "unverified"
    assert any("no cited source" in m for m in p.missing)
    stored = db.execute("SELECT evidence_status FROM exposure_candidates WHERE psx_symbol='ENGROH' "
                        "AND rule_id='R-REL-1'")[0]
    assert stored["evidence_status"] == "unverified"
    assert any("relationship is unverified" in x for x in p.review_reasons)
    assert any("ownership percentage" in m for m in p.missing)


def _rel(db, **kw):
    base = {"parent_company_id": repo.company_by_ticker(db, "ENGROH")["company_id"], "child_name": "Child Co",
            "relationship_type": "subsidiary", "evidence_status": "unverified", "recorded_by": "test",
            "change_reason": "SYNTHETIC FIXTURE", "is_synthetic": True}
    base.update(kw)
    return record_relationship(db, **base)


def test_relationship_constraints(db):
    a = repo.company_by_ticker(db, "ENGROH")["company_id"]
    with pytest.raises(DatabaseError):   # confirmed needs cited evidence
        _rel(db, evidence_status="confirmed")
    with pytest.raises(ValueError, match="cycle"):   # refused by the application first
        _rel(db, child_company_id=a, child_name="self")
    with pytest.raises(DatabaseError):   # and by the database for direct SQL
        db.execute("INSERT INTO company_relationships(parent_company_id, child_company_id, child_name, "
                   "relationship_type, evidence_status, change_reason, recorded_by, recorded_at_utc) "
                   "VALUES (?,?,?,?,?,?,?,?)", (a, a, "self", "subsidiary", "unverified", "x", "test", NOW))
    unapproved = item(db, "fxunapproved", "rel-u", "SYNTHETIC FIXTURE relationship")
    with pytest.raises(DatabaseError, match="approved"):   # strong status needs an approved source
        _rel(db, evidence_status="strongly_supported", source_item_id=unapproved, evidence_excerpt="x")
    with pytest.raises(DatabaseError, match="synthetic"):  # synthetic evidence on a non-synthetic row
        _rel(db, source_item_id=unapproved, evidence_excerpt="x", evidence_status="potential",
             is_synthetic=False)
    with pytest.raises(DatabaseError):   # invalid company reference
        _rel(db, parent_company_id="cmp-doesnotexist")


def test_relationships_are_append_only_with_correction_history(db):
    child = repo.company_by_ticker(db, "EFERT")["company_id"]
    rid = _rel(db, child_company_id=child, child_name="Engro Fertilizers", ownership_pct=50.0)
    with pytest.raises(DatabaseError):
        db.execute("UPDATE company_relationships SET ownership_pct = 60 WHERE relationship_id = ?", (rid,))
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM company_relationships")
    with pytest.raises(DatabaseError, match="supersede"):   # duplicate current relationship
        _rel(db, child_company_id=child, child_name="Engro Fertilizers")
    fixed = _rel(db, child_company_id=child, child_name="Engro Fertilizers", ownership_pct=56.0,
                 supersedes=rid, change_reason="SYNTHETIC correction")
    gone = _rel(db, child_company_id=child, child_name="Engro Fertilizers", evidence_status="rejected",
                supersedes=fixed, change_reason="SYNTHETIC rejection")
    with pytest.raises(DatabaseError):   # a row can be superseded only once
        _rel(db, child_company_id=child, child_name="Engro Fertilizers", supersedes=rid)
    with pytest.raises(DatabaseError, match="same parent and child"):
        _rel(db, child_name="Someone Else", supersedes=gone)
    hist = exposure_mapping.relationship_history(db, rid)
    assert [h["relationship_id"] for h in hist] == [rid, fixed, gone]
    assert [h["ownership_pct"] for h in hist][:2] == [50.0, 56.0]
    assert hist[-1]["evidence_status"] == "rejected"
    current = db.execute("SELECT relationship_id FROM current_company_relationships")
    assert [r["relationship_id"] for r in current] == [gone]   # rejected stays traceable as the current row


def test_relationship_cycles_are_refused(db):
    a, b, c = (repo.company_by_ticker(db, t)["company_id"] for t in ("ENGROH", "EFERT", "EPCL"))
    _rel(db, parent_company_id=a, child_company_id=b, child_name="B")
    _rel(db, parent_company_id=b, child_company_id=c, child_name="C")
    with pytest.raises(DatabaseError, match="cycle"):      # direct reversal: refused by the database
        db.execute("INSERT INTO company_relationships(parent_company_id, child_company_id, child_name, "
                   "relationship_type, evidence_status, change_reason, recorded_by, recorded_at_utc) "
                   "VALUES (?,?,?,?,?,?,?,?)", (b, a, "A", "subsidiary", "unverified", "x", "test", NOW))
    with pytest.raises(ValueError, match="cycle"):         # deeper cycle: refused by the application
        _rel(db, parent_company_id=c, child_company_id=a, child_name="A")


# ------------------------------------------------------------------ persistence, revisions, review
def test_persistence_is_idempotent_and_revisions_are_kept(db):
    exposure(db, "ATRL", "input", "crude oil")
    eid = event(db, "Brent crude oil price rises")
    first = map_event(db, eid, synthetic=True)
    again = map_event(db, eid, synthetic=True)
    assert first.stored["created"] > 0 and again.stored == {"created": 0, "revised": 0, "unchanged":
                                                             first.stored["created"]}
    db.execute("UPDATE sources SET lifecycle_status='DISABLED', enabled=0 WHERE source_id='fxapproved'")
    third = map_event(db, eid, synthetic=True)
    assert third.stored["revised"] >= 1
    row = db.execute("SELECT * FROM exposure_candidates WHERE psx_symbol='ATRL' AND rule_id='R-OIL-1'")[0]
    assert row["evidence_status"] == "unverified" and row["current_revision"] == 3
    assert row["is_synthetic"] == 1
    hist = db.execute("SELECT revision_no, evidence_status FROM exposure_candidate_revisions "
                      "WHERE candidate_id=? ORDER BY revision_no", (row["candidate_id"],))
    assert [h["evidence_status"] for h in hist] == ["unverified", "strongly_supported", "unverified"]
    assert [h["revision_no"] for h in hist] == [1, 2, 3]
    assert row["ruleset_version"] == exposure_rules.RULESET_VERSION and row["schema_version"]


def test_review_accepts_only_strong_evidence_and_promotes_to_event_companies(db):
    exposure(db, "ATRL", "input", "crude oil")
    eid = event(db, "Brent crude oil price rises")
    map_event(db, eid, synthetic=True)
    strong = db.execute("SELECT candidate_id FROM exposure_candidates "
                        "WHERE psx_symbol='ATRL'")[0]["candidate_id"]
    weak = db.execute("SELECT candidate_id FROM exposure_candidates WHERE evidence_status='unverified' "
                      "LIMIT 1")[0]["candidate_id"]
    with pytest.raises(ValueError, match="cannot accept"):
        review(db, weak, "accept", reviewer="owner", notes="looks right")
    with pytest.raises(ValueError, match="notes"):
        review(db, strong, "accept", reviewer="owner", notes=" ")
    done = review(db, strong, "accept", reviewer="owner", notes="checked fixture evidence")
    assert done["evidence_status"] == "confirmed" and done["review_status"] == "accepted"
    link = db.execute("SELECT * FROM event_companies WHERE event_id=?", (eid,))[0]
    assert link["reviewer_status"] == "accepted" and link["impact_direction"] == "negative"
    revs = db.execute("SELECT review_status, last_review_id FROM exposure_candidate_revisions "
                      "WHERE candidate_id=? ORDER BY revision_no DESC LIMIT 1", (strong,))[0]
    rv = db.execute("SELECT * FROM exposure_reviews WHERE review_id=?", (done["last_review_id"],))[0]
    assert revs["review_status"] == "accepted" and revs["last_review_id"] == rv["review_id"]
    assert rv["decision"] == "accept" and rv["reviewer"] == "owner" and rv["evidence_status_at_decision"] == \
        "strongly_supported"
    rejected = review(db, weak, "reject", reviewer="owner", notes="sector membership only")
    assert rejected["evidence_status"] == "rejected"
    with pytest.raises(DatabaseError):   # a decided candidate cannot be flipped without a new review
        db.execute("UPDATE exposure_candidates SET review_status='pending', evidence_status='unverified', "
                   "current_revision=?, change_reason='x', changed_by='x', updated_at_utc=? "
                   "WHERE candidate_id=?",
                   (rejected["current_revision"] + 1, NOW, weak))
    assert map_event(db, eid, synthetic=True).stored["revised"] == 0   # human decisions are not overwritten
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM exposure_reviews")
    with pytest.raises(DatabaseError):
        db.execute("UPDATE exposure_reviews SET decision='accept'")


def _candidate_cols(row):
    skip = {"candidate_id"}
    return [k for k in row if k not in skip]


def _raw_insert(db, row, **over):
    vals = dict(row, **over)
    cols = _candidate_cols(row)
    db.execute(f"INSERT INTO exposure_candidates({', '.join(cols)}) "  # noqa: S608 - fixed column names
               f"VALUES ({', '.join('?' * len(cols))})", [vals[k] for k in cols])


def _strong_candidate(db):
    exposure(db, "ATRL", "input", "crude oil")
    eid = event(db, "Brent crude oil price rises")
    map_event(db, eid, synthetic=True)
    return eid, db.execute("SELECT * FROM exposure_candidates "
                           "WHERE psx_symbol='ATRL' AND rule_id='R-OIL-1'")[0]


def test_every_candidate_has_revision_one_written_by_the_database(db):
    eid, row = _strong_candidate(db)
    for c in db.execute("SELECT candidate_id FROM exposure_candidates"):
        revs = db.execute("SELECT revision_no FROM exposure_candidate_revisions WHERE candidate_id=? "
                          "ORDER BY revision_no", (c["candidate_id"],))
        assert revs and revs[0]["revision_no"] == 1
    _raw_insert(db, row, mechanism="raw SQL insert", current_revision=1, evidence_status="unverified",
                review_status="needs_review", last_review_id=None)
    new = db.execute("SELECT candidate_id FROM exposure_candidates WHERE mechanism='raw SQL insert'")[0]
    assert db.execute("SELECT revision_no FROM exposure_candidate_revisions WHERE candidate_id=?",
                      (new["candidate_id"],))[0]["revision_no"] == 1   # even raw inserts get revision 1
    with pytest.raises(DatabaseError, match="revision 1"):
        _raw_insert(db, row, mechanism="starts at 5", current_revision=5, evidence_status="unverified",
                    review_status="needs_review", last_review_id=None)


def test_direct_sql_cannot_create_strong_or_confirmed_candidates(db):
    eid, row = _strong_candidate(db)
    for status, review_status in (("strongly_supported", "pending"), ("potential", "pending"),
                                  ("confirmed", "accepted")):
        with pytest.raises(DatabaseError):
            _raw_insert(db, row, mechanism=f"forged {status}", current_revision=1, evidence_status=status,
                        review_status=review_status, last_review_id=None)


def test_status_cannot_be_raised_or_confirmed_without_real_evidence_and_review(db):
    eid, row = _strong_candidate(db)
    cid, rev = row["candidate_id"], row["current_revision"]
    upd = ("UPDATE exposure_candidates SET evidence_status=?, review_status=?, current_revision=?, "
           "change_reason='forged', changed_by='attacker', updated_at_utc=? WHERE candidate_id=?")
    with pytest.raises(DatabaseError, match="acceptance review"):     # confirmed by flipping fields
        db.execute(upd, ("confirmed", "accepted", rev + 1, NOW, cid))
    with pytest.raises(DatabaseError, match="next revision"):         # skipping the revision
        db.execute("UPDATE exposure_candidates SET confidence=0.9 WHERE candidate_id=?", (cid,))
    sector = db.execute("SELECT * FROM exposure_candidates WHERE evidence_status='unverified' "
                        "AND exposure_level='indirect' LIMIT 1")[0]
    with pytest.raises(DatabaseError, match="company-specific evidence"):   # no evidence linked
        db.execute(upd, ("strongly_supported", "pending", sector["current_revision"] + 1, NOW,
                         sector["candidate_id"]))
    with pytest.raises(DatabaseError):   # a forged review: accept of a non-strong candidate
        db.execute("INSERT INTO exposure_reviews(candidate_id, decision, reviewer, notes, decided_at_utc, "
                   "evidence_status_at_decision) VALUES (?,?,?,?,?,?)",
                   (sector["candidate_id"], "accept", "attacker", "x", NOW, "unverified"))
    with pytest.raises(DatabaseError):   # review must state the true current status
        db.execute("INSERT INTO exposure_reviews(candidate_id, decision, reviewer, notes, decided_at_utc, "
                   "evidence_status_at_decision) VALUES (?,?,?,?,?,?)",
                   (sector["candidate_id"], "accept", "attacker", "x", NOW, "strongly_supported"))
    for bad in (("", NOW), ("owner", "yesterday")):     # reviewer identity and timestamp are required
        with pytest.raises(DatabaseError):
            db.execute("INSERT INTO exposure_reviews(candidate_id, decision, reviewer, notes, "
                       "decided_at_utc, evidence_status_at_decision) VALUES (?,?,?,?,?,?)",
                       (cid, "reject", bad[0], "x", bad[1], "strongly_supported"))
    with pytest.raises(DatabaseError, match="confirmed exposure candidate"):   # event_companies shortcut
        db.execute("INSERT INTO event_companies(event_id, company_id, exposure_type, rationale, "
                   "reviewer_status, created_at_utc) VALUES (?,?,?,?,?,?)",
                   (eid, row["company_id"], "direct", "forged", "accepted", NOW))


def test_downgraded_evidence_blocks_strong_status(db):
    eid, row = _strong_candidate(db)
    db.execute("UPDATE sources SET lifecycle_status='DISABLED', enabled=0 WHERE source_id='fxapproved'")
    with pytest.raises(DatabaseError, match="approved"):
        db.execute("UPDATE exposure_candidates SET explanation='x', current_revision=?, change_reason='t', "
                   "changed_by='t', updated_at_utc=? WHERE candidate_id=?",
                   (row["current_revision"] + 1, NOW, row["candidate_id"]))


def test_fabricated_and_foreign_evidence_links_are_refused(db):
    eid, row = _strong_candidate(db)
    other_eid = event(db, "Unrelated synthetic event about cement", event_type="other")
    other_ev = db.execute("SELECT evidence_id, source_item_id FROM event_evidence WHERE event_id=?",
                          (other_eid,))[0]
    ins = ("INSERT INTO exposure_candidate_evidence(candidate_id, role, event_evidence_id, "
           "company_exposure_id, relationship_id, source_item_id, added_at_utc) VALUES (?,?,?,?,?,?,?)")
    cid = row["candidate_id"]
    with pytest.raises(DatabaseError):          # fabricated id (foreign key / trigger)
        db.execute(ins, (cid, "company_specific", 99999, None, None, other_ev["source_item_id"], NOW))
    with pytest.raises(DatabaseError, match="candidate's event"):     # evidence from another event
        db.execute(ins, (cid, "claim", other_ev["evidence_id"], None, None, other_ev["source_item_id"], NOW))
    other_x = exposure(db, "LUCK", "input", "coal")
    sid = db.execute("SELECT source_item_id FROM company_exposures WHERE exposure_id=?", (other_x,))[0]
    with pytest.raises(DatabaseError, match="candidate's company"):   # another company's exposure
        db.execute(ins, (cid, "company_specific", None, other_x, None, sid["source_item_id"], NOW))
    with pytest.raises(DatabaseError):          # two targets in one link
        db.execute(ins, (cid, "company_specific", other_ev["evidence_id"], other_x, None, 1, NOW))
    with pytest.raises(DatabaseError):          # evidence links are append-only
        db.execute("DELETE FROM exposure_candidate_evidence")


def test_synthetic_evidence_cannot_support_a_real_mapping(db):
    exposure(db, "ATRL", "input", "crude oil")
    eid = event(db, "Brent crude oil price rises")
    with pytest.raises(DatabaseError, match="synthetic"):
        map_event(db, eid, synthetic=False)
    assert db.execute("SELECT COUNT(*) n FROM exposure_candidates")[0]["n"] == 0   # whole batch rolled back
    assert db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions")[0]["n"] == 0


def test_revisions_are_immutable_and_cannot_be_forged(db):
    eid, row = _strong_candidate(db)
    with pytest.raises(DatabaseError):
        db.execute("UPDATE exposure_candidate_revisions SET evidence_status='confirmed'")
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM exposure_candidate_revisions")
    with pytest.raises(DatabaseError, match="current revision only"):
        db.execute("INSERT INTO exposure_candidate_revisions(candidate_id, revision_no, recorded_at_utc, "
                   "evidence_status, review_status, snapshot_json, change_reason, changed_by) "
                   "VALUES (?,?,?,?,?,?,?,?)", (row["candidate_id"], row["current_revision"] + 1, NOW,
                                                "confirmed", "accepted", "{}", "forged", "attacker"))
    with pytest.raises(DatabaseError):
        db.execute("DELETE FROM exposure_candidates")


def test_candidate_identity_and_duplicates(db):
    eid, row = _strong_candidate(db)
    with pytest.raises(DatabaseError, match="identity"):
        db.execute("UPDATE exposure_candidates SET company_id='cmp-luck', current_revision=?, "
                   "change_reason='x', changed_by='x', updated_at_utc=? WHERE candidate_id=?",
                   (row["current_revision"] + 1, NOW, row["candidate_id"]))
    with pytest.raises(DatabaseError):   # duplicate mapping
        _raw_insert(db, row, current_revision=1, evidence_status="unverified", review_status="needs_review",
                    last_review_id=None)
    with pytest.raises(DatabaseError):   # invalid company reference
        _raw_insert(db, row, company_id="cmp-nope", mechanism="m2", current_revision=1,
                    evidence_status="unverified", review_status="needs_review", last_review_id=None)


def test_failed_batch_leaves_no_candidate_or_revision(db):
    eid, row = _strong_candidate(db)
    before = (db.execute("SELECT COUNT(*) n FROM exposure_candidates")[0]["n"],
              db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions")[0]["n"])
    cols = _candidate_cols(row)
    good = dict(row, mechanism="batch test", current_revision=1, evidence_status="unverified",
                review_status="needs_review", last_review_id=None)
    with pytest.raises(DatabaseError):
        db.batch([(f"INSERT INTO exposure_candidates({', '.join(cols)}) "  # noqa: S608 - fixed column names
                   f"VALUES ({', '.join('?' * len(cols))})", [good[k] for k in cols]),
                  ("INSERT INTO exposure_candidate_evidence(candidate_id, role, event_evidence_id, "
                   "source_item_id, added_at_utc) SELECT candidate_id, 'claim', 99999, 1, ? "
                   "FROM exposure_candidates WHERE mechanism = 'batch test'", (NOW,))])
    after = (db.execute("SELECT COUNT(*) n FROM exposure_candidates")[0]["n"],
             db.execute("SELECT COUNT(*) n FROM exposure_candidate_revisions")[0]["n"])
    assert after == before


# ------------------------------------------------------------------ LLM suggestions (fixture provider only)
def suggestion(**over):
    s = {"company_mention": "Attock Refinery Limited", "exposure_category": "operational",
         "exposure_subtype": "raw_material_procurement", "exposure_level": "direct",
         "impact_direction": "NEGATIVE", "mechanism": "buys crude oil",
         "evidence_quote": "ATRL input crude oil"}
    s.update(over)
    return s


def test_llm_suggestions_are_validated_and_stay_suggestions(db):
    exposure(db, "ATRL", "input", "crude oil")
    eid = event(db, "Brent crude oil price rises")
    payload = {"missing_evidence": [], "suggestions": [
        suggestion(),
        suggestion(evidence_quote="ATRL owns three refineries abroad"),       # invented fact
        suggestion(company_mention="Engro", evidence_quote="Brent crude"),     # ambiguous company
        suggestion(exposure_subtype="price_target"),                            # not in taxonomy
        {"company_mention": "ATRL"},                                            # malformed
    ]}
    gw = LLMGateway(FixtureProvider({"Brent": payload}), PRICE, db=db, sleep=lambda s: None)
    r = suggest_with_llm(db, eid, gw, synthetic=True)
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c.origin == "llm_suggestion" and c.evidence_status == "potential"
    assert c.model == "fixture-model" and c.prompt_version == "1.0.0"
    assert any("LLM suggestion" in x for x in c.review_reasons)
    reasons = " | ".join(x["reason"] for x in r.rejected_suggestions)
    assert "not found in stored evidence" in reasons and "ambiguous" in reasons
    assert "invalid category/subtype" in reasons and "does not match the schema" in reasons
    audit = db.execute("SELECT evidence_status, review_status FROM exposure_candidates "
                       "WHERE origin='llm_suggestion' AND evidence_status='rejected'")
    assert audit and audit[0]["review_status"] == "rejected"   # rejected suggestion kept for audit
    assert db.execute("SELECT COUNT(*) n FROM llm_calls WHERE prompt_id='exposure_candidate'")[0]["n"] == 1


def test_llm_unavailable_or_kill_switch_produces_nothing(db, monkeypatch):
    eid = event(db, "Brent crude oil price rises")
    r = suggest_with_llm(db, eid, LLMGateway(ClaudeProvider(), PRICE))
    assert not r.candidates and "not_connected" in r.rejected_suggestions[0]["reason"]
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "1")
    fx = FixtureProvider({"Brent": {"missing_evidence": [], "suggestions": [suggestion()]}})
    r2 = suggest_with_llm(db, eid, LLMGateway(fx, PRICE))
    assert not r2.candidates and fx.calls == 0 and "kill_switch" in r2.rejected_suggestions[0]["reason"]


def test_invalid_llm_output_is_rejected(db):
    eid = event(db, "Brent crude oil price rises")
    r = suggest_with_llm(db, eid, LLMGateway(FixtureProvider({"Brent": "not json"}), PRICE))
    assert not r.candidates and "invalid model output" in r.rejected_suggestions[0]["reason"]


# ------------------------------------------------------------------ licensing safeguard
def test_psx_profile_text_is_never_used_as_exposure_evidence():
    for mod in (exposure_mapping, entity_resolution, exposure_rules):
        assert "business_summary" not in inspect.getsource(mod)
