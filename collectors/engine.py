"""Collection pipeline (ADR-0005):

registry -> policy checks -> conditional fetch -> parse -> canonicalise -> hash ->
dedupe / version -> persist (with provenance) -> run audit -> source health.

Safety rules enforced here:
* Only sources whose lifecycle_status is ACTIVE are collected for real.
* A dry run (fetch and parse, never write) is allowed only for sources under review that have no
  known prohibition: lifecycle REVIEWED, APPROVED, IMPLEMENTED or TESTED, and access/terms/licensing
  not restricted, blocked, licence-required or prohibiting automation. NOT REVIEWED, RESTRICTED,
  BLOCKED, LICENCE REQUIRED and DISABLED sources are refused before any network request.
  ``authorise`` is the single gate used by every entry point; robots.txt still applies on top.
* PSXNI_KILL_SWITCH stops collection before any network or database work.
* Database usage stays within the per-run budgets of database.connection.
* Retention follows the source's retention_mode: metadata only (title, link, timestamps,
  hash) unless the terms permit an excerpt.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from collectors.http import FetchError, HttpClient, RobotsDisallowed
from collectors.parsers import Entry, ParseError, parse_feed, parse_json_api, parse_timestamp
from database.canonical import canonical_url, content_sha256, now_utc
from database.connection import Database, DatabaseBudgetError
from database.repositories import record_source_item

EXCERPT_CHARS = 300
ADAPTERS = ("rss", "atom", "json_api")


class CollectionRefused(RuntimeError):
    """Policy (kill switch, lifecycle status, missing configuration) stopped the run."""


@dataclass
class RunResult:
    source_id: str
    status: str = "running"  # succeeded | failed | partial | dry_run | refused
    dry_run: bool = False
    fetched: int = 0
    new: int = 0
    unchanged: int = 0
    duplicates: int = 0
    new_versions: int = 0
    failed: int = 0
    not_modified: bool = False
    http_status: int | None = None
    http_requests: int = 0
    errors: list[str] = field(default_factory=list)
    run_id: int | None = None
    entries: list[dict] = field(default_factory=list)  # dry-run preview only


DRY_RUN_LIFECYCLES = frozenset({"REVIEWED", "APPROVED", "IMPLEMENTED", "TESTED", "ACTIVE"})
PROHIBITED_ACCESS = frozenset({"restricted", "blocked", "licence_required"})
PROHIBITED_TERMS = frozenset({"prohibits_automation", "licence_required", "restricted"})
PROHIBITED_LICENSING = frozenset({"licence_required", "paid_api", "permission_required"})


# Sources collected only by their own consent-bound job (rate limit, trading hours, robots, backoff).
# The generic engine must never fetch them, not even as a dry run.
CONSENT_GOVERNED = frozenset({"investify_announcements"})  # collectors/investify_job.py


def authorise(source: dict, *, dry_run: bool) -> None:
    """Raise CollectionRefused unless this source may be fetched in this mode. No network use."""
    sid, life = source["source_id"], source.get("lifecycle_status")
    if sid in CONSENT_GOVERNED:
        raise CollectionRefused(f"source '{sid}' is collected only by its consent-bound job "
                                "(collectors.investify_job)")
    if not dry_run:
        if life != "ACTIVE":
            raise CollectionRefused(f"source '{sid}' is {life}; only ACTIVE sources are collected "
                                    "(use dry_run to test a reviewed source without writing)")
        return
    if life not in DRY_RUN_LIFECYCLES:
        raise CollectionRefused(f"source '{sid}' is {life}; dry runs are not permitted for it")
    reasons = []
    if source.get("access_status") in PROHIBITED_ACCESS:
        reasons.append(f"access_status={source['access_status']}")
    if source.get("terms_status") in PROHIBITED_TERMS:
        reasons.append(f"terms_status={source['terms_status']}")
    if source.get("licensing_status") in PROHIBITED_LICENSING:
        reasons.append(f"licensing_status={source['licensing_status']}")
    if source.get("access_method") == "not_permitted":
        reasons.append("access_method=not_permitted")
    if reasons:
        raise CollectionRefused(f"source '{sid}' may not be fetched, even as a dry run: {', '.join(reasons)}")


def _kill_switch_on() -> bool:
    return os.environ.get("PSXNI_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}


def load_source(db: Database, source_id: str) -> dict:
    rows = db.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,))
    if not rows:
        raise CollectionRefused(f"unknown source '{source_id}'")
    return rows[0]


def _representation(entry: Entry, retention: str) -> tuple[str, str | None]:
    """What is hashed and what may be stored, according to the retention mode."""
    summary = entry.summary or ""
    basis = "\n".join([entry.title or "", entry.url or "", entry.published_raw or "", summary])
    excerpt = None
    if retention in ("excerpt", "full_text_permitted") and summary:
        excerpt = summary[:EXCERPT_CHARS]
    return basis, excerpt


def parse_payload(source: dict, body: bytes) -> list[Entry]:
    adapter = source.get("adapter")
    if adapter in ("rss", "atom"):
        _, entries = parse_feed(body)
        return entries
    if adapter == "json_api":
        cfg = json.loads(source.get("review_notes") or "{}").get("json_api", {})
        return parse_json_api(body, items_key=cfg.get("items_key", ""), fields=cfg.get("fields", {}))
    raise CollectionRefused(f"source '{source['source_id']}' has no implemented adapter ({adapter})")


def _start_run(db: Database, source_id: str, job: str) -> int:
    rows = db.batch([
        ("INSERT INTO collector_runs(job, source_id, started_at_utc, status) VALUES (?, ?, ?, 'running')",
         (job, source_id, now_utc())),
        ("SELECT last_insert_rowid() AS id", ()),
    ])
    return rows[1][0]["id"]


def _finish(db: Database, res: RunResult, started: datetime) -> None:
    dur = int((datetime.now(UTC) - started).total_seconds() * 1000)
    now = now_utc()
    stmts = [(
        """UPDATE collector_runs SET finished_at_utc = ?, status = ?, items_fetched = ?,
               items_accepted = ?, items_rejected = ?, items_duplicate = ?, items_new_version = ?,
               items_failed = ?, http_requests = ?, http_status = ?, duration_ms = ?, not_modified = ?,
               errors = ? WHERE run_id = ?""",
        (now, res.status, res.fetched, res.new, res.unchanged, res.duplicates, res.new_versions,
         res.failed, res.http_requests, res.http_status, dur, int(res.not_modified),
         "\n".join(res.errors)[:2000] or None, res.run_id))]
    if res.status == "failed":
        stmts.append(("""UPDATE sources SET last_attempt_at_utc = ?, last_error = ?,
                             failure_count = failure_count + 1,
                             consecutive_failures = consecutive_failures + 1 WHERE source_id = ?""",
                      (now, (res.errors[-1] if res.errors else "failed")[:500], res.source_id)))
    else:
        stmts.append(("""UPDATE sources SET last_attempt_at_utc = ?, last_success_at_utc = ?,
                             last_error = CASE WHEN ? = 'partial' THEN ? ELSE NULL END,
                             consecutive_failures = 0 WHERE source_id = ?""",
                      (now, now, res.status, (res.errors[-1] if res.errors else None), res.source_id)))
    db.batch(stmts)


def collect(db: Database, source_id: str, *, client: HttpClient | None = None, dry_run: bool = False,
            max_items: int = 100, since_utc: str | None = None, until_utc: str | None = None,
            job: str = "manual") -> RunResult:
    """Collect one source. Returns a RunResult; never raises for ordinary source failures."""
    if _kill_switch_on():
        raise CollectionRefused("PSXNI_KILL_SWITCH is on")
    source = load_source(db, source_id)
    authorise(source, dry_run=dry_run)
    if source.get("adapter") not in ADAPTERS or not source.get("feed_url"):
        raise CollectionRefused(f"source '{source_id}' has no implemented adapter or endpoint")

    client = client or HttpClient()
    res = RunResult(source_id, dry_run=dry_run)
    started = datetime.now(UTC)
    checkpoint = None if dry_run else (db.execute(
        "SELECT * FROM collector_checkpoints WHERE source_id = ?", (source_id,)) or [None])[0]
    if not dry_run:
        res.run_id = _start_run(db, source_id, job)

    try:
        resp = client.get(source["feed_url"],
                          etag=checkpoint["etag"] if checkpoint else None,
                          last_modified=checkpoint["last_modified"] if checkpoint else None)
        res.http_status = resp.status
        res.http_requests = client.requests_made
        if resp.not_modified:
            res.not_modified = True
            res.status = "dry_run" if dry_run else "succeeded"
            if not dry_run:
                _finish(db, res, started)
            return res
        entries = parse_payload(source, resp.body)
    except (FetchError, RobotsDisallowed, ParseError, CollectionRefused) as exc:
        res.http_requests = client.requests_made
        res.http_status = getattr(exc, "status", None)
        res.errors.append(f"{type(exc).__name__}: {exc}")
        res.status = "failed"
        if not dry_run:
            _finish(db, res, started)
        return res

    collected_at = now_utc()
    retention = source.get("retention_mode") or "metadata_only"
    newest = None
    for entry in entries[:max_items]:
        res.fetched += 1
        try:
            ts = parse_timestamp(entry.published_raw)
            if ts.utc and ((since_utc and ts.utc < since_utc) or (until_utc and ts.utc > until_utc)):
                continue
            if not entry.url and not entry.external_id:
                raise ParseError("entry has neither a link nor an identifier")
            basis, excerpt = _representation(entry, retention)
            curl = canonical_url(entry.url) if entry.url else None
            if dry_run:
                res.entries.append({"title": entry.title, "canonical_url": curl,
                                    "published_at_utc": ts.utc, "publication_time_status": ts.status,
                                    "content_sha256": content_sha256(basis)})
                continue
            out = record_source_item(
                db, source_id=source_id, collected_at_utc=collected_at, url=entry.url,
                external_id=entry.external_id, content=basis, title=entry.title,
                published_at_utc=ts.utc, published_at_raw=ts.raw, published_tz_offset=ts.offset,
                excerpt=excerpt,
                provenance={"original_url": entry.url, "retrieval_method": source["adapter"],
                            "collection_run_id": res.run_id, "http_status": resp.status,
                            "document_type": entry.document_type, "publication_time_status": ts.status,
                            "source_metadata_json": json.dumps(entry.metadata) if entry.metadata else None})
            if out.outcome == "inserted":
                res.new += 1
            elif out.outcome == "unchanged":
                res.unchanged += 1
            elif out.outcome == "new_version":
                res.new_versions += 1
            else:
                res.duplicates += 1
            if ts.utc and (newest is None or ts.utc > newest):
                newest = ts.utc
        except DatabaseBudgetError:
            res.errors.append("database budget reached; run stopped early")
            res.failed += 1
            break
        except (ParseError, ValueError) as exc:
            res.failed += 1
            res.errors.append(f"item {res.fetched}: {exc}")

    if dry_run:
        res.status = "dry_run"
        return res
    res.status = "partial" if res.failed else "succeeded"
    db.batch([
        ("""INSERT INTO collector_checkpoints(source_id, endpoint_url, etag, last_modified,
               last_seen_published_utc, updated_at_utc) VALUES (?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET endpoint_url = excluded.endpoint_url,
               etag = excluded.etag, last_modified = excluded.last_modified,
               last_seen_published_utc = COALESCE(excluded.last_seen_published_utc,
                                                  collector_checkpoints.last_seen_published_utc),
               updated_at_utc = excluded.updated_at_utc""",
         (source_id, source["feed_url"], resp.headers.get("etag"), resp.headers.get("last-modified"),
          newest, now_utc())),
        ("UPDATE sources SET last_content_at_utc = COALESCE(?, last_content_at_utc) WHERE source_id = ?",
         (newest, source_id)),
    ])
    _finish(db, res, started)
    return res


def collect_document(db: Database, source_id: str, url: str, *, client: HttpClient | None = None,
                     dry_run: bool = False, title: str | None = None,
                     published_raw: str | None = None) -> RunResult:
    """Record one official downloadable document (e.g. a PDF notification) by URL.

    Only metadata is stored: URL, size, content type, SHA-256 of the bytes, server Last-Modified
    and the source's own publication date if supplied. The document body is never stored in the
    database. A changed document at the same URL becomes a new version.
    """
    from collectors.parsers import document_info

    if _kill_switch_on():
        raise CollectionRefused("PSXNI_KILL_SWITCH is on")
    source = load_source(db, source_id)
    authorise(source, dry_run=dry_run)
    client = client or HttpClient()
    res = RunResult(source_id, dry_run=dry_run)
    started = datetime.now(UTC)
    if not dry_run:
        res.run_id = _start_run(db, source_id, "document")
    try:
        resp = client.get(url)
        res.http_status, res.http_requests = resp.status, client.requests_made
        info = document_info(url, resp.headers, resp.body)
    except (FetchError, ParseError) as exc:
        res.http_requests = client.requests_made
        res.http_status = getattr(exc, "status", None)
        res.errors.append(f"{type(exc).__name__}: {exc}")
        res.status = "failed"
        if not dry_run:
            _finish(db, res, started)
        return res
    res.fetched = 1
    ts = parse_timestamp(published_raw)
    meta = {"content_type": info.content_type, "size_bytes": info.size_bytes, "is_pdf": info.is_pdf,
            "pdf_version": info.pdf_version, "server_last_modified": info.last_modified_raw}
    if dry_run:
        res.entries.append({"url": canonical_url(url), "sha256": info.sha256, **meta})
        res.status = "dry_run"
        return res
    out = record_source_item(
        db, source_id=source_id, collected_at_utc=now_utc(), url=url, content_hash=info.sha256,
        title=title, published_at_utc=ts.utc, published_at_raw=ts.raw, published_tz_offset=ts.offset,
        provenance={"original_url": url, "retrieval_method": "pdf" if info.is_pdf else "html",
                    "collection_run_id": res.run_id, "http_status": resp.status,
                    "document_type": "pdf" if info.is_pdf else "document",
                    "publication_time_status": ts.status, "source_metadata_json": json.dumps(meta)})
    setattr(res, {"inserted": "new", "unchanged": "unchanged", "new_version": "new_versions"}
            .get(out.outcome, "duplicates"), 1)
    res.status = "succeeded"
    _finish(db, res, started)
    return res


def due_sources(db: Database, now: str | None = None) -> list[str]:
    """ACTIVE sources whose collection interval has elapsed (scheduler)."""
    now = now or now_utc()
    rows = db.execute(
        """SELECT source_id FROM sources WHERE lifecycle_status = 'ACTIVE' AND enabled = 1
           AND adapter IN ('rss','atom','json_api') AND feed_url IS NOT NULL
           AND (last_attempt_at_utc IS NULL OR
                strftime('%s', ?) - strftime('%s', last_attempt_at_utc)
                  >= 60 * COALESCE(collection_frequency_minutes, 360))
           ORDER BY COALESCE(priority, 5), source_id""", (now,))
    return [r["source_id"] for r in rows]


def fetch_pages(client: HttpClient, first_url: str, *, source: dict, dry_run: bool, next_url,
                max_pages: int = 5) -> list:
    """Fetch a paginated listing (archive pages or API pages).

    `next_url(response, page_no)` returns the next page URL or None. Stops at max_pages, on an
    empty page or on an error, and returns the responses fetched so far, so a later page failing
    still leaves the earlier pages usable (partial collection).
    """
    authorise(source, dry_run=dry_run)
    pages, url, n = [], first_url, 1
    while url and n <= max_pages:
        try:
            resp = client.get(url)
        except FetchError:
            break
        if resp.status != 200 or not resp.body.strip():
            break
        pages.append(resp)
        url, n = next_url(resp, n), n + 1
    return pages
