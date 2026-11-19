from scripts import mettis_timestamp_impact as mt


def row(stored, collected):
    return {"url": "https://m/x", "title": "T", "published_at": stored, "fetched_at": collected}


def test_the_correction_layer_is_versioned_read_only_and_marks_what_it_cannot_verify():
    view = mt.corrected_view(
        [
            row(
                "2026-11-17T13:32:19Z", "2026-11-17T09:00:47Z"
            ),  # stored 4.5 h after collection: offset visible
            row("2026-11-10T09:00:00Z", "2026-11-17T09:00:00Z"),  # collected a week later: cannot be checked
            row("2026-11-18T05:00:00Z", "2026-11-17T22:30:00Z"),  # still future after the fix: check
            row("2026-11-18T03:30:00Z", "2026-11-17T23:50:00Z"),  # fix moves it across midnight
        ]
    )
    assert [v["validation_status"] for v in view] == ["valid", "unverifiable", "check", "valid"]
    first = view[0]
    assert (
        first["original_utc"] == "2026-11-17T13:32:19Z" and first["corrected_utc"] == "2026-11-17T08:32:19Z"
    )
    assert first["version"] == mt.VERSION and "Asia/Karachi" in first["source_timezone"] and first["method"]
    assert view[3]["calendar_day_changes"] is True and view[0]["calendar_day_changes"] is False
