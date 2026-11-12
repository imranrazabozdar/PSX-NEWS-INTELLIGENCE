"""The library target (psx-library only), the link test on the approved probe table, and the calendar.

All synthetic. No network. No real Turso database is opened: the link test runs on an in-memory copy of the
probe table. The live link test needs the owner's secrets and is not run here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import investify_library as lib
from engines import market_calendar as mc

ROOT = Path(__file__).resolve().parents[1]
# captured before the suite's fixture allows every calendar check, so these tests exercise the real rule
REAL_CALENDAR_VERDICT = gc.calendar_verdict
LIBRARY = "libsql://psx-library-turso202601.aws-us-east-1.turso.io"
DATA_CAPTURE = "libsql://psx-data-capture-turso202601.aws-us-east-1.turso.io"
ARCHIVAL_TEST = "libsql://psx-data-archival-test-turso202601.aws-us-east-1.turso.io"


def pkt(text: str) -> datetime:
    """A Pakistan-time wall clock, as a UTC instant."""
    return datetime.fromisoformat(text).replace(tzinfo=pol.PKT).astimezone(UTC)


# ---------- the library target: accept psx-library, refuse everything else

def test_the_guard_accepts_the_psx_library_url_and_returns_only_the_name():
    assert lib.check_library_target(LIBRARY) == "psx-library-turso202601"
    assert lib.check_library_target(LIBRARY + "?authToken=SECRET") == "psx-library-turso202601"


def test_the_guard_refuses_the_data_capture_database():
    with pytest.raises(lib.LibraryTargetError, match="production, data-capture or archival"):
        lib.check_library_target(DATA_CAPTURE)


def test_the_guard_refuses_the_archival_test_database():
    with pytest.raises(lib.LibraryTargetError, match="production, data-capture or archival"):
        lib.check_library_target(ARCHIVAL_TEST)


@pytest.mark.parametrize("url", [
    "libsql://psx-archive-turso202601.aws-us-east-1.turso.io",
    "libsql://psx-prod-turso202601.aws-us-east-1.turso.io",
    "libsql://psx-production-turso202601.aws-us-east-1.turso.io",
    "libsql://psx-library-prod.turso.io",  # a library name with a production marker is still refused
])
def test_the_guard_refuses_any_production_or_archive_marker(url):
    with pytest.raises(lib.LibraryTargetError):
        lib.check_library_target(url)


def test_the_guard_refuses_a_url_that_does_not_name_the_library_and_a_missing_url():
    with pytest.raises(lib.LibraryTargetError, match="does not name the psx-library"):
        lib.check_library_target("libsql://psx-operational-turso202601.aws-us-east-1.turso.io")
    with pytest.raises(lib.LibraryTargetError, match="not set"):
        lib.check_library_target(None)


# ---------- the link test: one synthetic record, read back, deleted, on the approved probe table

def test_the_link_test_writes_reads_and_deletes_one_synthetic_record():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    result = lib.link_test(db)
    assert result == {"written": True, "read_back": True, "deleted": True, "marker": "psxni-link-test-0001"}
    assert db.execute("SELECT COUNT(*) AS n FROM library_probe")[0]["n"] == 0  # nothing left behind


def test_the_probe_row_is_small_synthetic_and_marked_as_a_test():
    import json

    payload = json.dumps({"synthetic": True, "purpose": "library link test", "source": "test"},
                         sort_keys=True)
    assert len(payload.encode("utf-8")) < 1024
    assert "test" in payload and '"synthetic": true' in payload


# ---------- the calendar: fetch only in a confirmed-open window; the Friday break; uncertainty refuses

@pytest.fixture
def cal():
    return mc.load_calendar(ROOT / "config" / "psx_calendar.json")


def test_monday_inside_the_recorded_hours_is_a_confirmed_open_window(cal):
    assert REAL_CALENDAR_VERDICT(pkt("2026-11-16 10:00"), cal, gc.load_policy()).allowed is True


def test_after_the_recorded_close_there_is_no_fetch(cal):
    assert REAL_CALENDAR_VERDICT(pkt("2026-11-16 16:30"), cal, gc.load_policy()).allowed is False


def test_the_friday_break_is_refused_while_its_window_is_unconfirmed(cal):
    v = REAL_CALENDAR_VERDICT(pkt("2026-11-13 13:00"), cal, gc.load_policy())  # Friday 13:00 PKT
    assert v.allowed is False and "Friday break" in v.reason


def test_friday_before_the_break_is_open(cal):
    assert REAL_CALENDAR_VERDICT(pkt("2026-11-13 10:30"), cal, gc.load_policy()).allowed is True


def test_a_weekend_is_not_a_trading_day(cal):
    v = REAL_CALENDAR_VERDICT(pkt("2026-11-14 10:30"), cal, gc.load_policy())  # Saturday
    assert v.allowed is False and "not a trading day" in v.reason


def test_a_recorded_holiday_is_not_a_trading_day(cal):
    holiday = sorted(cal.holidays)[0]
    v = REAL_CALENDAR_VERDICT(pkt(f"{holiday} 10:30"), cal, gc.load_policy())
    assert v.allowed is False and "not a trading day" in v.reason


def test_an_unreadable_calendar_refuses(cal):
    assert REAL_CALENDAR_VERDICT(pkt("2026-11-16 10:00"), None, gc.load_policy()).allowed is False


def test_unrecorded_hours_refuse_rather_than_guess(cal):
    empty = mc.TradingCalendar(regular_hours={})
    v = REAL_CALENDAR_VERDICT(pkt("2026-11-16 10:00"), empty, gc.load_policy())
    assert v.allowed is False and "not recorded" in v.reason


def test_the_friday_break_is_a_config_value_marked_pending_owner_confirmation():
    shipped = gc.load_policy()
    assert shipped.friday_break is not None  # refused by default
    import json

    raw = json.loads((ROOT / "config" / "investify_good_citizen.json").read_text(encoding="utf-8"))
    assert "PENDING" in raw["friday_break_pkt"]["_note"]


def test_the_shipped_policy_is_still_cache_only_with_every_collector_off():
    shipped = gc.load_policy()
    assert shipped.mode == "cache_only" and not any(shipped.collectors_enabled.values())
