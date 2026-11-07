"""Polite HTTP client for collectors (standard library only).

* Identifies itself with a descriptive User-Agent.
* Obeys robots.txt (cached per host). A disallowed URL is never fetched.
* Per-host rate limit (minimum interval between requests).
* Timeouts, retries with exponential backoff for network errors / 429 / 5xx, honouring
  Retry-After (capped).
* Conditional requests (If-None-Match / If-Modified-Since); 304 is reported, not an error.
* Response size cap, so a misbehaving source cannot exhaust memory.

The network is reached only through `Transport`, which tests replace with a fake.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

USER_AGENT = ("psx-news-intelligence/0.2 (+https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE; "
              "research collector; respects robots.txt)")
MAX_BYTES = 5_000_000


class FetchError(RuntimeError):
    """A request failed permanently (after retries) or was refused by policy."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class RobotsDisallowed(FetchError):
    pass


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int

    @property
    def not_modified(self) -> bool:
        return self.status == 304


# A transport takes (url, headers, timeout) and returns (status, headers, body) or raises
# urllib.error.HTTPError / URLError / TimeoutError like urllib does.
Transport = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes]]


def urllib_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    if urlsplit(url).scheme not in ("https", "http"):
        raise FetchError(f"unsupported scheme: {url}", url=url)
    req = urllib.request.Request(url, headers=headers)  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            body = r.read(MAX_BYTES + 1)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, {k.lower(): v for k, v in exc.headers.items()}, b""
        raise


@dataclass
class HttpClient:
    transport: Transport = urllib_transport
    timeout: float = 25.0
    max_attempts: int = 3
    backoff_base: float = 2.0
    max_retry_after: float = 60.0
    min_interval: float = 2.0  # seconds between requests to the same host
    respect_robots: bool = True
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    requests_made: int = 0
    _last_request: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(default_factory=dict)

    # ------------------------------------------------------------ policy
    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()

    def allowed_by_robots(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                status, _, body = self._send(origin + "/robots.txt", {})
                if status == 200:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                elif status in (401, 403):
                    rp.disallow_all = True  # access to robots.txt refused: be conservative
                else:
                    rp = None  # no robots.txt: nothing disallowed
            except FetchError as exc:
                if exc.status in (401, 403):
                    rp = urllib.robotparser.RobotFileParser()
                    rp.disallow_all = True  # robots.txt refused: be conservative
                else:
                    rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    # ------------------------------------------------------------ requests
    def _send(self, url: str, extra_headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"} | extra_headers
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle(host)
            self.requests_made += 1
            try:
                status, hdrs, body = self.transport(url, headers, self.timeout)
                if len(body) > MAX_BYTES:
                    raise FetchError(f"response larger than {MAX_BYTES} bytes", url=url)
                return status, hdrs, body
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == self.max_attempts:
                    raise FetchError(f"HTTP {exc.code}", status=exc.code, url=url) from exc
                ra = (exc.headers or {}).get("Retry-After") if exc.headers else None
                delay = float(ra) if ra and str(ra).isdigit() else self.backoff_base ** attempt
                self.sleep(min(delay, self.max_retry_after))
                last_exc = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    break
                self.sleep(self.backoff_base ** attempt)
        raise FetchError(f"request failed after {self.max_attempts} attempts: {last_exc}", url=url)

    def get(self, url: str, *, etag: str | None = None, last_modified: str | None = None) -> Response:
        if not self.allowed_by_robots(url):
            raise RobotsDisallowed("disallowed by robots.txt", url=url)
        cond = {}
        if etag:
            cond["If-None-Match"] = etag
        if last_modified:
            cond["If-Modified-Since"] = last_modified
        start = self.clock()
        status, headers, body = self._send(url, cond)
        return Response(url, status, headers, body, int((self.clock() - start) * 1000))
