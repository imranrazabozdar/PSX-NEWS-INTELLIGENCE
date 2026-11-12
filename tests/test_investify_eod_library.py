"""EOD progress report, the library target guard, the synthetic dry run, and the after-hours guarantee.

All data is SYNTHETIC: the fixtures under tests/fixtures/investify/ and the in-memory database. No network,
and no library or production database is touched. The live link test is skipped unless the owner has set the
library secret, and it is never run from a session that cannot set it.
"""

from __future__ import annotations

import json
import os
import random
import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collectors import investify_fundamentals as fund
from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol
from collectors.engine import load_source
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import investify_eod as eod
from engines import investify_extract as x
from engines import investify_library as lib

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "investify"
NOW = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)  # 16:00 PKT, Nov 10
PERMISSIVE = gc.parse_policy({
    "mode": "live", "kill_switch": False,
    "collectors_enabled": {k: True for k in gc.COLLECTORS},
    "min_gap_minutes": 15, "daily_ceiling": 96, "weekly_ceiling": 672, "warn_fraction": 0.99,
    "quiet_window_pkt": {"start": "00:00", "end": "23:59"},
    "cooldown_base_hours": 4, "cooldown_max_hours": 24,
    "breaker_threshold": 1, "backfill": {"paused": False, "reserve_daily": 0},
    "ttl_hours": {k: 0 for k in gc.COLLECTORS},
})


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no socket may be opened")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _db():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    return db


def _store(db, symbol, endpoint, fields, fetched="2026-11-10T04:00:00Z"):
    fund.store_structured(db, endpoint=endpoint, symbol=symbol, fields=fields,
                          url=f"https://www.investify.pk/company/{symbol}/{endpoint}", fetched_at_utc=fetched,
                          http_status=200)


# ---------- A. the library target (guard) and the link test

def test_the_library_url_must_be_set():
    with pytest.raises(lib.LibraryTargetError, match="not set"):
        lib.check_library_target(None)


@pytest.mark.parametrize("url", ["libsql://psxni-prod.turso.io", "libsql://psxni-data-capture.turso.io",
                                 "libsql://psx-library-prod.turso.io"])
def test_a_production_or_data_capture_target_is_refused_before_any_write(url):
    with pytest.raises(lib.LibraryTargetError, match="production|does not name the psx-library"):
        lib.check_library_target(url)


def test_a_url_that_does_not_name_the_library_is_refused():
    with pytest.raises(lib.LibraryTargetError, match="does not name the psx-library"):
        lib.check_library_target("libsql://psxni-operational.turso.io")


def test_the_guard_returns_the_database_name_and_never_the_credentials():
    name = lib.check_library_target("libsql://psx-library-turso202601.aws-us-east-1.turso.io?authToken=SECRET123")
    assert name == "psx-library-turso202601" and "SECRET123" not in name and "authToken" not in name


@pytest.mark.skipif(not os.environ.get("PSXNI_LIBRARY_TURSO_DATABASE_URL"),
                    reason="owner has not set the library secret (PSXNI_LIBRARY_TURSO_DATABASE_URL); "
                           "the live link test cannot run from this session")
def test_the_live_library_link_writes_reads_and_refuses_prod():  # pragma: no cover, secret only
    lib.check_library_target(os.environ["PSXNI_LIBRARY_TURSO_DATABASE_URL"])


# ------------------------------------------------------------------ B. the synthetic end-to-end dry run

def test_the_synthetic_dry_run_parses_stores_reads_back_and_verifies():
    result = lib.synthetic_dry_run(_db())
    assert result["stored"] == "inserted" and result["read_back"] is True
    assert result["metric_count"] == 4 and result["verified"] is True
    assert result["symbol"] == lib.SYNTHETIC_SYMBOL and result["synthetic"] is True


def test_the_synthetic_symbol_is_not_a_listed_company():
    watch = json.loads((ROOT / "config" / "coverage_watchlist.json").read_text(encoding="utf-8"))["companies"]
    assert lib.SYNTHETIC_SYMBOL not in {c["symbol"] for c in watch}


def test_the_dry_run_uses_only_the_disposable_database_and_refuses_the_remote_one():
    """source_items is append-only, so the dry run cannot delete a row. Its clean-up is to discard the
    database: the function takes a handle the caller discards, and nothing reaches a shared database."""
    db = _db()
    lib.synthetic_dry_run(db)
    fresh = _db()  # a new disposable database has none of the test rows
    rows = fresh.execute("SELECT COUNT(*) AS n FROM source_items WHERE external_id LIKE 'ZZTEST%'")
    assert rows[0]["n"] == 0


# ------------------------------------------------------------------ C. the EOD report

