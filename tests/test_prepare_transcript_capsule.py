"""Transcript capsule preparation: undated-source handling and near-duplicate collapsing."""

from __future__ import annotations

import json

import pytest

from engines import research_facts as rf
from scripts import prepare_transcript_capsule as prep

GOOD = {
    "company": "LUCK", "topic": "commentary.thesis",
    "fact_text": "The analyst saw Lucky's renewable investment as a durable cost advantage.",
    "value": None, "unit": None, "period": None,
    "source_name": "Abdul Rehman Najam, 'Cement Explained' (YouTube transcript, undated)",
    "source_url": "https://www.youtube.com/watch?v=abc", "video_id": "abc",
    "confidence": "analyst_view",
}


def test_the_capture_date_is_recorded_and_never_passed_off_as_a_publication_date():
    row = prep.convert(GOOD)
    assert row["source_date"] == prep.ARCHIVE_CAPTURE_DATE
    assert "undated" in row["source_name"].lower()
    assert row["as_of"] is None  # we do not know when this was said


def test_a_source_that_does_not_declare_itself_undated_is_refused():
    with pytest.raises(rf.ResearchFactError, match="undated"):
        prep.convert(dict(GOOD, source_name="Abdul Rehman Najam, 'Cement Explained'"))


def test_a_real_title_containing_an_ellipsis_survives_the_placeholder_check():
    """"Sazgar Looks Undervalued... But" is a real title, not a placeholder I left behind."""
    row = prep.convert(dict(GOOD, source_name="Abdul Rehman Najam, 'Sazgar Looks Undervalued... But "
                                              "This Risk Changes Everything' (YouTube transcript, undated)"))
    assert "..." not in row["source_name"] and "…" in row["source_name"]


def test_the_video_id_key_does_not_leak_into_a_schema_row():
    assert set(prep.convert(GOOD)) == set(rf.COLUMNS)


def test_an_oversized_or_unsourced_row_is_refused_not_truncated_silently():
    with pytest.raises(rf.ResearchFactError):
        prep.convert(dict(GOOD, fact_text="x" * 400))
    with pytest.raises(rf.ResearchFactError):
        prep.convert(dict(GOOD, company=""))


# ---------- near-duplicate collapsing: one analyst repeating himself must leave ONE row

def test_a_restatement_of_the_same_point_is_collapsed(tmp_path):
    a = dict(GOOD, fact_text="Energy is roughly seventy percent of a cement maker's production cost.")
    b = dict(GOOD, fact_text="Roughly seventy percent of cement production cost is energy.")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(json.dumps([a, b]), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json")
    assert len(json.loads((tmp_path / "out.json").read_text())) == 1


def test_two_genuinely_different_points_both_survive(tmp_path):
    a = dict(GOOD, fact_text="Energy is roughly seventy percent of a cement maker's production cost.")
    b = dict(GOOD, fact_text="Limestone mining leases keep raw material near five percent of cost.")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(json.dumps([a, b]), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json")
    assert len(json.loads((tmp_path / "out.json").read_text())) == 2


def test_the_same_sentence_about_a_different_company_is_not_a_duplicate(tmp_path):
    a = dict(GOOD, company="LUCK", fact_text="The analyst saw its captive power as a cost advantage.")
    b = dict(GOOD, company="FCCL", fact_text="The analyst saw its captive power as a cost advantage.")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(json.dumps([a, b]), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json")
    assert len(json.loads((tmp_path / "out.json").read_text())) == 2


def test_malformed_rows_are_dropped_and_counted_without_stopping_the_batch(tmp_path, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(
        json.dumps([GOOD, dict(GOOD, company=""), dict(GOOD, confidence="guess")]), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json")
    assert len(json.loads((tmp_path / "out.json").read_text())) == 1
    assert "dropped as malformed : 2" in capsys.readouterr().out


# ---------- one company, one entity key: a split profile is as bad as a duplicate row

def test_a_prose_name_folds_onto_the_ticker_already_in_use():
    alias = prep.build_alias_map(["HALEON", "Haleon Pakistan", "LUCK"])
    assert alias == {"Haleon Pakistan": "HALEON"}


def test_folding_ignores_corporate_suffixes_and_punctuation():
    assert prep.entity_key("Haleon Pakistan Limited") == prep.entity_key("HALEON")
    assert prep.entity_key("Ghani Dairies Ltd.") == prep.entity_key("Ghani Dairies")


def test_two_genuinely_different_companies_are_never_folded_together():
    assert prep.build_alias_map(["LUCK", "FCCL", "Lucky Cement"]) == {}


def test_a_company_named_only_one_way_is_left_alone():
    assert prep.build_alias_map(["Ghani Dairies"]) == {}


def test_folded_rows_land_under_one_entity_in_the_capsule(tmp_path):
    rows = [dict(GOOD, company="HALEON", fact_text="Panadol carries most of its volume."),
            dict(GOOD, company="Haleon Pakistan", topic="commentary.risk",
                 fact_text="Its imported raw material leaves it exposed to the rupee.")]
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(json.dumps(rows), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json")
    out = json.loads((tmp_path / "out.json").read_text())
    assert {r["company"] for r in out} == {"HALEON"} and len(out) == 2


# ---------- provenance: a channel is not a speaker

def test_every_row_is_attributed_to_the_channel_not_assumed_to_be_its_owner_speaking():
    row = prep.convert(GOOD)
    assert row["source_name"].startswith("Abdul Rehman Najam channel,")
    assert "speaker may be" not in row["source_name"]


def test_a_host_or_guest_led_title_is_flagged_so_the_view_is_not_credited_to_the_owner():
    for title in ("Shafy's Weekly Roundup", "Salary to Financial Freedom ft Ammar Siddiqui",
                  "How to become a Value Investor - Irfan Khan explains"):
        source = f"Abdul Rehman Najam, '{title}' (YouTube transcript, undated)"
        row = prep.convert(dict(GOOD, source_name=source))
        assert "speaker may be a host or guest" in row["source_name"], title
        assert "undated" in row["source_name"]


def test_attribution_is_idempotent_so_a_second_pass_does_not_stack_notes():
    once = prep.convert(dict(GOOD, source_name="ARN, 'Shafy Weekly' (YouTube transcript, undated)"))
    twice = prep.convert(dict(once))
    assert once["source_name"] == twice["source_name"]


# ---------- reproducible without Claude: several folders, and a list of ruled-out rows

def test_several_input_folders_combine_into_one_capsule(tmp_path):
    for name, text in (("a", "Energy is roughly seventy percent of production cost."),
                       ("b", "Limestone from owned leases keeps raw material near five percent.")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.json").write_text(json.dumps([dict(GOOD, fact_text=text)]), encoding="utf-8")
    prep.build([tmp_path / "a", tmp_path / "b"], tmp_path / "out.json")
    assert len(json.loads((tmp_path / "out.json").read_text())) == 2


def test_a_ruled_out_row_is_left_out_but_a_same_text_row_from_another_video_is_kept(tmp_path):
    text = "Energy is roughly seventy percent of production cost."
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.json").write_text(json.dumps([
        dict(GOOD, fact_text=text, video_id="bad"),
        dict(GOOD, fact_text=text, video_id="good", company="FCCL")]), encoding="utf-8")
    ex = tmp_path / "ex.json"
    ex.write_text(json.dumps([{"video_id": "bad", "fact_text": text}]), encoding="utf-8")
    prep.build(tmp_path / "in", tmp_path / "out.json", ex)
    out = json.loads((tmp_path / "out.json").read_text())
    assert [r["company"] for r in out] == ["FCCL"]
