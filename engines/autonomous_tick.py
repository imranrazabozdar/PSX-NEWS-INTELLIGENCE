"""One autonomous tick of the good-citizen fetcher. Self-contained: it reads state, decides, acts at most
once, writes state back. Runs from a scheduled GitHub Actions job (see .github/workflows/psx_fetch.yml).

Live by default. Nothing is switched off by a mode toggle: every tick is gated by structural guards only
(library reachable, breaker/cooldown, owner window, calendar, throttle, daily ceiling, robots.txt), and each
guard fails closed. Stop controls: the automatic breaker, and disabling the workflow in the Actions UI.

Pure decision: `decide()`. Side effects only in `tick()`, through injected dependencies, so every branch is
testable without the network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol

MIN_GAP = timedelta(minutes=15)
DAY1_CEILING = 2  # conservative ramp: the first live day is a trickle
DEFAULT_CEILING = 12


def in_owner_window(local: datetime, calendar: Any) -> bool:
    """True only inside an official OPEN session, read from the calendar (the single source of truth)."""
    return calendar.in_open_session(local.date().isoformat(), local.hour * 60 + local.minute)


@dataclass(frozen=True)
class Control:
    kill_switch: bool = False  # manual stop row in psx-library; off by default
    breaker_tripped: bool = False
    cooldown_until_utc: str | None = None
    global_last_request_utc: str | None = None
    daily_day_pkt: str | None = None
    daily_count: int = 0
    robots_txt: str | None = None
    robots_fetched_utc: str | None = None
    first_live_day: str | None = None


@dataclass(frozen=True)
class Decision:
    action: str  # "noop" | "fetch"
    reason: str
    resource: tuple[str, str] | None = None  # (symbol, endpoint)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def ceiling_for(local_day: str, first_live_day: str | None) -> int:
    """Day 1 of live running is DAY1_CEILING; afterwards the default ceiling."""
    if first_live_day is None or local_day == first_live_day:
        return DAY1_CEILING
    return DEFAULT_CEILING


ROBOTS_MAX_AGE = timedelta(hours=24)
BASE = "https://www.investify.pk"


def resource_url(resource: tuple[str, str]) -> str:
    return f"{BASE}/company/{resource[0]}/{resource[1]}"


def decide(now: datetime, control: Control, *, calendar: Any, resources: list[tuple[str, str]],
           done: set[str], first_live_day: str | None, env: Mapping[str, str] | None = None,
           exceptions: Mapping[str, Mapping[str, Any]] | None = None) -> Decision:
    """The tick's decision. At most one request. Every guard fails closed."""
    env = os.environ if env is None else env
    if control.breaker_tripped and control.cooldown_until_utc and now < _utc(control.cooldown_until_utc):
        return Decision("noop", f"breaker cooling until {control.cooldown_until_utc}")
    if control.kill_switch or any(env.get(k, "").lower() == "true" for k in gc.ENV_KILL):
        return Decision("noop", "kill switch is on")
    if calendar is None:
        return Decision("noop", "trading calendar unreadable: fail closed")
    local = now.astimezone(gc.PKT)
    day = local.date().isoformat()
    if not calendar.is_trading_day(day):
        return Decision("noop", f"not a trading day ({calendar.day_type(day)})")
    if not in_owner_window(local, calendar):
        return Decision("noop", "outside an official open session (calendar)")
    if control.global_last_request_utc and now - _utc(control.global_last_request_utc) < MIN_GAP:
        return Decision("noop", "throttled: 15 minutes since the last request across all resources")
    count = control.daily_count if control.daily_day_pkt == day else 0
    ceiling = (exceptions or {}).get(day, {}).get("ceiling") or ceiling_for(day, first_live_day)
    if count >= ceiling:
        return Decision("noop", f"daily ceiling reached ({count})")
    if control.robots_txt is None or control.robots_fetched_utc is None or \
            now - _utc(control.robots_fetched_utc) >= ROBOTS_MAX_AGE:
        return Decision("fetch", "refresh robots.txt (it counts as the one request)",
                        ("robots", "robots.txt"))
    for resource in resources:
        key = f"{resource[0]}:{resource[1]}"
        if key in done:
            continue
        if not pol.robots_allows(control.robots_txt, resource_url(resource)):
            continue  # robots.txt disallows this path: never fetched
        return Decision("fetch", "next pending resource", resource)
    return Decision("noop", "nothing pending")