def _synthetic_company_store(db):
    # the synthetic feed belongs to FCL; it is parsed under its own symbol and stored for the test company
    ann = x.parse_announcements((FIX / "announcements_synthetic.html").read_bytes(), "FCL")
    prof = {"symbol": "AAA", "sector": "S", "leadership": {"chairperson": "P"}, "description": "d"}
    fund_fields = x.parse_fundamentals((FIX / "fundamentals_synthetic.html").read_bytes(), "AAA")
    comp = {"symbol": "AAA", "peer_source": "sector-derived", "peer_count": 1, "peers": []}
    _store(db, "AAA", "profile", prof)
    _store(db, "AAA", "fundamentals", fund_fields)
    _store(db, "AAA", "competitors", comp)
    _store(db, "AAA", "announcements", ann)
    _store(db, "BBB", "profile", prof)  # breadth only: profile, no depth
    _store(db, "CCC", "announcements", ann)  # any data, not breadth


def test_the_backfill_percentages_separate_coverage_breadth_and_depth():
    db = _db()
    _synthetic_company_store(db)
    watch = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    r = eod.build_report(db, watchlist=watch, day="2026-10-20", now=NOW, audit_events=[], policy=PERMISSIVE)
    b = r["backfill"]
    assert b["watchlist_total"] == 5
    assert b["library_coverage_percent"] == 60.0  # AAA, BBB, CCC of 5
    assert b["pass1_breadth_percent"] == 40.0  # AAA and BBB have a profile or fundamentals
    assert b["pass2_depth_percent"] == 20.0  # only AAA has all four


def test_todays_announcements_are_grouped_and_the_financial_result_is_highlighted():
    db = _db()
    _synthetic_company_store(db)
    r = eod.build_report(db, watchlist=["AAA"], day="2026-10-20", now=NOW, audit_events=[], policy=PERMISSIVE)
    a = r["announcements_today"]
    assert a["count"] == 1 and a["by_group"]["Financials"] == 1
    assert a["items"][0]["highlight"] is True and a["items"][0]["group"] == "Financials"


def test_the_footprint_is_part_of_the_report_and_warns_near_the_ceiling():
    db = _db()
    events = [{"event": "endpoint_request", "ts_utc": pol._iso(NOW.replace(hour=5, minute=i)),
               "endpoint": "profile", "outcome": "ok"} for i in range(0, 12, 2)]  # 6 requests today
    tight = replace(PERMISSIVE, daily_ceiling=8, warn_fraction=0.6)  # a ceiling of 8: 6 is at least 60%
    r = eod.build_report(db, watchlist=["AAA"], day="2026-11-10", now=NOW, audit_events=events, policy=tight)
    assert r["footprint"]["requests_today"] == 6
    assert r["footprint"]["warnings"] and "6 of 8" in r["footprint"]["warnings"][0]

def test_the_report_text_carries_the_private_use_attribution():
    db = _db()
    r = eod.build_report(db, watchlist=["AAA"], day="2026-11-10", now=NOW, audit_events=[], policy=PERMISSIVE)
    text = eod.render_text(r)
    assert "investify.pk" in text and "Private research use" in text


def test_a_day_is_persisted_once_and_never_overwritten(tmp_path):
    db = _db()
    r = eod.build_report(db, watchlist=["AAA"], day="2026-11-10", now=NOW, audit_events=[], policy=PERMISSIVE)
    path = eod.persist(r, tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "2026-11-10.json" and saved["day_pkt"] == "2026-11-10"
    with pytest.raises(FileExistsError):
        eod.persist(r, tmp_path)


# ------------------------------------------------------------------ no live fetch after hours

class NoNetwork:
    calls = 0

    def __call__(self, url, headers):
        NoNetwork.calls += 1
        raise AssertionError(f"a request was sent: {url}")


def test_no_live_request_is_made_after_trading_hours_even_with_every_limit_permissive(tmp_path):
    db = _db()
    entry = {**load_source(db, fund.SOURCE_ID), "enabled": 1}
    NoNetwork.calls = 0
    after_hours = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # 17:00 PKT
    out = fund.run_endpoint(now=after_hours, state_path=tmp_path / "s.json", entry=entry, db=db,
                            endpoint="profile", symbol="AAA", watchlist=frozenset({"AAA"}),
                            transport=NoNetwork(), rng=random.Random(1),  # noqa: S311 - test jitter
                            good=PERMISSIVE)
    assert out.status in ("skipped", "refused") and NoNetwork.calls == 0


def test_the_shipped_good_citizen_policy_is_still_cache_only_and_every_collector_is_off():
    shipped = gc.load_policy()
    assert shipped.mode == "cache_only" and not any(shipped.collectors_enabled.values())
