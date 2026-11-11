"""Investor-relations report fetcher: company annual and quarterly report PDFs into the document vault.

Scope and rules (hard):
* Companies' OWN public investor-relations pages only. The gated PSX document store is never used here.
* Honest, stable identity: one User-Agent that names the project and a contact URL. Never a browser disguise,
  never rotated.
* robots.txt is obeyed for every host the fetcher touches.
* A per-host minimum interval between requests (polite rate limit). Single-flight: one request in flight
  per host.
* HTTP 403, 429 and 503 stop that host for the run (429 and 503 honour Retry-After). No retry storm, and no
  bypass of any WAF, challenge, paywall or login.
* Raw PDFs go to the document vault (PSXNI_DOCUMENT_VAULT, outside the repository). They are never
  committed to
  Git and never written to any database. Only manifest metadata is recorded, in the vault.

Pipeline per company: fetch the IR reports page (one request); extract PDF links; classify each by report
type and
period from its link text and filename; keep only target types inside the scope window; for each new link,
fetch
the PDF (one request), verify it is a PDF, hash it, and store it under vault/<SYMBOL>/<type>_<period>.pdf.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from engines.document_intake import vault_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "config" / "ir_registry.json"
USER_AGENT = (
    "psx-news-intelligence/0.3 (+https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE; "
    "contact: https://github.com/imranrazabozdar/PSX-NEWS-INTELLIGENCE/issues; "
    "public investor-relations report fetcher; one request per URL)"
)
ROBOTS_TOKEN = "psx-news-intelligence"  # noqa: S105 - a robots.txt user-agent token, not a secret
TARGET_TYPES = ("annual_report", "half_year", "quarterly", "financial_statements")
STATUSES = ("live", "todo_unverified", "todo_js_rendered", "blocked_by_site", "todo_unreachable")
DEFAULT_MIN_INTERVAL_S = 10.0
DEFAULT_BACKOFF_S = 1800.0
MAX_BACKOFF_S = 3600.0
MAX_PDF_BYTES = 60_000_000
MAX_PAGE_BYTES = 8_000_000
DEFAULT_EXCLUDE = (
    r"summary|notice|corrigendum|proxy|form\s*34|agm|minutes|presentation|briefing|brochure|"
    r"policy|code\s+of|sustainability|esg"
)


class HostUnavailable(RuntimeError):
    """The host has asked us to stop (429, 503, 403, a network error or an open breaker). Not retried."""


class ResourceMissing(RuntimeError):
    """One URL is not available (for example HTTP 404). Only that URL is skipped; the host is not stopped."""


class RobotsDisallowed(RuntimeError):
    """robots.txt disallows the URL. It is not fetched."""


# ------------------------------------------------------------------ registry


@dataclass(frozen=True)
class IrEntry:
    symbol: str
    name: str
    url: str
    status: str
    allowed_hosts: tuple[str, ...] = ()  # the company's own domains; PDFs on other hosts are ignored
    report_types: tuple[str, ...] = TARGET_TYPES
    exclude: tuple[str, ...] = ()
    notes: str = ""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, IrEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, IrEntry] = {}
    for symbol, raw in data["companies"].items():
        status = raw["status"]
        if status not in STATUSES:
            raise ValueError(f"{symbol}: unknown status {status!r}")
        url = raw["ir_reports_url"]
        if not url.startswith("https://"):
            raise ValueError(f"{symbol}: the IR URL must be https")
        types = tuple(raw.get("report_types", TARGET_TYPES))
        if not set(types) <= set(TARGET_TYPES):
            raise ValueError(f"{symbol}: unknown report types {types}")
        hosts = tuple(raw.get("allowed_hosts", [urlsplit(url).netloc]))
        out[symbol] = IrEntry(
            symbol=symbol,
            name=raw.get("name", symbol),
            url=url,
            status=status,
            allowed_hosts=hosts,
            report_types=types,
            exclude=tuple(raw.get("exclude_patterns", [])),
            notes=raw.get("notes", ""),
        )
    return out


# ------------------------------------------------------------------ classification


@dataclass(frozen=True)
class Candidate:
    pdf_url: str
    text: str
    source_page_url: str
    report_type: str
    period: str
    year: int


_ORDINAL = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4}
_QUARTER_PATTERNS = (
    re.compile(r"\b(1st|2nd|3rd|4th|first|second|third|fourth)\s+quarter"),
    re.compile(r"\bq([1-4])\s*(?:fy)?\s*\d{2,4}\b"),
    re.compile(r"\b9\s*m\s*(?:fy)?\s*\d{2,4}\b"),  # nine months: the third quarter
    re.compile(r"\bnine\s*months?\b"),
)
_HALF_PATTERN = re.compile(
    r"\bhalf\s*-?\s*year|\bhalf\s*yearly|\b6\s*m\s*(?:fy)?\s*\d{2,4}\b|\bh1\s*(?:fy)?\s*\d{2,4}\b"
)
_ANNUAL_PATTERN = re.compile(r"\bannual\s*report|\bintegrated\s*annual")
_FS_PATTERN = re.compile(r"\bfinancial\s*statements\b")


def _year(text: str) -> int | None:
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"fy\s?(\d{2})(?!\d)", text)
    return 2000 + int(m.group(1)) if m else None


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("-", " ")).strip()


def classify(text: str) -> tuple[str, str, int] | None:
    """(report_type, period, year) for a link's text plus filename, or None when it cannot be stated
    reliably."""
    t = _normal(text)
    year = _year(t)
    if year is None:
        return None
    m = next((p.search(t) for p in _QUARTER_PATTERNS if p.search(t)), None)
    if m:
        if m.group(0).startswith(("9", "nine")):
            quarter = 3
        elif m.group(1).isdigit():
            quarter = int(m.group(1))
        else:
            quarter = _ORDINAL[m.group(1)]
        return "quarterly", f"Q{quarter}-{year}", year
    if _HALF_PATTERN.search(t):
        return "half_year", f"H1-{year}", year
    if _ANNUAL_PATTERN.search(t):
        return "annual_report", str(year), year
    if _FS_PATTERN.search(t):
        return "financial_statements", str(year), year
    return None


_HREF = re.compile(r'<a\b[^>]*?href="([^"#]+?\.pdf(?:\?[^"#]*)?)"[^>]*>(.*?)</a>', re.I | re.S)
_ABSOLUTE_PDF = re.compile(r"https://[^\s\"'<>\\]+?\.pdf", re.I)  # PDF URLs embedded in page data
_TAG = re.compile(r"<[^>]+>")


def _on_allowed_host(url: str, allowed: tuple[str, ...]) -> bool:
    host = urlsplit(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in allowed)


def extract_candidates(html: str, page_url: str, allowed_hosts: tuple[str, ...] = ()) -> list[Candidate]:
    """Classifiable PDF links on the page: anchors first, then PDF URLs embedded in the page's own data.

    Only hosts in `allowed_hosts` (the company's own domains) are kept. De-duplicated by resolved URL.
    Pure: no I/O."""
    found: list[tuple[str, str]] = []  # (url, link text)
    for href, inner in _HREF.findall(html):
        found.append((urljoin(page_url, href.strip()), re.sub(r"\s+", " ", _TAG.sub(" ", inner)).strip()))
    found += [(u, "") for u in _ABSOLUTE_PDF.findall(html)]
    seen: set[str] = set()
    out: list[Candidate] = []
    for raw_url, text in found:
        url = _canonical(raw_url)
        if url in seen or (allowed_hosts and not _on_allowed_host(url, allowed_hosts)):
            continue
        seen.add(url)
        filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        classified = classify(f"{text} {filename}")
        if classified is None:
            continue
        report_type, period, year = classified
        out.append(
            Candidate(
                pdf_url=url,
                text=text,
                source_page_url=page_url,
                report_type=report_type,
                period=period,
                year=year,
            )
        )
    return out


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ""))


def in_scope(c: Candidate, entry: IrEntry, *, today: datetime, years_back: int = 2) -> bool:
    """Target types only, inside the window, and not excluded by the registry's patterns.

    years_back=2 keeps the current year and the year before it (today 2026 keeps 2025 and 2026). A report
    labelled
    with the following year is kept too, as companies label quarters that way."""
    if c.report_type not in entry.report_types:
        return False
    if not (today.year - (years_back - 1) <= c.year <= today.year + 1):
        return False
    text = f"{c.text} {c.pdf_url}"
    return not any(re.search(p, text, re.I) for p in (*DEFAULT_EXCLUDE.split("|"), *entry.exclude))


def scoped(
    candidates: list[Candidate], entry: IrEntry, *, today: datetime, years_back: int = 2
) -> list[Candidate]:
    return [c for c in candidates if in_scope(c, entry, today=today, years_back=years_back)]


# ------------------------------------------------------------------ polite HTTP


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


def default_transport(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """One request, no retries. Error statuses are returned, not raised."""
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - https only, checked upstream
    try:
        with urllib.request.urlopen(req, timeout=25) as r:  # noqa: S310 - https only, checked upstream
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(MAX_PDF_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read(65536)


@dataclass
class PoliteClient:
    transport: Transport = default_transport
    user_agent: str = USER_AGENT
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    requests_made: int = 0
    _last: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, RobotFileParser] = field(default_factory=dict)
    _blocked_until: dict[str, float] = field(default_factory=dict)
    _blocks: dict[str, int] = field(default_factory=dict)
    _in_flight: set[str] = field(default_factory=set)

    def _raw(self, url: str) -> Response:
        host = urlsplit(url).netloc
        if host in self._in_flight:
            raise AssertionError("single-flight: a second request to the same host while one is in flight")
        self._in_flight.add(host)
        try:
            last = self._last.get(host)
            if last is not None:
                wait = self.min_interval_s - (self.clock() - last)
                if wait > 0:
                    self.sleep(wait)
            self._last[host] = self.clock()
            self.requests_made += 1
            try:
                status, headers, body = self.transport(
                    url,
                    {"User-Agent": self.user_agent, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5"},
                )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._block(host, DEFAULT_BACKOFF_S)
                raise HostUnavailable(f"network error ({type(exc).__name__}) for {host}") from exc
            return Response(status, headers, body)
        finally:
            self._in_flight.discard(host)

    def _block(self, host: str, seconds: float) -> None:
        self._blocks[host] = self._blocks.get(host, 0) + 1
        self._blocked_until[host] = self.clock() + min(seconds, MAX_BACKOFF_S)
        if self._blocks[host] >= 2:  # a second consecutive refusal: stop this host for the run
            self._blocked_until[host] = float("inf")

    def _robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            resp = self._raw(f"{parts.scheme}://{host}/robots.txt")
            rp = RobotFileParser()
            if resp.status == 200:
                rp.parse(resp.body.decode("utf-8", "replace").splitlines())
            elif resp.status in (404, 410):
                rp.parse([])  # no robots file: nothing is disallowed
            else:
                rp.parse(["User-agent: *", "Disallow: /"])  # cannot read it: be conservative
            self._robots[host] = rp
        return self._robots[host].can_fetch(ROBOTS_TOKEN, url)

    def get(self, url: str) -> Response:
        if urlsplit(url).scheme != "https":
            raise ValueError("only https URLs are fetched")
        host = urlsplit(url).netloc
        if self._blocked_until.get(host, 0) > self.clock():
            raise HostUnavailable(f"{host} is paused for this run after a refusal")
        if not self._robots_allows(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        resp = self._raw(url)
        if resp.status in (429, 503):
            self._block(host, _retry_after(resp.headers.get("retry-after")))
            raise HostUnavailable(f"HTTP {resp.status} from {host}: stopped, no retry")
        if resp.status == 403:
            self._block(host, DEFAULT_BACKOFF_S)
            raise HostUnavailable(f"HTTP 403 from {host}: stopped, no bypass attempted")
        if resp.status != 200:
            raise ResourceMissing(f"HTTP {resp.status} for {url}")
        self._blocks[host] = 0
        return resp


def _retry_after(value: str | None) -> float:
    if value and value.strip().isdigit():
        return float(value.strip())
    return DEFAULT_BACKOFF_S


# ------------------------------------------------------------------ vault and manifest


class Manifest:
    """Append-only JSON-lines manifest inside the vault. Records metadata only, never the PDF."""

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.path = vault / "manifest.jsonl"
        self.rows: list[dict[str, Any]] = []
        if self.path.exists():
            self.rows = [
                json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line
            ]

    def has_url(self, pdf_url: str) -> bool:
        return any(r["pdf_url"] == pdf_url for r in self.rows)

    def has_sha(self, sha: str) -> bool:
        return any(r["sha256"] == sha for r in self.rows)

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _store_pdf(vault: Path, symbol: str, report_type: str, period: str, data: bytes, sha: str) -> Path:
    folder = vault / symbol
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / f"{report_type}_{period}.pdf"
    if target.exists():  # the name is taken by a different document: keep both, distinguished by hash
        target = folder / f"{report_type}_{period}_{sha[:8]}.pdf"
    tmp = target.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


# ------------------------------------------------------------------ the run


@dataclass
class CompanyResult:
    symbol: str
    status: str
    reason: str = ""
    found: int = 0
    in_scope: int = 0
    stored: list[str] = field(default_factory=list)
    duplicates: int = 0
    rejected: list[str] = field(default_factory=list)


def run_company(
    entry: IrEntry,
    *,
    now: datetime,
    client: PoliteClient,
    vault: Path,
    manifest: Manifest,
    years_back: int = 2,
    max_downloads: int = 10,
) -> CompanyResult:
    if entry.status != "live":
        return CompanyResult(entry.symbol, "skipped", f"status {entry.status}: not fetched")
    try:
        page = client.get(entry.url)
    except (HostUnavailable, RobotsDisallowed, ResourceMissing) as exc:
        return CompanyResult(entry.symbol, "failed", str(exc))
    if len(page.body) > MAX_PAGE_BYTES:
        return CompanyResult(entry.symbol, "failed", "reports page larger than the limit")
    html = page.body.decode("utf-8", "replace")
    candidates = extract_candidates(html, entry.url, entry.allowed_hosts)
    wanted = scoped(candidates, entry, today=now, years_back=years_back)
    result = CompanyResult(entry.symbol, "ok", found=len(candidates), in_scope=len(wanted))
    for c in wanted[:max_downloads]:
        if manifest.has_url(c.pdf_url):
            result.duplicates += 1
            continue
        try:
            pdf = client.get(c.pdf_url)
        except (RobotsDisallowed, ResourceMissing) as exc:
            result.rejected.append(f"{c.pdf_url}: {exc}")  # this URL only: the others may still be fetched
            continue
        except HostUnavailable as exc:
            result.rejected.append(f"{c.pdf_url}: {exc}")
            break  # the host has asked us to stop: no further downloads this run
        if not pdf.body.startswith(b"%PDF-") or len(pdf.body) > MAX_PDF_BYTES:
            result.rejected.append(f"{c.pdf_url}: not a PDF, or larger than the limit")
            continue
        sha = hashlib.sha256(pdf.body).hexdigest()
        if manifest.has_sha(sha):
            result.duplicates += 1
            continue
        path = _store_pdf(vault, entry.symbol, c.report_type, c.period, pdf.body, sha)
        manifest.add(
            {
                "symbol": entry.symbol,
                "report_type": c.report_type,
                "period": c.period,
                "source_page_url": entry.url,
                "pdf_url": c.pdf_url,
                "sha256": sha,
                "retrieved_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bytes": len(pdf.body),
                "vault_path": str(path.relative_to(vault)),
            }
        )
        result.stored.append(str(path.relative_to(vault)))
    return result


def run_registry(
    registry: dict[str, IrEntry],
    *,
    now: datetime,
    client: PoliteClient,
    vault: Path,
    symbols: list[str] | None = None,
    years_back: int = 2,
    max_downloads: int = 10,
) -> list[CompanyResult]:
    manifest = Manifest(vault)
    chosen = [registry[s] for s in symbols] if symbols else list(registry.values())
    return [
        run_company(
            e,
            now=now,
            client=client,
            vault=vault,
            manifest=manifest,
            years_back=years_back,
            max_downloads=max_downloads,
        )
        for e in chosen
    ]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Fetch company IR report PDFs into the document vault")
    ap.add_argument("--symbol", action="append", help="limit to these symbols (repeatable)")
    ap.add_argument("--vault", help="vault directory (default: PSXNI_DOCUMENT_VAULT)")
    ap.add_argument("--max-downloads", type=int, default=10)
    args = ap.parse_args(argv)
    vault = vault_dir(args.vault)
    results = run_registry(
        load_registry(),
        now=datetime.now(UTC),
        client=PoliteClient(),
        vault=vault,
        symbols=args.symbol,
        max_downloads=args.max_downloads,
    )
    for r in results:
        print(json.dumps(r.__dict__, ensure_ascii=False, default=str))
    return 0 if all(r.status in ("ok", "skipped") for r in results) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
