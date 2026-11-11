"""
termux_node_runner.py
=====================

Fault-tolerant, polite, single-shot ingestion runner for the Pattern C node
(a spare Android device under Termux, or any low-power Linux box). Designed to
be invoked by ``crond`` a couple of times an hour during PSX trading hours.

What one invocation does:

  1. Refuse to run outside trading hours (09:00-16:30 PKT, Mon-Fri).
  2. Fetch ONLY the small delta feed archive (announceWithSymbol.lis).
  3. Parse it, drop rows already seen (sqlite dedup on doc_id/row hash).
  4. Route each NEW announcement and dispatch its structured metadata payload
     to the cloud database endpoint.
  5. Optionally (off by default) fetch flash-filing binaries, preferring open
     mirrors and never touching the exchange edge except by disclosed id under
     rate-limited, robots-respecting, back-off-on-block controls.

Standard library only (urllib, sqlite3, zoneinfo, json, logging). The parser
and router modules sit beside this file.

Politeness is not decorative here: ``PoliteSession`` honours robots.txt, sends
an honest identifying User-Agent (no browser impersonation), rate-limits per
host, and on 403/429 BACKS OFF rather than retrying or rotating anything.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import sqlite3
import time as _time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime
from datetime import time as dtime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from engines.document_router import RouteDecision, Source, route
from engines.psx_feed_parser import StatutoryAnnouncement, coerce_date, load_announcements

logger = logging.getLogger("psx.node")

PKT = ZoneInfo("Asia/Karachi")
TRADING_START = dtime(9, 0)
TRADING_END = dtime(16, 30)

# Honest, contactable identity. Do not change this to mimic a browser.
USER_AGENT = os.environ.get(
    "PSX_USER_AGENT",
    "PSX-Public-Disclosure-Reader/1.0 (personal investor tooling; polite, low-volume)",
)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class Config:
    feed_url: str  # URL of the announceWithSymbol.lis archive
    cloud_endpoint: str  # HTTPS endpoint that stores metadata rows
    cloud_token: str | None = None  # bearer token for the endpoint, if any
    state_db: str = os.path.expanduser("~/.psx_node/seen.sqlite3")
    min_request_interval_s: float = 3.0  # per-host floor between requests
    fetch_binaries: bool = False  # keep False: metadata-only by default
    request_timeout_s: float = 30.0
    respect_robots: bool = True
    # Open Telegram/JSON syndication mirror index (Pattern D). When set, flash
    # filings are resolved to the mirror's own hosted PDF copy. None disables it.
    mirror_api_url: str | None = None

    @classmethod
    def from_env(cls) -> Config:
        feed = os.environ.get("PSX_FEED_URL")
        endpoint = os.environ.get("PSX_CLOUD_ENDPOINT")
        if not feed or not endpoint:
            raise SystemExit("set PSX_FEED_URL and PSX_CLOUD_ENDPOINT environment variables")
        return cls(
            feed_url=feed,
            cloud_endpoint=endpoint,
            cloud_token=os.environ.get("PSX_CLOUD_TOKEN"),
            state_db=os.environ.get("PSX_STATE_DB", cls.state_db),
            fetch_binaries=os.environ.get("PSX_FETCH_BINARIES", "0") == "1",
            mirror_api_url=os.environ.get("PSX_MIRROR_API_URL") or None,
        )


# --------------------------------------------------------------------------- #
# Trading-hours gate
# --------------------------------------------------------------------------- #


def within_trading_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(PKT)
    if now.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return TRADING_START <= now.timetz().replace(tzinfo=None) <= TRADING_END


# --------------------------------------------------------------------------- #
# Polite HTTP
# --------------------------------------------------------------------------- #


def _require_http(url: str) -> None:
    """Refuse any scheme other than http(s); the URLs come from operator configuration."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"only http(s) URLs are allowed: {url!r}")


class PoliteBackoff(Exception):
    """Raised when a host asks us to slow down (403/429). Caller must stop."""


class PoliteSession:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    # -- robots -----------------------------------------------------------
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(origin)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "robots.txt unreadable for %s (%s); treating as disallow for safety", origin, exc
                )
                # Fail closed: if we cannot read robots, do not fetch.
                rp.disallow_all = True  # type: ignore[attr-defined]
            self._robots[origin] = rp
        return rp

    def _allowed(self, url: str) -> bool:
        if not self.cfg.respect_robots:
            return True
        rp = self._robots_for(url)
        if getattr(rp, "disallow_all", False):
            return False
        return rp.can_fetch(USER_AGENT, url)

    # -- rate limit -------------------------------------------------------
    def _throttle(self, url: str) -> None:
        from urllib.parse import urlsplit

        host = urlsplit(url).netloc
        last = self._last_hit.get(host, 0.0)
        wait = self.cfg.min_request_interval_s - (_time.monotonic() - last)
        if wait > 0:
            _time.sleep(wait)
        self._last_hit[host] = _time.monotonic()

    # -- fetch ------------------------------------------------------------
    def get(self, url: str) -> bytes:
        _require_http(url)
        if not self._allowed(url):
            raise PoliteBackoff(f"robots.txt disallows {url}")
        self._throttle(url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - scheme checked
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.request_timeout_s) as r:  # noqa: S310
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                # The operator is signalling "not like this". Honour it.
                raise PoliteBackoff(f"{exc.code} from {url}; backing off") from exc
            raise


