"""Permissioned fetcher for the SCS Trade and PSX sources (standard library only).

Scope is set by written permission recorded in docs/SOURCE_ACCESS_REGISTER.md (2026-11-09):

* The only User-Agent is the one the joint compliance team approved, exactly as written.
  No browser identities are sent, rotated or implied, and no other browser headers are added.
* Every request is preceded by a random delay of 3.5 to 8.5 seconds.
* Requests are made only outside PSX trading hours (PKT, per config/psx_calendar.json).
* Only hosts named in the caller's allow-list are reachable; robots.txt is obeyed for the
  approved User-Agent.

The network is reached only through `transport`, which tests replace with a fake. Nothing in
this module starts a collection; it has no scheduler and no database access.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import urlsplit

from engines.market_calendar import TradingCalendar

APPROVED_USER_AGENT = "PSX-NEWS-INTELLIGENCE research bot, contact owner"
JITTER_MIN_SECONDS = 3.5
JITTER_MAX_SECONDS = 8.5
PKT = timezone(timedelta(hours=5))
DATA_DELAY_MINUTES = 15  # only data settled at least this long ago may be requested
MAX_BYTES = 5_000_000

Transport = Callable[[str, dict[str, str], float], tuple[int, bytes]]


class PermissionRefused(RuntimeError):
    """A request was refused by policy before any network access."""


class DelayRefused(PermissionRefused):
    """Requested data is not yet settled for the mandatory exchange delay."""


class OffPeakRefused(PermissionRefused):
    """Collection is allowed only outside PSX trading hours."""


def is_off_peak(now_utc: datetime, calendar: TradingCalendar) -> bool:
    """True when collection is allowed: not inside PSX regular trading hours.

    On a trading day with no recorded hours the answer is False (refuse when unsure).
    On a non-trading day any time is off-peak.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    local = now_utc.astimezone(PKT)
    day = local.date().isoformat()
    if not calendar.is_trading_day(day):
        return True
    hours = calendar.hours(day)
    if hours is None:
        return False
    open_min, close_min = hours
    minute = local.hour * 60 + local.minute
    return minute < open_min or minute >= close_min


def jitter_seconds(rng: random.Random) -> float:
    return rng.uniform(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS)


@dataclass
class PermissionedFetcher:
    allowed_hosts: frozenset[str]
    calendar: TradingCalendar
    transport: Transport
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    timeout: float = 30.0
    requests_made: int = 0
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must not be empty")
        self.allowed_hosts = frozenset(h.lower() for h in self.allowed_hosts)

    # ---------------------------------------------------------------- policy checks
    def _check_host(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise PermissionRefused(f"only https is permitted: {url}")
        host = (parts.hostname or "").lower()
        if host not in self.allowed_hosts:
            raise PermissionRefused(f"host not in the approved list: {host}")
        return host

    def _check_time(self) -> None:
        if not is_off_peak(self.now(), self.calendar):
            raise OffPeakRefused("PSX trading hours: collection is permitted only after market close")

    def _robots_allows(self, host: str, url: str) -> bool:
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"https://{host}/robots.txt"
            status, body = self._raw(robots_url)
            if status == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
                self._robots[host] = rp
            elif status in (401, 403):
                self._robots[host] = None
                raise PermissionRefused(f"robots.txt refused ({status}); collection stopped for {host}")
            else:  # 404 and other non-200: no robots rules published
                self._robots[host] = None
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(APPROVED_USER_AGENT, url)

    # ---------------------------------------------------------------- requests
    def _raw(self, url: str) -> tuple[int, bytes]:
        self.sleep(jitter_seconds(self.rng))
        self.requests_made += 1
        headers = {"User-Agent": APPROVED_USER_AGENT}
        try:
            status, body = self.transport(url, headers, self.timeout)
        except urllib.error.HTTPError as exc:
            return exc.code, b""
        if len(body) > MAX_BYTES:
            raise PermissionRefused(f"response larger than {MAX_BYTES} bytes: {url}")
        return status, body

    def _check_delay(self, data_as_of_utc: datetime) -> None:
        """Refuse any request for data not yet settled for DATA_DELAY_MINUTES."""
        if data_as_of_utc.tzinfo is None:
            raise ValueError("data_as_of_utc must be timezone-aware")
        latest = self.now() - timedelta(minutes=DATA_DELAY_MINUTES)
        if data_as_of_utc > latest:
            raise DelayRefused(
                f"data as of {data_as_of_utc.isoformat()} is inside the {DATA_DELAY_MINUTES}-minute "
                f"exchange delay (latest permitted {latest.isoformat()})")

    def fetch(self, url: str, *, data_as_of_utc: datetime) -> bytes:
        """Return the body of an allowed, delayed, off-peak, robots-compliant GET request.

        `data_as_of_utc` is the latest timestamp of the data requested. It is required, so
        every request states what it is asking for, and it must be at least 15 minutes old.
        """
        host = self._check_host(url)
        self._check_delay(data_as_of_utc)
        self._check_time()
        if not self._robots_allows(host, url):
            raise PermissionRefused(f"robots.txt disallows this path for the approved agent: {url}")
        status, body = self._raw(url)
        if status != 200:
            raise PermissionRefused(f"HTTP {status} for {url}")
        return body


def urllib_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """Production transport: one plain GET with the approved headers only."""
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - https enforced
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def approved_hosts(names: Iterable[str]) -> frozenset[str]:
    return frozenset(n.lower() for n in names)
