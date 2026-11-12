"""The autonomous tick: every guard fails closed, it acts at most once, the breaker trips on any pushback,
and the state round-trips. No network: every side effect is a fake that records what it was asked to do.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collectors import investify_good_citizen as gc
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import autonomous_tick as at
from engines import library_db
from engines import market_calendar as mc

ROOT = Path(__file__).resolve().parents[1]
CAL = mc.load_calendar(ROOT / "config" / "psx_calendar.json")
ROBOTS = "User-agent: *\nDisallow: /admin\n"
ROBOTS_OK = at.Control(kill_switch=False, robots_txt=ROBOTS,
                       robots_fetched_utc="2026-11-16T04:00:00Z")
RESOURCES = [("MEBL", "fundamentals"), ("LUCK", "profile")]


def pkt(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=gc.PKT).astimezone(UTC)


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no socket may be opened by the tick tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def open_control(**over):
    return at.Control(**{**ROBOTS_OK.__dict__, **over})


def d(now, control=None, **kw):
    kw.setdefault("calendar", CAL)
    kw.setdefault("resources", RESOURCES)
    kw.setdefault("done", set())
    kw.setdefault("first_live_day", None)
    kw.setdefault("env", {})
    return at.decide(now, control or open_control(), **kw)


# ---------- every guard, fail closed

def test_live_by_default_so_only_the_structural_guards_decide():
    assert at.Control().kill_switch is False
    assert not hasattr(at.Control(), "fetch_mode")
    assert d(pkt("2026-11-16 10:00"), at.Control(robots_txt=ROBOTS,
             robots_fetched_utc="2026-11-16T04:00:00Z")).action == "fetch"


def test_no_fetch_mode_toggle_exists_anywhere_in_the_code_or_config():
    banned = ("fetch_mode", "FETCH_MODE", "cache_only")
    roots = [ROOT / "engines", ROOT / "collectors", ROOT / "config", ROOT / ".github", ROOT / "tests",
             ROOT / "docs" / "ops", ROOT / "database" / "library"]
    hits = []
    for base in roots:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json", ".yml", ".yaml", ".md", ".sql"} \
                    and path.name != Path(__file__).name and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                hits += [f"{path.relative_to(ROOT)}: {b}" for b in banned if b in text]
    assert hits == []


def test_the_library_is_checked_before_any_investify_request(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(library_db, "get_library_connection",
                        lambda env: library_db.LibraryConnection(host="x", db=None))

    def unreachable(conn):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(library_db, "auth_check", unreachable)
    monkeypatch.setattr(at, "fetch_http", lambda ua: calls.append(ua) or (lambda s, e: (200, {}, b"")))
    env = {"PSXNI_CONTACT_EMAIL": "ops@example.test"}
    assert at.main(env) == 1
    assert calls == [] and "unreachable" in capsys.readouterr().out


def test_the_breaker_cooldown_is_checked_before_everything_else():
    c = open_control(breaker_tripped=True, cooldown_until_utc="2026-11-16T12:00:00Z", kill_switch=False)
    assert d(pkt("2026-11-16 10:00"), c).reason.startswith("breaker cooling")


def test_the_kill_switch_halts_instantly():
    assert d(pkt("2026-11-16 10:00"), open_control(kill_switch=True)).action == "noop"
    assert d(pkt("2026-11-16 10:00"), env={"PSXNI_KILL_SWITCH": "true"}).action == "noop"


def test_an_unreadable_calendar_is_a_no_op():
    assert d(pkt("2026-11-16 10:00"), calendar=None).action == "noop"


def test_a_weekend_or_holiday_is_a_no_op():
    assert d(pkt("2026-11-14 10:00")).action == "noop"
    holiday = sorted(CAL.holidays)[0]
    assert d(pkt(f"{holiday} 10:00")).action == "noop"


def test_before_the_window_and_after_it_is_a_no_op():
    assert d(pkt("2026-11-16 08:00")).action == "noop"
    assert d(pkt("2026-11-16 16:00")).action == "noop"


def test_the_first_and_last_fifteen_minutes_of_the_session_are_trimmed():
    assert d(pkt("2026-11-16 09:35")).action == "noop"  # 09:32 + 15 minutes
    assert d(pkt("2026-11-16 15:20")).action == "noop"  # 15:30 - 15 minutes
    assert d(pkt("2026-11-16 10:00")).action == "fetch"


def test_friday_jumma_break_is_refused_and_friday_morning_is_open():
    assert d(pkt("2026-11-13 13:00")).action == "noop"  # the break 12:00-14:32
    assert d(pkt("2026-11-13 10:30")).action == "fetch"


def test_the_throttle_holds_for_fifteen_minutes_across_all_resources():
    recent = open_control(global_last_request_utc="2026-11-16T04:55:00Z")  # 5 minutes before 10:00 PKT
    assert d(pkt("2026-11-16 10:00"), recent).action == "noop"
    earlier = open_control(global_last_request_utc="2026-11-16T04:40:00Z")
    assert d(pkt("2026-11-16 10:00"), earlier).action == "fetch"


def test_the_day_one_ceiling_is_two_then_twelve():
    today = "2026-11-16"
    assert d(pkt("2026-11-16 10:00"), open_control(daily_day_pkt=today, daily_count=2),
             first_live_day="2026-11-16").action == "noop"
    assert d(pkt("2026-11-17 10:00"), open_control(daily_day_pkt="2026-11-17", daily_count=2),
             first_live_day="2026-11-16").action == "fetch"
    assert d(pkt("2026-11-17 10:00"), open_control(daily_day_pkt="2026-11-17", daily_count=12),
             first_live_day="2026-11-16").action == "noop"


def test_a_breaker_that_is_still_cooling_is_a_no_op_and_expires_on_time():
    cooling = open_control(breaker_tripped=True, cooldown_until_utc="2026-11-16T09:00:00Z")
    assert d(pkt("2026-11-16 10:00"), cooling).action == "noop"  # 10:00 PKT is 05:00 UTC, before 09:00 UTC
    expired = open_control(breaker_tripped=True, cooldown_until_utc="2026-11-16T04:00:00Z")
    assert d(pkt("2026-11-16 10:00"), expired).action == "fetch"


def test_robots_is_refreshed_first_and_disallowed_paths_are_never_fetched():
    assert d(pkt("2026-11-16 10:00"), at.Control(kill_switch=False)).resource == (
        "robots", "robots.txt")
    blocked = [("ADMIN", "fundamentals")]
    stricter = open_control(robots_txt="User-agent: *\nDisallow: /company/ADMIN\n")
    assert d(pkt("2026-11-16 10:00"), stricter, resources=blocked).action == "noop"


def test_a_done_resource_is_skipped_and_the_next_is_chosen():
    dec = d(pkt("2026-11-16 10:00"), done={"MEBL:fundamentals"})
    assert dec.action == "fetch" and dec.resource == ("LUCK", "profile")


# ---------- acting: at most once, state written before the request, pushback stops everything

class Recorder:
    def __init__(self, status=200, body=b"", headers=None, control=None):
        self.events: list[str] = []
        self.control = control or open_control()
        self.done: set[str] = set()
        self.stored: list[tuple[str, str]] = []
        self.status, self.body, self.headers = status, body, headers or {}
        self.fetched: list[tuple[str, str]] = []

    def deps(self):
        def save_control(c):
            self.events.append("save_control")
            self.control = c

        def fetch(sym, ep):
            self.events.append("fetch")
            self.fetched.append((sym, ep))
            return self.status, self.headers, self.body

        def store(sym, ep, body):
            self.events.append("store")
            self.stored.append((sym, ep))

        return at.Dependencies(load_control=lambda: self.control, save_control=save_control,
                               load_done=lambda: set(self.done),
                               save_done=lambda k: self.done.add(k) or self.events.append("done"),
                               fetch=fetch, store=store, log=lambda e, x: self.events.append(f"log:{e}"))


def test_an_open_tick_acts_exactly_once_and_writes_the_throttle_before_the_request():
    r = Recorder(status=200, body=b"<p>x</p>", control=open_control(robots_txt=None, robots_fetched_utc=None))
    dec = at.tick(pkt("2026-11-16 10:00"), r.deps(), calendar=CAL, resources=RESOURCES, first_live_day=None,
                  env={})
    assert dec.action == "fetch"
    assert r.fetched == [("robots", "robots.txt")]  # the one request of this tick is robots (it was stale)
    assert r.events.index("save_control") < r.events.index("fetch")  # throttle written before the request


def test_a_clear_tick_makes_exactly_one_request():
    r = Recorder(status=200, body=b"<p>x</p>")
    at.tick(pkt("2026-11-16 10:00"), r.deps(), calendar=CAL, resources=RESOURCES, first_live_day=None, env={})
    assert len(r.fetched) == 1 and r.fetched[0] == ("MEBL", "fundamentals")
    assert r.stored == [("MEBL", "fundamentals")] and "MEBL:fundamentals" in r.done


@pytest.mark.parametrize("status", [403, 429, 503, None])
def test_any_pushback_trips_the_breaker_for_a_multi_hour_cooldown(status):
    r = Recorder(status=status, control=open_control())
    at.tick(pkt("2026-11-16 10:00"), r.deps(), calendar=CAL, resources=RESOURCES, first_live_day=None, env={})
    assert r.control.breaker_tripped is True
    cooldown = gc.load_policy()  # the shipped floor
    until = datetime.fromisoformat(r.control.cooldown_until_utc.replace("Z", "+00:00"))
    assert until - pkt("2026-11-16 10:00") >= timedelta(hours=4)
    assert cooldown.cooldown_base >= timedelta(hours=4)
    again = d(pkt("2026-11-16 10:30"), r.control)
    assert again.action == "noop"


def test_a_304_is_a_recorded_no_op_that_writes_no_data():
    r = Recorder(status=304)
    at.tick(pkt("2026-11-16 10:00"), r.deps(), calendar=CAL, resources=RESOURCES, first_live_day=None, env={})
    assert r.stored == [] and "MEBL:fundamentals" in r.done


def test_a_200_is_stored_as_distilled_fields_through_the_store_only():
    r = Recorder(status=200, body=b"<p>x</p>")
    at.tick(pkt("2026-11-16 10:00"), r.deps(), calendar=CAL, resources=RESOURCES, first_live_day=None, env={})
    assert r.stored and r.events.count("store") == 1


def test_resources_run_fundamentals_first_and_core_names_first():
    order = at.resources_for(["ZZZ", "MEBL", "HUBC", "AAA"])
    assert order[0] == ("MEBL", "fundamentals") and order[1] == ("HUBC", "fundamentals")
    assert order[2] == ("AAA", "fundamentals") and order[3] == ("ZZZ", "fundamentals")
    assert all(ep == "fundamentals" for _, ep in order[:4])  # fundamentals before profile and competitors


# ---------- the state store: round trip on the migration, on an in-memory copy

def _state_db():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    sql = (ROOT / "database" / "library" / "0001_fetch_state.sql").read_text(encoding="utf-8")
    for statement in [s for s in sql.split(";") if s.strip()]:
        db.execute(statement)
    return db


def test_the_state_migration_creates_the_three_tables():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    store = at.LibraryState(db)
    assert store.tables_present() is False
    sql = (ROOT / "database" / "library" / "0001_fetch_state.sql").read_text(encoding="utf-8")
    for statement in [s for s in sql.split(";") if s.strip()]:
        db.execute(statement)
    assert store.tables_present() is True


def test_control_and_progress_round_trip_through_the_store():
    store = at.LibraryState(_state_db())
    c = open_control(kill_switch=False, global_last_request_utc="2026-11-16T05:00:00Z",
                     daily_day_pkt="2026-11-16", daily_count=1, first_live_day="2026-11-16")
    store.save_control(c)
    back = store.load_control()
    assert back.kill_switch is False and back.daily_count == 1
    assert back.global_last_request_utc == "2026-11-16T05:00:00Z" and back.first_live_day == "2026-11-16"
    store.save_done("MEBL:fundamentals")
    assert store.load_done() == {"MEBL:fundamentals"}
    store.log("tick_noop", "test")
    rows = store.db.execute("SELECT COUNT(*) AS n FROM fetch_log")
    assert rows[0]["n"] == 1


def test_the_default_store_state_is_live_with_the_kill_switch_off():
    store = at.LibraryState(_state_db())
    c = store.load_control()
    assert c.kill_switch is False


# ---------- the entrypoint and the honest User-Agent

def test_without_the_library_variables_the_tick_is_a_clean_no_op(capsys, monkeypatch):
    monkeypatch.delenv("PSXNI_LIBRARY_TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("PSXNI_LIBRARY_TURSO_AUTH_TOKEN", raising=False)
    assert at.main({}) == 0
    assert "no-op" in capsys.readouterr().out


def test_no_contact_address_means_no_user_agent_and_no_live_request():
    assert at.user_agent(None) is None and at.user_agent("not-an-address") is None


def test_with_a_contact_the_user_agent_is_honest_and_contactable():
    ua = at.user_agent("ops@example.test")
    assert "contact: ops@example.test" in ua and "psx-news-intelligence" in ua


def test_the_workflow_is_scheduled_on_the_default_branch_and_uses_library_secrets_only():
    text = (ROOT / ".github" / "workflows" / "psx_fetch.yml").read_text(encoding="utf-8")
    assert "cron:" in text and "workflow_dispatch" in text
    assert "PSXNI_LIBRARY_TURSO_DATABASE_URL" in text and "PSXNI_LIBRARY_TURSO_AUTH_TOKEN" in text
    assert "PSXNI_PROD" not in text and "data-capture" not in text.lower()
    assert "PSXNI_FETCH_MODE" not in text
    assert "python -m engines.autonomous_tick" in text


def test_the_end_of_day_log_reports_progress_and_breaker_state_from_state_only():
    text = at.render_fetch_log(day="2026-11-16", done=3, total=108,
                               control=open_control(daily_day_pkt="2026-11-16", daily_count=2),
                               events=[("request", "stored MEBL:fundamentals")])
    assert "3 of 108 resources complete (2.8%)" in text and "Requests today: 2." in text
    assert "Private research use" in text and "investify.pk" in text
    assert "stored MEBL:fundamentals" in text
