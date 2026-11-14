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
