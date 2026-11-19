import json
import urllib.error

import pytest

from engines import setups_forward as sf
from engines import tracker_view as tv


def good_payload():
    snaps = [{"day": "2026-11-19", "group": ["A"], "tracks": {t: ["A"] for t in sf.TRACKS}}]
    return sf.results_payload(
        snaps, {t: {h: [] for h in sf.HORIZONS} for t in sf.TRACKS}, "2026-11-19T12:00:00Z"
    )


def test_a_valid_results_file_is_read_and_the_reading_says_too_few_until_twenty():
    seen = {}

    def get(url, headers):
        seen["url"], seen["headers"] = url, headers
        return json.dumps(good_payload())

    p = tv.fetch("tok", "owner/repo", get)
    assert "ref=data/setups-forward" in seen["url"] and seen["headers"]["Authorization"] == "Bearer tok"
    rows = tv.table(p)
    assert rows and all("too few snapshots" in r["Reading"] for r in rows)
    assert tv.reading({"snapshots_scored": 25, "avg_excess": 0.4}) == "ahead of the group on average"
    assert tv.reading({"snapshots_scored": 25, "avg_excess": -0.4}) == "behind the group on average"
    assert tv.reading({"snapshots_scored": 25, "avg_excess": None}) == "no result yet"


def test_a_missing_token_a_bad_schema_and_http_errors_fail_closed_without_leaking_the_token():
    with pytest.raises(tv.TrackerError, match="not configured"):
        tv.fetch("", "owner/repo", lambda *_: "{}")
    bad = dict(good_payload(), schema_version=99)
    with pytest.raises(tv.TrackerError, match="unsupported"):
        tv.fetch("tok", "o/r", lambda *_: json.dumps(bad))
    dup = dict(good_payload(), snapshot_days=["2026-11-19", "2026-11-19"])
    with pytest.raises(tv.TrackerError, match="duplicate"):
        tv.validate(dup)

    def forbidden(url, headers):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    with pytest.raises(tv.TrackerError) as exc:
        tv.fetch("SECRET-TOKEN-123", "o/r", forbidden)
    assert "403" in str(exc.value) and "SECRET-TOKEN-123" not in str(exc.value)
    with pytest.raises(tv.TrackerError, match="not valid JSON"):
        tv.fetch("tok", "o/r", lambda *_: "<html>")