# --------------------------------------------------------------------------- #
# Dedup state
# --------------------------------------------------------------------------- #


class SeenStore:
    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " key TEXT PRIMARY KEY, symbol TEXT, doc_id INTEGER, first_seen TEXT)"
        )
        self.conn.commit()

    @staticmethod
    def key_for(a: StatutoryAnnouncement) -> str:
        if a.doc_id is not None:
            return f"doc:{a.doc_id}"
        # No attachment: hash the stable identity of the notice.
        raw = f"{a.date.isoformat()}|{a.time}|{a.symbol}|{a.title}"
        return "txt:" + hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

    def is_new(self, a: StatutoryAnnouncement) -> bool:
        key = self.key_for(a)
        cur = self.conn.execute("SELECT 1 FROM seen WHERE key = ?", (key,))
        return cur.fetchone() is None

    def mark(self, a: StatutoryAnnouncement) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen(key, symbol, doc_id, first_seen) VALUES (?, ?, ?, ?)",
            (self.key_for(a), a.symbol, a.doc_id, datetime.now(PKT).isoformat()),
        )
        self.conn.commit()


# --------------------------------------------------------------------------- #
# Cloud dispatch (fault tolerant)
# --------------------------------------------------------------------------- #


def dispatch_metadata(cfg: Config, decision: RouteDecision, announcement: StatutoryAnnouncement) -> bool:
    payload = {
        "date": announcement.date.isoformat(),
        "time": announcement.time.isoformat() if announcement.time else None,
        "symbol": announcement.symbol,
        "category": announcement.category,
        "title": announcement.title,
        "doc_id": announcement.doc_id,
        "track": decision.track.value,
        "source": decision.source.value,
        "target_url": decision.url,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if cfg.cloud_token:
        headers["Authorization"] = f"Bearer {cfg.cloud_token}"

    for attempt in range(3):
        try:
            _require_http(cfg.cloud_endpoint)
            req = urllib.request.Request(cfg.cloud_endpoint, data=body, headers=headers, method="POST")  # noqa: S310 - scheme checked
            with urllib.request.urlopen(req, timeout=cfg.request_timeout_s) as r:  # noqa: S310
                if 200 <= r.status < 300:
                    return True
                logger.warning("cloud dispatch HTTP %s", r.status)
        except Exception as exc:  # noqa: BLE001 - never let one row kill the run
            logger.warning("cloud dispatch attempt %d failed: %s", attempt + 1, exc)
            _time.sleep(2**attempt)
    return False


# --------------------------------------------------------------------------- #
# Main run
# --------------------------------------------------------------------------- #


def run_once(cfg: Config, *, force: bool = False) -> dict[str, int]:
    stats = {"parsed": 0, "new": 0, "dispatched": 0, "binaries": 0, "skipped": 0}

    if not force and not within_trading_hours():
        logger.info("outside PSX trading hours; nothing to do")
        return stats

    session = PoliteSession(cfg)
    store = SeenStore(cfg.state_db)
    ir_registry = _load_ir_registry()
    resolver = TelegramMirrorResolver(cfg, session)  # no-op when mirror unset

    try:
        archive = session.get(cfg.feed_url)
    except PoliteBackoff as exc:
        logger.warning("feed fetch asked us to back off: %s", exc)
        return stats

    announcements = load_announcements(archive)
    stats["parsed"] = len(announcements)

    for a in announcements:
        if not store.is_new(a):
            continue
        stats["new"] += 1
        decision = route(a, ir_registry=ir_registry, mirror_resolver=resolver)

        if dispatch_metadata(cfg, decision, a):
            stats["dispatched"] += 1
            store.mark(a)  # only mark seen once metadata is safely stored
        else:
            stats["skipped"] += 1
            continue  # retry on next cron tick

        if cfg.fetch_binaries and decision.track.value == "flash" and decision.url:
            # Prefer open mirrors; only touch the edge by disclosed id, politely.
            try:
                _maybe_fetch_flash(session, decision)
                stats["binaries"] += 1
            except PoliteBackoff as exc:
                logger.info("flash fetch deferred (operator back-off): %s", exc)

    logger.info("run complete: %s", stats)
    return stats


def _maybe_fetch_flash(session: PoliteSession, decision: RouteDecision) -> bytes:
    if decision.source is Source.EXCHANGE_EDGE:
        logger.info("edge fetch for disclosed doc_id=%s", decision.doc_id)
    data = session.get(decision.url)  # PoliteSession enforces robots + backoff
    # Hand off to your object store here. Kept in-memory in this reference impl.
    return data


# --------------------------------------------------------------------------- #
# Pluggable registries (replace with your own data sources)
# --------------------------------------------------------------------------- #


def _load_ir_registry() -> dict[str, str]:
    """Load symbol -> IR base URL. Override via PSX_IR_REGISTRY (JSON file)."""
    path = os.environ.get("PSX_IR_REGISTRY")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


# Field-name aliases tolerated in a mirror post (schemas vary across channels).
_MIRROR_SYMBOL_KEYS = ("symbol", "sym", "ticker", "scrip")
_MIRROR_DATE_KEYS = ("date", "announced", "announced_at", "timestamp", "ts", "time")
_MIRROR_PDF_KEYS = ("pdf_url", "pdf", "document_url", "file_url", "url", "link")
_MIRROR_DOCID_KEYS = ("doc_id", "document_id", "id")


def _first(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _mirror_date_to_iso(value) -> str | None:
    """Normalise a mirror post's date to an ISO date string, or None."""
    if value is None:
        return None
    # Epoch seconds / millis.
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            ts = float(value)
            if ts > 1e12:  # millis
                ts /= 1000.0
            return datetime.fromtimestamp(ts, PKT).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    # Textual: ISO first, then the PSX/common formats the parser understands.
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(PKT).date().isoformat()
    except ValueError:
        pass
    try:
        return coerce_date(text[:11]).isoformat()
    except ValueError:
        return None


def _is_open_pdf_url(url: str) -> bool:
    """True only for a real http(s) URL that is NOT the PSX gated edge host."""
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    return "psx.com.pk" not in p.netloc.lower()


class TelegramMirrorResolver:
    """Pattern-D resolver: look up a flash filing's OPEN hosted PDF copy.

    Reads an open syndication mirror (public Telegram channel JSON mirror, or
    any JSON index) once per run, indexes posts by ``(symbol, date)``, and
    returns the mirror's own hosted PDF URL for a matching announcement.

    Deliberate constraints:
      * Returns a URL only when it is an open host (never a dps.psx.com.pk edge
        link) -- the mirror is a way AROUND the edge, not a backdoor TO it.
      * Fetches the index a single time, politely (robots + rate limit + 403/429
        back-off via PoliteSession); any failure yields an empty index and the
        router falls through to its normal path. Never raises into the loop.
      * A no-op (always None) when no mirror is configured.
    """

    def __init__(self, cfg: Config, session: PoliteSession) -> None:
        self.cfg = cfg
        self.session = session
        self._index: dict[tuple[str, str], dict] | None = None

    def _ensure_index(self) -> dict[tuple[str, str], dict]:
        if self._index is not None:
            return self._index
        self._index = {}
        if not self.cfg.mirror_api_url:
            return self._index
        try:
            raw = self.session.get(self.cfg.mirror_api_url)
            payload = json.loads(raw.decode("utf-8", "replace"))
        except PoliteBackoff as exc:
            logger.info("mirror index back-off: %s", exc)
            return self._index
        except Exception as exc:  # noqa: BLE001 - mirror is best-effort
            logger.warning("mirror index unavailable: %s", exc)
            return self._index

        # Accept a bare list, or {"messages"/"posts"/"result": [...]}.
        posts = payload
        if isinstance(payload, dict):
            for key in ("messages", "posts", "result", "data", "items"):
                if isinstance(payload.get(key), list):
                    posts = payload[key]
                    break
        if not isinstance(posts, list):
            logger.warning("mirror index shape unrecognised; ignoring")
            return self._index

        for post in posts:
            if not isinstance(post, dict):
                continue
            symbol = _first(post, _MIRROR_SYMBOL_KEYS)
            date_iso = _mirror_date_to_iso(_first(post, _MIRROR_DATE_KEYS))
            if not symbol or not date_iso:
                continue
            self._index[(str(symbol).strip().upper(), date_iso)] = post

        logger.info("mirror index: %d dated posts", len(self._index))
        return self._index

    def __call__(self, announcement: StatutoryAnnouncement) -> str | None:
        index = self._ensure_index()
        if not index:
            return None
        post = index.get((announcement.symbol, announcement.date.isoformat()))
        if not post:
            return None
        pdf_url = _first(post, _MIRROR_PDF_KEYS)
        if pdf_url and _is_open_pdf_url(str(pdf_url)):
            doc_id = _first(post, _MIRROR_DOCID_KEYS)
            logger.info(
                "mirror hit %s %s (doc_id=%s) -> open copy", announcement.symbol, announcement.date, doc_id
            )
            return str(pdf_url)
        # Mirror knew of it but only via the gated edge: decline, stay honest.
        return None


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PSX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ap = argparse.ArgumentParser(description="PSX polite ingestion node (single shot)")
    ap.add_argument("--force", action="store_true", help="ignore the trading-hours gate (testing only)")
    args = ap.parse_args()
    cfg = Config.from_env()
    run_once(cfg, force=args.force)


if __name__ == "__main__":
    main()
