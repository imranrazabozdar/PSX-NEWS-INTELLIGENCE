"""Date intervals for undated videos: what a title can and cannot say, and how order tightens it."""

from __future__ import annotations

import json
from datetime import date

import pytest

from database.connection import SQLiteDatabase
from engines import video_dating as vd
from scripts import build_video_dating as bvd


def vids(*titles):
    return [{"video_id": f"v{i}", "title": t, "archive_position": i} for i, t in enumerate(titles)]


def test_a_title_with_an_exact_day_bounds_the_video_to_a_few_days():
    a = vd.anchor_from_title("War Time Investing - 16 March 2026")
    assert a and a.basis == "title_exact_day" and (a.hi - a.lo).days <= 5


def test_a_budget_title_is_bounded_to_june_of_that_year():
    a = vd.anchor_from_title("Budget 2026 for PSX Investors")
    assert (a.lo, a.hi) == (date(2026, 6, 1), date(2026, 6, 30))
    other = vd.anchor_from_title("Don't Lose Money: 2026 Budget Moves for Every Investor")
    assert (other.lo, other.hi) == (a.lo, a.hi)  # the year may come before or after the word


def test_a_year_in_a_title_is_a_wide_bound_not_the_upload_year():
    a = vd.anchor_from_title("Best Cement Company of Pakistan in 2025")
    assert a.basis == "title_year" and (a.hi - a.lo).days > 600  # subject year, deliberately wide


def test_a_title_with_no_date_has_no_anchor():
    assert vd.anchor_from_title("Fauji Cement: The One Risk Most Investors Are Missing") is None


def test_order_gives_an_undated_video_an_interval_from_its_neighbours():
    out = vd.estimate(vids("Plain newest", "Plain middle", "Budget 2026 stuff", "Plain older"))
    middle, older = out[1], out[3]
    assert middle.basis == "order_bounded"
    # newer than the Budget 2026 video, so no earlier than June 2026 and capped only by the capture date
    assert middle.date_from == date(2026, 6, 1) and middle.date_to == vd.CAPTURE_DATE
    # older than it, so no later than the end of June 2026, and nothing older constrains how early
    assert older.date_to == date(2026, 6, 30) and older.date_from is None


def test_an_older_video_is_never_given_a_later_bound_than_a_newer_one():
    out = vd.estimate(vids("a", "Budget 2026", "b", "Budget 2024", "c"))
    uppers = [d.date_to for d in out]
    assert uppers == sorted(uppers, reverse=True)


def test_contradictory_anchors_are_refused_not_smoothed_over():
    # the older video claims a date after the newer one: the ordering and the titles cannot both be right
    with pytest.raises(vd.DatingConflict):
        vd.estimate(vids("Budget 2024", "Budget 2026"))


def test_the_capture_date_is_a_ceiling():
    out = vd.estimate(vids("anything"))
    assert out[0].date_to == vd.CAPTURE_DATE


def test_a_verified_date_replaces_the_estimate_and_keeps_the_basis_honest():
    rows = bvd.build([{"video_id": "v0", "title": "x", "archive_position": 0}], {"v0": "2026-03-05"})
    assert rows[0]["date_from"] == rows[0]["date_to"] == "2026-03-05" and rows[0]["basis"] == "verified"


def test_loading_is_a_dry_run_by_default_and_idempotent_when_applied():
    rows = bvd.build([{"video_id": "v0", "title": "Budget 2026", "archive_position": 0}])
    db = SQLiteDatabase()
    bvd.apply(rows, write=False, db=db)
    assert not db.execute("SELECT name FROM sqlite_master WHERE name = 'video_dating'")
    bvd.apply(rows, write=True, db=db)
    bvd.apply(rows, write=True, db=db)
    assert db.execute("SELECT COUNT(*) AS n FROM video_dating")[0]["n"] == 1


def test_the_shipped_index_dates_every_video_without_conflict():
    index = json.loads((bvd.ARN / "video_index.json").read_text(encoding="utf-8"))
    assert len(vd.estimate(index)) == 215


def test_yt_dlp_plain_output_is_accepted_and_unusable_lines_are_skipped(tmp_path):
    f = tmp_path / "dates.txt"
    f.write_text("abc123 20260305\nxyz789 NA\nlmn456,2025-11-02\nbroken\n", encoding="utf-8")
    assert bvd.read_verified(f) == {"abc123": "2026-03-05", "lmn456": "2025-11-02"}


def test_a_json_date_map_is_accepted_too(tmp_path):
    f = tmp_path / "dates.json"
    f.write_text(json.dumps({"abc": "2026-01-02"}), encoding="utf-8")
    assert bvd.read_verified(f) == {"abc": "2026-01-02"}
