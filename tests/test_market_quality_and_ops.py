"""Stage 5: trading calendar, session grading, gap detection and recovery, cheap coverage, operations data.
Offline: local SQLite, SYNTHETIC bars."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from collectors.http import HttpClient
from collectors.market_ohlcv import collect_market
from collectors.market_orchestrator import plan_gaps
from engines import collection_ops as ops
from engines.market_calendar import CalendarError, TradingCalendar, load_calendar
from engines.market_quality import coverage_summary, grade_sessions, load_bars, recoverable_gaps
from tests.test_market_orchestration import SRC, Provider, db  # noqa: F401 (fixture)

TODAY = "2026-11-09"  # Monday (PKT)
NOW = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)  # Wed; "yesterday" = Tue (11-09 is a holiday)
CAL = TradingCalendar()


def _minutes(day, start="04:30", n=360, skip=()):
    """1-minute bar starts (UTC) for a PKT session: 09:30 PKT = 04:30 UTC."""
    t0 = datetime.fromisoformat(f"{day}T{start}:00+00:00")
    return [(t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(n) if i not in skip]


def _data(per_symbol: dict[str, dict[str, list[str]]]):
    out = {}
    for sym, days in per_symbol.items():
        allb = sorted(b for v in days.values() for b in v)
        out[sym] = {"days": days, "first": allb[0] if allb else None, "last": allb[-1] if allb else None}
    return out


def _grade(data, start="2026-11-02", end=TODAY, cal=CAL):
    return {
        (g.symbol, g.session_date): g
        for g in grade_sessions(data, "1m", start, end, today=TODAY, calendar=cal)
    }


WEEK = {d: _minutes(d) for d in ("2026-11-02", "2026-11-04", "2026-11-05")}
FRI_BREAK = _minutes("2026-11-06", skip=range(150, 270))  # a 2-hour break every symbol shares


def _universe(c_overrides=None):
    base = {**WEEK, "2026-11-06": FRI_BREAK}
    return _data({"A": dict(base), "B": dict(base), "C": {**base, **(c_overrides or {})}})


# ------------------------------------------------------------------ calendar
def test_calendar_distinguishes_weekend_holiday_closure_and_special_sessions(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(
        json.dumps(
            {
                "weekend_weekdays": [5, 6],
                "regular_hours": {
                    "default": {"open": "09:30", "close": "15:30"},
                    "4": {"open": "09:15", "close": "16:30"},
                },
                "holidays": {"2026-11-03": {"name": "Synthetic holiday", "source": "test notice"}},
                "closures": {"2026-11-05": {"name": "Unexpected closure", "source": "test notice"}},
                "special_sessions": {
                    "2026-11-07": {"open": "10:00", "close": "13:00", "source": "test notice"}
                },
            }
        )
    )
    cal = load_calendar(p)
    assert [
        cal.day_type(d) for d in ("2026-11-02", "2026-11-03", "2026-11-05", "2026-11-07", "2026-11-08")
    ] == ["WEEKDAY", "HOLIDAY", "CLOSURE", "SPECIAL", "WEEKEND"]
    assert cal.hours("2026-11-02") == (570, 930) and cal.hours("2026-11-06") == (555, 990)  # Friday differs
    assert cal.hours("2026-11-07") == (600, 780) and cal.hours("2026-11-03") is None


def test_calendar_refuses_uncited_or_malformed_entries(tmp_path):
    p = tmp_path / "cal.json"
    for bad in (
        {"holidays": {"2026-11-03": {"name": "x"}}},
        {"regular_hours": {"default": {"open": "16:00", "close": "09:00"}}},
        {"special_sessions": {"11/07/2026": {"source": "x"}}},
    ):
        p.write_text(json.dumps(bad))
        with pytest.raises(CalendarError):
            load_calendar(p)


def test_shipped_calendar_entries_are_official_and_cited():
    import json as _json
    from pathlib import Path

    raw = _json.loads((Path(__file__).resolve().parents[1] / "config/psx_calendar.json").read_text())
    for section in ("regular_hours", "holidays"):
        assert raw[section] and all("www.psx.com.pk" in e["source"] for e in raw[section].values())
    cal = load_calendar()
    assert cal.weekend == frozenset({5, 6}) and cal.closures == {} and cal.special == {}
    assert cal.hours("2026-11-04") == (555, 950) and cal.hours("2026-11-06") == (540, 1010)  # Wed / Fri
    assert cal.day_type("2026-11-09") == "HOLIDAY"  # Allama Iqbal Day (fixed date)
    assert "2026-03-21" not in cal.holidays  # moon-dependent dates await confirming notices


def test_official_hours_flag_only_1m_bars_outside_the_window():
    cal = load_calendar()
    hourly = _data({s: {"2026-11-04": [f"2026-11-04T0{h}:00:00Z" for h in range(4, 10)]} for s in "AB"})
    g = {(x.symbol, x.session_date): x for x in grade_sessions(hourly, "1h", "2026-11-04", "2026-11-04",
                                                              today=TODAY, calendar=cal)}
    assert g[("A", "2026-11-04")].state == "COMPLETE"  # 09:00 PKT hourly bar is not an anomaly
    early = _universe({"2026-11-04": _minutes("2026-11-04", start="04:00", n=390)})  # from 09:00 PKT
    assert _grade(early, cal=cal)[("C", "2026-11-04")].state == "ANOMALY"
    assert _grade(_universe(), cal=cal)[("A", "2026-11-04")].state == "COMPLETE"  # 09:30-15:29 inside


# ------------------------------------------------------------------ grading
def test_full_sessions_and_a_shared_market_break_are_complete():
    g = _grade(_universe())
    assert all(
        g[(s, d)].state == "COMPLETE" for s in "ABC" for d in ("2026-11-04", "2026-11-05", "2026-11-06")
    )


def test_a_long_symbol_specific_hole_is_incomplete_but_thin_minutes_are_not():
    g = _grade(
        _universe(
            {
                "2026-11-05": _minutes("2026-11-05", skip=range(100, 190)),
                "2026-11-04": _minutes("2026-11-04", skip=range(10, 40)),
            }
        )
    )
    inc = g[("C", "2026-11-05")]
    assert inc.state == "INCOMPLETE" and "recoverable" in inc.reason
    assert inc.missing_runs == [("2026-11-05T06:10:00Z", "2026-11-05T07:39:00Z")]
    assert g[("C", "2026-11-04")].state == "COMPLETE"  # 30 quiet minutes: within tolerance


def test_weekends_holidays_and_closures_are_never_missing():
    g = _grade(_universe())
    assert g[("A", "2026-11-07")].state == g[("A", "2026-11-08")].state == "NON_TRADING"
    assert g[("A", "2026-11-03")].state == "MARKET_CLOSED_INFERRED"  # weekday nobody traded
    hol = TradingCalendar(holidays={"2026-11-03": "Synthetic holiday"})
    assert _grade(_universe(), cal=hol)[("A", "2026-11-03")].state == "NON_TRADING"


def test_missing_versus_provider_unavailable_versus_not_collected():
    g = _grade(_universe({"2026-11-02": [], "2026-11-04": []}))
    assert g[("C", "2026-11-04")].state == "MISSING" and g[("C", "2026-11-04")].missing_runs
    assert g[("C", "2026-11-02")].state == "PROVIDER_UNAVAILABLE"  # older than 5-day 1m retention
    d = _data({"A": {"2026-11-04": _minutes("2026-11-04")}, "D": {}})
    g = _grade(d)
    assert g[("D", "2026-11-04")].state == "NOT_COLLECTED"  # backfill not started: no false alarm
    assert g[("A", "2026-11-05")].state == "NOT_COLLECTED"  # after its latest bar
    assert g[("A", TODAY)].state == "CURRENT_SESSION"


def test_bars_on_a_weekend_or_outside_recorded_hours_are_anomalies():
    data = _universe({"2026-11-07": _minutes("2026-11-07", n=10)})
    assert _grade(data)[("C", "2026-11-07")].state == "ANOMALY"
    cal = TradingCalendar(regular_hours={"default": (570, 900)})  # 09:30-15:00 PKT
    assert _grade(_universe(), cal=cal)[("A", "2026-11-04")].state == "ANOMALY"  # bars until 15:30


def test_recoverable_gaps_are_inside_retention_and_1m_first():
    g = grade_sessions(
        _universe({"2026-11-02": [], "2026-11-05": _minutes("2026-11-05", skip=range(0, 100))}),
        "1m",
        "2026-11-02",
        TODAY,
        today=TODAY,
        calendar=CAL,
    )
    gaps = recoverable_gaps(g, today=TODAY)
    assert [(s, tf) for s, tf, _, _ in gaps] == [("C", "1m")]  # 11-02 is past retention: not re-requested


# ------------------------------------------------------------------ database paths
def _insert(db, sym, starts, tf="1m", volume=100.0):  # noqa: F811
    db.connect()  # test setup is not a collection run: reset the synthetic per-run budget
    db.batch(
        [
            (
                "INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
                "open, high, low, close, volume, retrieved_at_utc) VALUES (?,?,?,?,?,10,11,9,10.5,?,?)",
                (
                    SRC,
                    sym,
                    tf,
                    b,
                    (datetime.strptime(b, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=5)).strftime("%Y-%m-%d"),
                    volume,
                    "2026-11-09T00:00:00Z",
                ),
            )
            for b in starts
        ]
    )
    db.connect()


def test_zero_volume_bars_count_as_present(db):  # noqa: F811
    _insert(db, "A", _minutes("2026-11-04"))
    _insert(db, "B", _minutes("2026-11-04"), volume=0.0)
    data = load_bars(db, SRC, ["A", "B"], "1m", "2026-11-02")
    g = _grade(data)
    assert g[("B", "2026-11-04")].state == "COMPLETE" and g[("B", "2026-11-04")].bars == 360


def test_coverage_and_bar_loads_use_the_index_not_a_full_scan(db):  # noqa: F811
    _insert(db, "A", _minutes("2026-11-04", n=30))
    cov = coverage_summary(db, SRC, ["A", "B"], ["1m", "1d"])
    assert cov[0] == {
        "symbol": "A",
        "timeframe": "1m",
        "first_bar_utc": "2026-11-04T04:30:00Z",
        "last_bar_utc": "2026-11-04T04:59:00Z",
    }
    assert cov[1]["first_bar_utc"] is None
    for sql in (
        "SELECT MIN(bar_start_utc) AS v FROM market_bars WHERE source_id = ? AND symbol = ? "
        "AND timeframe = ?",
        "SELECT bar_start_utc, session_date_pkt FROM market_bars WHERE source_id = ? AND symbol = ? "
        "AND timeframe = ? AND bar_start_utc >= ? ORDER BY bar_start_utc",
    ):
        n = sql.count("?")
        plan = " ".join(str(r) for r in db.execute("EXPLAIN QUERY PLAN " + sql, ("x",) * n))
        assert "SEARCH" in plan and "SCAN market_bars" not in plan


def test_gap_recovery_fills_only_missing_bars_and_rewrites_nothing(db, monkeypatch):  # noqa: F811
    day = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    full = _minutes(day, n=120)
    _insert(db, "A", full)
    _insert(db, "B", _minutes(day, n=120, skip=range(10, 90)))
    gaps = plan_gaps(db, NOW, ["A", "B"], ["1m"], SRC)
    assert len(gaps) == 1 and gaps[0][:2] == ("B", "1m")
    t0 = int(datetime.fromisoformat(full[0].replace("Z", "+00:00")).timestamp())

    def provider(url, headers, timeout):
        from urllib.parse import parse_qs, urlparse

        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        ts = [t0 + 60 * i for i in range(120) if int(q["from"]) <= t0 + 60 * i <= int(q["to"])]
        body = {
            "s": "ok",
            "t": ts,
            "o": [10] * len(ts),
            "h": [11] * len(ts),
            "l": [9] * len(ts),
            "c": [10.5] * len(ts),
            "v": [100] * len(ts),
        }
        return 200, {"content-type": "application/json"}, json.dumps(body).encode()

    before = db.execute("SELECT COUNT(*) AS n FROM market_bars")[0]["n"]
    run = collect_market(
        db,
        source_id=SRC,
        symbols=["A", "B"],
        timeframes=["1m"],
        now=NOW,
        pause_seconds=0,
        gap_ranges=gaps,
        client=HttpClient(transport=provider, sleep=lambda s: None, respect_robots=False),
    )
    gap = next(s for s in run.series if s.gap)
    assert gap.inserted == 80 and gap.unchanged == 0 and gap.corrected == 0
    assert db.execute("SELECT COUNT(*) AS n FROM market_bars")[0]["n"] == before + 80
    assert db.execute("SELECT COUNT(*) AS n FROM market_bar_corrections")[0]["n"] == 0
    assert plan_gaps(db, NOW, ["A", "B"], ["1m"], SRC) == []  # recovered: no longer planned


def test_gap_the_provider_no_longer_serves_is_not_retried_for_a_day(db):  # noqa: F811
    day = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    _insert(db, "A", _minutes(day, n=120))
    _insert(db, "B", _minutes(day, n=120, skip=range(0, 90)))  # 90 minutes: beyond the 60-minute tolerance
    gaps = plan_gaps(db, NOW, ["A", "B"], ["1m"], SRC)
    run = collect_market(
        db,
        source_id=SRC,
        symbols=["A", "B"],
        timeframes=["1m"],
        now=NOW,
        pause_seconds=0,
        gap_ranges=gaps,
        client=HttpClient(transport=Provider(n=0), sleep=lambda s: None, respect_robots=False),
    )
    assert run.status in ("succeeded", "partial") and not next(s for s in run.series if s.gap).error
    meta = json.loads(db.execute("SELECT quota_usage_json FROM collector_runs")[0]["quota_usage_json"])
    assert meta["gaps_unavailable"] == [["B", "1m", gaps[0][2]]]
    # run bookkeeping uses the real clock; align it with this test's fixed clock
    db.execute("UPDATE collector_runs SET started_at_utc = ?", (NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),))
    assert plan_gaps(db, NOW, ["A", "B"], ["1m"], SRC) == []


# ------------------------------------------------------------------ operations data
def test_run_outcomes_keep_complete_partial_and_failed_apart():
    def row(status, meta=None):
        return {"status": status, "quota_usage_json": json.dumps(meta) if meta else None}

    assert ops.run_outcome(row("succeeded")) == "Complete"
    assert ops.run_outcome(row("partial", {"budget_stopped": True, "series_errors": 0})).startswith(
        "Partial: budget"
    )
    assert ops.run_outcome(row("partial", {"series_errors": 2})) == "Partial: some series failed"
    assert ops.run_outcome(row("failed")) == "Failed"
    assert ops.run_outcome(row("running")).startswith("Stale legacy")
    assert ops.run_outcome(row("running", {"context": {}})) == "Running"


def test_operations_data_from_a_real_run(db):  # noqa: F811
    from tests.test_market_orchestration import _orch

    _orch(db, Provider(n=50), context={"trigger": "external", "github_run_id": 77})
    now = datetime.now(UTC)
    runs = ops.recent_runs(db)
    assert (
        runs[0]["trigger"] == "external"
        and runs[0]["github_run_id"] == 77
        and runs[0]["outcome"] == "Complete"
    )
    assert isinstance(runs[0]["rows_written"], int) and runs[0]["rows_written"] > 0
    assert ops.latest_success(db)["market_ohlcv"]["outcome"] == "Complete"
    trig = {t["trigger"]: t for t in ops.trigger_status(db, now, SRC)}
    assert trig["external"]["status"] == "ok" and trig["schedule"]["status"] == "no record"
    later = {t["trigger"]: t for t in ops.trigger_status(db, now + timedelta(hours=4), SRC)}
    assert later["external"]["status"].startswith("overdue")
    prog = {(p["symbol"], p["timeframe"]): p for p in ops.backfill_progress(db, ["SYN"], now, SRC)}
    assert prog[("SYN", "1d")]["covered_pct"] == 0.0 and prog[("SYN", "1m")]["covered_pct"] > 0


def test_gap_planning_failure_never_blocks_normal_collection(db, monkeypatch):  # noqa: F811
    from collectors import market_orchestrator as mo
    from database.connection import DatabaseError
    from tests.test_market_orchestration import _orch

    def broken(*a, **k):
        raise DatabaseError("simulated read failure while planning gaps")

    monkeypatch.setattr(mo, "plan_gaps", broken)
    out = _orch(db, Provider(n=30))
    p = out["passes"][0]
    assert p["status"] == "succeeded" and p["context"]["gaps_planned"] == 0
    assert "simulated" in p["context"]["gap_planning_error"]
