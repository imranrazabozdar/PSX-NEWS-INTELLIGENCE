from datetime import date, timedelta

from engines import setups_forward as sf


def bars(n_stocks=30, n_days=60, up=()):
    start = date(2026, 8, 1)
    out = {}
    for s in range(n_stocks):
        sym = f"S{s:02d}"
        px = 100.0
        rows = []
        for d in range(n_days):
            px *= 1.004 if sym in up else 0.999
            rows.append(
                {"trade_date": (start + timedelta(days=d)).isoformat(), "close": px, "volume": 2_000_000.0}
            )
        out[sym] = rows
    return out


def result_for(bars_, winners):
    rows = {s: {"symbol": s} for s in bars_}
    top = [{"symbol": s} for s in winners]
    return {"rows": rows, "technical": top, "fundamental": top, "combined": top}


def test_a_snapshot_records_the_tops_and_the_whole_group_and_evaluation_uses_only_later_prices():
    b = bars(up=("S00", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09"))
    winners = [f"S{i:02d}" for i in range(10)]
    day = "2026-09-10"
    snap = sf.snapshot(result_for(b, winners), b, day)
    assert snap["group"] == sorted(b) and snap["tracks"]["technical"] == winners
    assert len(snap["tracks"]["technical_novol"]) == 10
    scored = sf.evaluate([snap], b)
    row = scored["technical"][5][0]
    assert row["top"] > row["group"] and row["excess"] > 0  # winners kept winning after the snapshot
    assert row["day"] == day


def test_a_snapshot_too_recent_to_score_is_left_out_not_counted_as_zero():
    b = bars()
    last = max(r["trade_date"] for r in b["S00"])
    snap = sf.snapshot(result_for(b, [f"S{i:02d}" for i in range(10)]), b, last)
    scored = sf.evaluate([snap], b)
    assert all(scored[t][h] == [] for t in sf.TRACKS for h in sf.HORIZONS)
    text = sf.report([snap], scored)
    assert "n/a" in text and "1 daily snapshots" in text and "Not advice" in text


def test_report_averages_the_scored_snapshots():
    b = bars(up=tuple(f"S{i:02d}" for i in range(10)))
    snaps = [
        sf.snapshot(result_for(b, [f"S{i:02d}" for i in range(10)]), b, d)
        for d in ("2026-09-01", "2026-09-02")
    ]
    text = sf.report(snaps, sf.evaluate(snaps, b))
    assert "| technical | 5 | 2 |" in text and "100%" in text


def test_the_results_file_is_versioned_validated_and_free_of_secrets():
    b = bars(up=tuple(f"S{i:02d}" for i in range(10)))
    top = [f"S{i:02d}" for i in range(10)]
    snaps = [sf.snapshot(result_for(b, top), b, d) for d in ("2026-09-01", "2026-09-02")]
    assert sf.validate_snapshots(snaps) == []
    payload = sf.results_payload(snaps, sf.evaluate(snaps, b), "2026-11-19T12:00:00Z")
    assert payload["schema_version"] == sf.SCHEMA_VERSION and payload["snapshots"] == 2
    assert payload["first_day"] == "2026-09-01" and any(
        r["snapshots_scored"] == 2 for r in payload["summary"]
    )
    text = str(payload).lower()
    assert "token" not in text and "secret" not in text and "password" not in text
    bad = snaps + [dict(snaps[0])]  # a duplicate day
    assert any("duplicate" in p for p in sf.validate_snapshots(bad))
    assert any("malformed" in p for p in sf.validate_snapshots([{"day": "19-11-2026", "tracks": {}}]))
