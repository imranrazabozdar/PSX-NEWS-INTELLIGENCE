"""Polite, rate-limited retrieval of owner-permitted filing PDFs into the local vault.

The fetcher runs once per invocation (python -m services.source_fetcher --once). An external scheduler,
using the polling_schedule in the registry, decides when; the fetcher never schedules itself.

Guards, in order, for every source:

1. Fail closed: only permission_status "permitted" with an https endpoint_url may be fetched. Anything
   else is reported as SKIPPED_NOT_PERMITTED and no network call is made. 2. Politeness: a per-host
   minimum interval (never below 3 s), one active connection per host, and HTTP 429 handled with Retry-
   After or exponential backoff with jitter (bounded attempts). 3. Conditional requests: If-None-Match /
   If-Modified-Since from the last successful response; 304 is NOT_MODIFIED. 4. Content checks: Content-
   Type must be application/pdf and the body must start with %PDF-. Anything else is discarded
   (REJECTED_NOT_PDF) and not stored. 5. Atomic vault write: the body is streamed to a .tmp file with
   SHA-256 computed on the fly. If {sha256}.pdf already exists the write is aborted (SKIPPED_DUPLICATE)
   and nothing is overwritten. Otherwise the temporary file is linked to {sha256}.pdf (no overwrite) and
   removed. 6. Dispatch: a newly stored PDF is diagnosed by scripts.financial_intake --text (never with
   --archive), and the result is appended to vault_ingestion_log.json.

Time, sleep, the HTTP opener and randomness are injected, so the behaviour is tested without any network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engines import document_intake as di

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "fetch_targets.json"
OWNER_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "sources_registry.json"
DEFAULT_INTERVAL = 5
MIN_INTERVAL = 3
PERMISSIONS = ("permitted", "paused")
FRAMEWORKS = ("bank", "corporate")
MAX_ATTEMPTS = 4  # the first request plus three retries after 429
BACKOFF_BASE = 5.0
BACKOFF_CAP = 300.0
MAX_BYTES = 80 * 1024 * 1024
CHUNK = 64 * 1024
STATE_FILE = "source_fetch_state.json"
LOG_FILE = "vault_ingestion_log.json"
_PDF_MAGIC = b"%PDF-"


class RegistryError(ValueError):
    """The registry is malformed. The fetcher refuses to run; it never guesses a field."""


@dataclass(frozen=True)
class Source:
    symbol: str
    company_id: int | None
    endpoint_url: str | None
    permission_status: str
    expected_framework: str
    min_request_interval_seconds: int
    polling_schedule: str
    intake: dict | None


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise RegistryError(message)


def parse_registry(data: dict) -> list[Source]:
    """Validate the registry.

    Unknown permissions or frameworks, non-https URLs and short intervals are errors."""
    _require(
        isinstance(data, dict) and isinstance(data.get("sources"), list), "registry needs a 'sources' list"
    )
    out: list[Source] = []
    for i, raw in enumerate(data["sources"]):
        where = f"sources[{i}]"
        _require(isinstance(raw, dict), f"{where} must be an object")
        symbol = str(raw.get("symbol", "")).strip().upper()
        _require(bool(re.fullmatch(r"[A-Z0-9]{2,10}", symbol)), f"{where}: symbol must be a PSX ticker")
        perm = raw.get("permission_status", "paused")
        _require(perm in PERMISSIONS, f"{where} ({symbol}): permission_status must be one of {PERMISSIONS}")
        framework = raw.get("expected_framework")
        _require(
            framework in FRAMEWORKS, f"{where} ({symbol}): expected_framework must be one of {FRAMEWORKS}"
        )
        url = raw.get("endpoint_url")
        if url is not None:
            _require(
                isinstance(url, str) and url.startswith("https://"),
                f"{where} ({symbol}): endpoint_url must be an https URL or null",
            )
        if perm == "permitted":
            _require(url is not None, f"{where} ({symbol}): a permitted source needs an endpoint_url")
        interval = raw.get("min_request_interval_seconds", DEFAULT_INTERVAL)
        _require(
            isinstance(interval, int) and not isinstance(interval, bool) and interval >= MIN_INTERVAL,
            f"{where} ({symbol}): min_request_interval_seconds must be an integer >= {MIN_INTERVAL}",
        )
        company = raw.get("company_id")
        _require(
            company is None or (isinstance(company, int) and not isinstance(company, bool)),
            f"{where} ({symbol}): company_id must be an integer or null",
        )
        schedule = raw.get("polling_schedule", "")
        _require(
            isinstance(schedule, str) and schedule.strip() != "",
            f"{where} ({symbol}): polling_schedule must be a non-empty cron or interval string",
        )
        intake = raw.get("intake")
        if intake is not None:
            _require(
                isinstance(intake, dict) and "period_end" in intake and "columns" in intake,
                f"{where} ({symbol}): intake needs period_end and columns",
            )
        out.append(Source(symbol, company, url, perm, framework, interval, schedule, intake))
    symbols = [s.symbol for s in out]
    _require(len(symbols) == len(set(symbols)), "registry has a duplicate symbol")
    return out


def owner_permits(source: Source, owner_sources: list | None = None) -> bool:
    """The owner's source registry must hold a permitted, enabled annual_report entry for this symbol.

    The entry's url_pattern must match the endpoint. It is read through engines.source_registry, the owner's
    own governance module. With the shipped (empty) registry nothing is permitted.
    """
    from engines import source_registry as owner

    if owner_sources is None:
        owner_sources = owner.load(OWNER_REGISTRY_PATH)
    if not source.endpoint_url:
        return False
    for entry in owner.automated_allowed(
        owner_sources, symbol=source.symbol, category="annual_report", financial_year=None
    ):
        pattern = (entry.url_pattern or "").split("{", 1)[0]  # the fixed part of the pattern
        if pattern and source.endpoint_url.startswith(pattern):
            return True
    return False


def load_registry(path: Path | str = REGISTRY_PATH) -> list[Source]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"registry cannot be read: {type(exc).__name__}") from exc
    return parse_registry(data)


# ---------------------------------------------------------- politeness: per-host timing and concurrency


class HostPolicy:
    """Per-host minimum interval and one active connection per host (a lock per host)."""

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep
    ):
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def pause(self, seconds: float) -> None:
        """Back off (after a 429): sleep the given time."""
        self._sleep(seconds)

    def lock(self, host: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def wait(self, host: str, interval: float) -> float:
        """Sleep until `interval` seconds have passed since the last request to this host.

        Returns the time slept."""
        slept = 0.0
        last = self._last.get(host)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
                slept = remaining
        self._last[host] = self._clock()
        return slept


def backoff_delay(attempt: int, retry_after: float | None, rng: random.Random) -> float:
    """Seconds to wait after a 429.

    Retry-After wins when given; otherwise the wait is exponential in the attempt. Jitter adds up to 25 % so
    that parallel clients do not retry together. Capped."""
    base = retry_after if retry_after is not None else BACKOFF_BASE * (2**attempt)
    base = min(base, BACKOFF_CAP)
    return min(base + rng.uniform(0, 0.25 * base), BACKOFF_CAP)


def _retry_after(headers: Any) -> float | None:
    raw = headers.get("retry-after") if headers is not None else None  # headers are lower-cased
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None  # an HTTP-date is not parsed here: the exponential backoff applies


# ------------------------------------------------------------------ the transport


def default_opener(request: urllib.request.Request) -> Any:
    """Open a request. HTTP errors are returned as responses (they carry status and headers), not raised."""
    try:
        return urllib.request.urlopen(request, timeout=60)  # noqa: S310 - https only, enforced by the registry
    except urllib.error.HTTPError as exc:
        return exc


def _status(resp: Any) -> int:
    return int(getattr(resp, "status", None) or getattr(resp, "code", 0))


def _headers(resp: Any) -> dict[str, str]:
    h = getattr(resp, "headers", None) or {}
    return {str(k).lower(): str(v) for k, v in h.items()} if hasattr(h, "items") else {}


def _mime(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


# ------------------------------------------------------------------ state (conditional requests)


def _read_state(vault: Path) -> dict:
    p = vault / STATE_FILE
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}  # an unreadable state file only costs an unconditional request


def _write_state(vault: Path, state: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=vault, prefix=".state-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, vault / STATE_FILE)


# ------------------------------------------------------------------ the fetch


@dataclass
class FetchResult:
    symbol: str
    status: str
    sha256: str | None = None
    path: str | None = None
    detail: str = ""


def _store_stream(resp: Any, vault: Path) -> tuple[str, Path | None, str]:
    """Stream to a .tmp file with SHA-256 on the fly. Returns (sha256, final_path_or_None, status)."""
    h = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=vault, prefix=".fetch-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            first = True
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                if first:
                    first = False
                    if not chunk.startswith(_PDF_MAGIC):
                        return "", None, "REJECTED_NOT_PDF_CONTENT"
                size += len(chunk)
                if size > MAX_BYTES:
                    return "", None, "REJECTED_TOO_LARGE"
                h.update(chunk)
                f.write(chunk)
            if size == 0:
                return "", None, "REJECTED_EMPTY"
        sha = h.hexdigest()
        final = vault / f"{sha}.pdf"
        try:
            os.link(tmp, final)  # atomic and never overwrites an existing file
        except FileExistsError:
            return sha, final, "SKIPPED_DUPLICATE"
        except OSError:  # no hard links on this filesystem: check, then move
            if final.exists():
                return sha, final, "SKIPPED_DUPLICATE"
            os.replace(tmp, final)
            os.chmod(final, 0o600)
            return sha, final, "STORED"
        os.chmod(final, 0o600)
        return sha, final, "STORED"
    finally:
        if tmp.exists():
            tmp.unlink()


def fetch_source(
    source: Source,
    vault: Path,
    *,
    policy: HostPolicy,
    opener: Callable[..., Any] = default_opener,
    rng: random.Random | None = None,
    state: dict | None = None,
    owner_sources: list | None = None,
) -> FetchResult:
    """Fetch one permitted source into the vault. Never raises for a remote problem; returns a status."""
    if source.permission_status != "permitted" or not source.endpoint_url:
        return FetchResult(
            source.symbol, "SKIPPED_NOT_PERMITTED", detail="permission_status is not permitted"
        )
    if not owner_permits(source, owner_sources):
        return FetchResult(
            source.symbol,
            "SKIPPED_NOT_PERMITTED",
            detail="the owner's source registry does not permit this endpoint",
        )
    rng = rng or random.Random()  # noqa: S311 - retry jitter, not cryptography
    host = urllib.request.urlsplit(source.endpoint_url).netloc.lower()
    state = state if state is not None else _read_state(vault)
    prev = state.get(source.endpoint_url, {})
    headers = {
        "User-Agent": "psxni-source-fetcher/1 (owner-permitted; contact the owner)",
        "Accept": "application/pdf",
    }
    if prev.get("etag"):
        headers["If-None-Match"] = prev["etag"]
    if prev.get("last_modified"):
        headers["If-Modified-Since"] = prev["last_modified"]
    with policy.lock(host):  # one active connection per host
        for attempt in range(MAX_ATTEMPTS):
            policy.wait(host, source.min_request_interval_seconds)
            req = urllib.request.Request(source.endpoint_url, headers=headers, method="GET")  # noqa: S310
            resp = opener(req)
            code = _status(resp)
            resp_headers = _headers(resp)
            if code == 429:
                delay = backoff_delay(attempt, _retry_after(resp_headers), rng)
                _close(resp)
                if attempt == MAX_ATTEMPTS - 1:
                    return FetchResult(source.symbol, "RATE_LIMITED_GIVE_UP", detail=f"429 x{MAX_ATTEMPTS}")
                policy.pause(delay)
                continue
            if code == 304:
                _close(resp)
                return FetchResult(source.symbol, "NOT_MODIFIED")
            if code != 200:
                _close(resp)
                return FetchResult(source.symbol, "ERROR_HTTP", detail=f"status {code}")
            if _mime(resp_headers) != "application/pdf":
                _close(resp)  # HTML error pages and other types are discarded without being stored
                return FetchResult(
                    source.symbol, "REJECTED_NOT_PDF", detail=f"content-type {_mime(resp_headers)!r}"
                )
            try:
                sha, final, status = _store_stream(resp, vault)
            finally:
                _close(resp)
            if status.startswith("REJECTED"):
                return FetchResult(source.symbol, status)
            state[source.endpoint_url] = {
                "etag": resp_headers.get("etag"),
                "last_modified": resp_headers.get("last-modified"),
                "last_sha256": sha,
            }
            _write_state(vault, state)
            return FetchResult(source.symbol, status, sha256=sha, path=str(final) if final else None)
    return FetchResult(source.symbol, "RATE_LIMITED_GIVE_UP")


def _close(resp: Any) -> None:
    close = getattr(resp, "close", None)
    if callable(close):
        close()


# ------------------------------------------------------------------ dispatch to the diagnostic intake

_OVERALL = re.compile(r"Reconciliation:.*?overall (\w+)")


def dispatch(source: Source, pdf: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict:
    """Run the diagnostic intake (--text, never --archive) on a newly stored PDF and return the result."""
    if not source.intake:
        return {"reconciliation_status": "NOT_DISPATCHED", "reason": "no intake profile in the registry"}
    prof = source.intake
    cmd = [
        sys.executable,
        "-m",
        "scripts.financial_intake",
        "--file",
        str(pdf),
        "--symbol",
        source.symbol,
        "--period-end",
        prof["period_end"],
        "--columns",
        ",".join(prof["columns"]),
        "--unit-scale",
        str(prof.get("unit_scale", 1000)),
        "--consolidation",
        prof.get("consolidation", "unconsolidated"),
        "--currency",
        prof.get("currency", "PKR"),
        "--framework",
        source.expected_framework,
        "--text",
    ]
    if source.company_id is not None:
        cmd += ["--company-id", str(source.company_id)]
    if prof.get("page_map"):
        cmd += ["--page-map", str(prof["page_map"])]
    proc = runner(cmd, capture_output=True, text=True, timeout=1800, check=False)
    m = _OVERALL.search(proc.stdout or "")
    if proc.returncode != 0 or not m:
        return {"reconciliation_status": "INTAKE_FAILED", "exit_code": proc.returncode}
    return {"reconciliation_status": m.group(1)}


def append_log(vault: Path, entry: dict) -> None:
    p = vault / LOG_FILE
    entries = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    entries.append(entry)
    fd, tmp = tempfile.mkstemp(dir=vault, prefix=".log-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, p)


def run_once(
    sources: list[Source],
    vault: Path,
    *,
    policy: HostPolicy,
    opener: Callable[..., Any] = default_opener,
    rng: random.Random | None = None,
    runner: Callable[..., Any] = subprocess.run,
    only: str | None = None,
    owner_sources: list | None = None,
) -> list[dict]:
    """One pass over the permitted sources. Every stored document is dispatched and logged."""
    out: list[dict] = []
    state = _read_state(vault)
    if owner_sources is None and any(s.permission_status == "permitted" for s in sources):
        from engines import source_registry as owner

        owner_sources = owner.load(OWNER_REGISTRY_PATH)
    for s in sources:
        if only and s.symbol != only.upper():
            continue
        res = fetch_source(
            s, vault, policy=policy, opener=opener, rng=rng, state=state, owner_sources=owner_sources
        )
        row = {"symbol": s.symbol, "fetch_status": res.status, "detail": res.detail}
        if res.status == "STORED" and res.path:
            d = dispatch(s, Path(res.path), runner=runner)
            entry = {
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                "symbol": s.symbol,
                "sha256": res.sha256,
                "reconciliation_status": d["reconciliation_status"],
            }
            append_log(vault, entry)
            row.update(entry)
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Polite, permission-gated retrieval of filing PDFs into the vault."
    )
    ap.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    ap.add_argument("--once", action="store_true", help="one pass over the permitted sources, then exit")
    ap.add_argument("--symbol", default=None, help="restrict the pass to one symbol")
    args = ap.parse_args(argv)
    if not args.once:
        print("refusing to run: use --once (the external scheduler decides when to run)", file=sys.stderr)
        return 2
    try:
        sources = load_registry(args.registry)
        vault = di.vault_dir()
    except (RegistryError, di.IntakeError) as exc:
        print(json.dumps({"status": "refused", "detail": str(exc)}))
        return 2
    rows = run_once(sources, vault, policy=HostPolicy(), only=args.symbol)
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