@dataclass
class Dependencies:
    load_control: Callable[[], Control]
    save_control: Callable[[Control], None]
    load_done: Callable[[], set[str]]
    save_done: Callable[[str], None]
    fetch: Callable[[str, str], tuple[int, dict[str, str], bytes]]  # (status, headers, body)
    store: Callable[[str, str, bytes], None]  # distilled fields only, never the raw body
    log: Callable[[str, str], None] = field(default=lambda event, detail: None)


def tick(now: datetime, deps: Dependencies, *, calendar: Any, resources: list[tuple[str, str]],
         first_live_day: str | None, env: Mapping[str, str] | None = None,
         exceptions: Mapping[str, Mapping[str, Any]] | None = None) -> Decision:
    control = deps.load_control()
    done = deps.load_done()
    d = decide(now, control, calendar=calendar, resources=resources, done=done,
               first_live_day=first_live_day or control.first_live_day, env=env, exceptions=exceptions)
    if d.action == "noop":
        deps.log("tick_noop", d.reason)
        return d
    # the throttle is written BEFORE the request, so a crash cannot cause a second request in the gap
    local_day = now.astimezone(gc.PKT).date().isoformat()
    count = control.daily_count if control.daily_day_pkt == local_day else 0
    new = Control(**{**control.__dict__, "global_last_request_utc": now.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"), "daily_day_pkt": local_day, "daily_count": count + 1})
    deps.save_control(new)
    status, headers, body = deps.fetch(*d.resource)
    key = f"{d.resource[0]}:{d.resource[1]}"
    if d.resource[0] == "robots" and status == 200:
        deps.save_control(Control(**{**new.__dict__, "robots_txt": body.decode("utf-8", "replace"),
                                     "robots_fetched_utc": now.astimezone(UTC).strftime(
                                         "%Y-%m-%dT%H:%M:%SZ")}))
        deps.log("request", "robots.txt refreshed")
        return Decision("fetch", "robots.txt refreshed", d.resource)
    if status in gc.BLOCK_STATUSES or status is None:
        until = gc.cooldown_until(now, 1, gc.load_policy(), headers.get("retry-after"))
        deps.save_control(Control(**{**new.__dict__, "breaker_tripped": True,
                                     "cooldown_until_utc": until.strftime("%Y-%m-%dT%H:%M:%SZ")}))
        deps.log("breaker_tripped", f"HTTP {status} on {key}; cooling until {until.isoformat()}")
        return Decision("noop", f"blocked on {key}: breaker tripped", d.resource)
    if status == 304:
        deps.save_done(key)  # nothing changed: a recorded no-op, no data written
        deps.log("not_modified", key)
        return Decision("fetch", f"304 on {key}: no-op", d.resource)
    if status == 200:
        try:
            written = deps.store(d.resource[0], d.resource[1], body)
        except Exception as exc:  # noqa: BLE001 - a failed store leaves the resource pending for the next run
            deps.log("store_failed", f"{key}: {type(exc).__name__}: {exc}"[:500])
            return Decision("noop", f"store failed on {key}: resource stays pending", d.resource)
        deps.save_done(key)
        deps.log("request", f"stored {key}: {written} row(s)")
        return Decision("fetch", f"stored {key}", d.resource)
    deps.log("request", f"HTTP {status} on {key}: not stored")
    return Decision("noop", f"HTTP {status} on {key}: not stored", d.resource)


# ---------------------------------------------------------- the state store (Turso-backed, or any handle)

class LibraryState:
    """Reads and writes the fetch-state tables. Needs the state migration applied (owner approval first)."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def tables_present(self) -> bool:
        names = {r["name"] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {"fetch_control", "fetch_progress", "fetch_log"} <= names

    def load_control(self) -> Control:
        kv = {r["key"]: r["value"] for r in self.db.execute("SELECT key, value FROM fetch_control")}
        return Control(
            kill_switch=kv.get("kill_switch", "false").lower() == "true",
            breaker_tripped=kv.get("breaker_tripped", "false").lower() == "true",
            cooldown_until_utc=kv.get("cooldown_until_utc") or None,
            global_last_request_utc=kv.get("global_last_request_utc") or None,
            daily_day_pkt=kv.get("daily_day_pkt") or None,
            daily_count=int(kv.get("daily_count", "0") or 0),
            robots_txt=kv.get("robots_txt") or None,
            robots_fetched_utc=kv.get("robots_fetched_utc") or None,
            first_live_day=kv.get("first_live_day") or None)

    def save_control(self, c: Control) -> None:
        values = {"kill_switch": str(c.kill_switch).lower(),
                  "breaker_tripped": str(c.breaker_tripped).lower(),
                  "cooldown_until_utc": c.cooldown_until_utc or "",
                  "global_last_request_utc": c.global_last_request_utc or "",
                  "daily_day_pkt": c.daily_day_pkt or "", "daily_count": str(c.daily_count),
                  "robots_txt": c.robots_txt or "", "robots_fetched_utc": c.robots_fetched_utc or "",
                  "first_live_day": c.first_live_day or ""}
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for key, value in values.items():
            self.db.execute("INSERT INTO fetch_control (key, value, updated_utc) VALUES (?, ?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                            "updated_utc = excluded.updated_utc", (key, value, now))

    def load_done(self) -> set[str]:
        return {r["resource_key"] for r in self.db.execute(
            "SELECT resource_key FROM fetch_progress WHERE status = 'done'")}

    def save_done(self, key: str) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.db.execute("INSERT INTO fetch_progress (resource_key, status, last_result, updated_utc) "
                        "VALUES (?, 'done', 'ok', ?) ON CONFLICT(resource_key) DO UPDATE "
                        "SET status = 'done', "
                        "updated_utc = excluded.updated_utc", (key, now))

    def log(self, event: str, detail: str) -> None:
        self.db.execute("INSERT INTO fetch_log (ts_utc, event, detail) VALUES (?, ?, ?)",
                        (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), event, detail[:500]))


CORE_FIRST = ("MEBL", "LUCK", "OGDC", "FFC", "APL", "HUBC")  # owner-approved core names first


def resources_for(symbols: list[str]) -> list[tuple[str, str]]:
    """Fundamentals first, then profile, then competitors; core names first within each."""
    order = [s for s in CORE_FIRST if s in symbols] + sorted(s for s in symbols if s not in CORE_FIRST)
    return [(s, ep) for ep in ("fundamentals", "profile", "competitors") for s in order]


# ------------------------------------------------- the entrypoint (one tick, from the scheduler)

WATCHLIST_PATH = Path(__file__).resolve().parents[1] / "config" / "coverage_watchlist.json"


# THE one default contact, used when PSXNI_CONTACT_EMAIL is unset or empty; the variable overrides it.
DEFAULT_CONTACT = "https://github.com/imranrazabozdar/psx-news-intelligence"
CONTACT_VAR = "PSXNI_CONTACT_EMAIL"
_LOCAL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")
_LABEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


def _is_email(value: str) -> bool:
    """Plain string checks, no regex: bounded length, one @, a dotted domain of clean labels."""
    if len(value) > 254 or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    labels = domain.split(".")
    return (bool(local) and set(local) <= _LOCAL_CHARS and len(labels) >= 2
            and all(lab and set(lab) <= _LABEL_CHARS and not lab.startswith("-") and not lab.endswith("-")
                    for lab in labels))


def validate_contact(value: str) -> str | None:
    """A plausible email or an https:// public project URL. Anything else is refused."""
    if any(ch.isspace() for ch in value):
        return None
    if value.startswith("https://"):
        parts = urlsplit(value)
        return value if parts.hostname and "." in parts.hostname and parts.username is None else None
    return value if _is_email(value) else None


def resolve_contact(environ: Mapping[str, str]) -> str | None:
    """The contact to use. Unset or empty: the default. Set: it must validate, else None (a no-op)."""
    raw = environ.get(CONTACT_VAR)
    if raw is None or raw == "":
        return DEFAULT_CONTACT
    return validate_contact(raw)


def user_agent(contact: str | None) -> str | None:
    """The honest User-Agent. A contact that does not validate yields None (refused: no request)."""
    if not contact:
        return None
    checked = validate_contact(contact)
    return None if checked is None else f"PSX-NI/1.0 (private, consented; contact: {checked})"


def fetch_http(ua: str) -> Callable[[str, str], tuple[int | None, dict[str, str], bytes]]:
    from collectors import investify_job as job

    def fetch(sym: str, endpoint: str) -> tuple[int | None, dict[str, str], bytes]:
        url = BASE + "/robots.txt" if sym == "robots" else resource_url((sym, endpoint))
        try:
            status, headers, body = job.default_transport(url, {"User-Agent": ua, "Accept": "text/html"})
            return status, headers, body
        except Exception:  # noqa: BLE001 - any network failure is a block: stop, do not retry
            return None, {}, b""

    return fetch


def store_fields(db: Any) -> Callable[[str, str, bytes], int]:
    """Distilled fields only, written as sourced, dated rows of research_fact (never the raw body, never the
    Investify description). Returns the number of rows written."""
    from collectors import investify_fundamentals as fund
    from engines import research_facts as rf

    def store(sym: str, endpoint: str, body: bytes) -> int:
        extractor = fund.EXTRACTORS.get(endpoint)
        if extractor is None:
            return 0
        fields = extractor(body, sym)
        rows = rf.rows_from_fields(company=sym, endpoint=endpoint, fields=fields,
                                   url=resource_url((sym, endpoint)),
                                   fetched_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return rf.insert_rows(db, rows)

    return store


def main(environ: Mapping[str, str] | None = None) -> int:
    from engines import library_db

    env = os.environ if environ is None else environ
    now = datetime.now(UTC)
    # Library first: nothing touches Investify until psx-library answers and the state tables exist.
    try:
        conn = library_db.get_library_connection(env)
        library_db.auth_check(conn)
    except library_db.LibraryConfigError as exc:
        print(f"no-op: {exc}")
        return 0
    except Exception as exc:  # noqa: BLE001 - unreachable or unauthenticated: stop before any request
        print(f"no-op: psx-library unreachable or unauthenticated: {exc}")
        return 1
    state = LibraryState(conn.db)
    if not state.tables_present():
        print("no-op: fetch-state tables are not in psx-library (the migration needs owner approval)")
        return 0
    ua = user_agent(resolve_contact(env))
    if ua is None:
        print(f"no-op: {CONTACT_VAR} is refused (a plausible email or an https:// URL only)")
        return 0

    def load_control() -> Control:
        return state.load_control()

    def save_control(c: Control) -> None:
        if c.first_live_day is None and c.global_last_request_utc:
            c = Control(**{**c.__dict__, "first_live_day": now.astimezone(gc.PKT).date().isoformat()})
        state.save_control(c)

    deps = Dependencies(load_control=load_control, save_control=save_control, load_done=state.load_done,
                        save_done=state.save_done, fetch=fetch_http(ua),
                        store=store_fields(conn.db), log=state.log)
    symbols = [c["symbol"] for c in json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))["companies"]]
    policy_file = json.loads(gc.POLICY_PATH.read_text(encoding="utf-8"))
    d = tick(now, deps, calendar=gc.load_calendar_safe(), resources=resources_for(symbols),
             first_live_day=None, env=env, exceptions=policy_file.get("one_day_exceptions", {}))
    print(f"tick: {d.action}: {d.reason} (host={conn.host})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _breaker_text(control: Control) -> str:
    if control.breaker_tripped:
        return f"tripped, cooling until {control.cooldown_until_utc}"
    return "clear"


def render_fetch_log(*, day: str, done: int, total: int, control: Control, events: list[tuple[str, str]],
                     breaker_note: str | None = None) -> str:
    """The end-of-day view, rendered from state only. No network, no raw data."""
    pct = round(100 * done / total, 1) if total else 0.0
    lines = [
        f"# Investify fetch log, {day} (Pakistan time)",
        "",
        "Private research use. Source: investify.pk.",
        "",
        f"- Backfill: {done} of {total} resources complete ({pct}%).",
        f"- Kill switch: {'on' if control.kill_switch else 'off'} (manual stop: psx-library fetch_control).",
        f"- Requests today: {control.daily_count if control.daily_day_pkt == day else 0}.",
        f"- Breaker: {_breaker_text(control)}.",
    ]
    if breaker_note:
        lines.append(f"- Note: {breaker_note}")
    lines += ["", "## Events today", ""]
    lines += [f"- {event}: {detail}" for event, detail in events] or ["- none"]
    return "\n".join(lines) + "\n"
