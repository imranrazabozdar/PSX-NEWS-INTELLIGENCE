"""The council's own ledger: daily and per-execution run caps, the pending queue, and every LLM call.

A small JSON file (path from PSXNI_COUNCIL_LEDGER). It is NOT the production database: during the dry run
the council
may not write to psx-library, so its budget, queue and call log live here. In Actions the file is carried
from one
execution to the next by the workflow's cache.

Concurrency: every change runs inside `transaction()`, which takes an exclusive file lock, re-reads the
file, applies
the change and replaces the file atomically. Two executions (or threads) can therefore never both take
the last slot.

Rules enforced here:
  * at most CAP_PER_DAY council runs per Pakistan-local day and CAP_PER_EXECUTION per collector execution;
  * one assessment per (event id, version): a repeat is refused, a changed version is a new item;
  * an important event that exceeds a cap stays in the queue (priority first, oldest first); nothing is
  discarded.
    A run that fails is retried on a later execution; after MAX_ATTEMPTS it is marked needs_review and kept.
  * every individual LLM call is recorded with its vendor, account, model, outcome and tokens, and the
  per-vendor,
    per-account quotas are computed from those records, separately from the council-run caps above.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CAP_PER_DAY = 6
CAP_PER_EXECUTION = 2
MAX_ATTEMPTS = 3
STALE_RESERVATION_HOURS = 3
KEEP_CALLS = 4000
KEEP_RUNS = 2000
KEEP_EXECUTIONS = 1000
SCHEMA = 1


COVER_HOURS = 36  # a story already assessed this recently is not assessed again (the queue item is kept)


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "days": {},  # pkt day -> {"runs": n}
        "executions": {},  # exec id -> {"runs": n}
        "events": {},  # event id -> {"anchor": [...], "urls": [...], "title": "..."}
        "queue": [],  # items waiting or reserved
        "assessed": {},  # "event:version" -> {"at": ..., "outcome": ...}
        "calls": [],
        "runs": [],
        "execution_log": [],
        "cursor": None,
        "scans": {},  # scan name -> last run time (UTC stamp), for scans that need not run every execution
    }


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    # --- storage ------------------------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # fail closed: a damaged ledger must not reset the caps
            raise LedgerError(f"ledger {self.path} is unreadable ({exc}); refusing to continue") from exc
        base = _empty()
        base.update(data)
        return base

    def _save(self, data: dict[str, Any]) -> None:
        data["calls"] = data["calls"][-KEEP_CALLS:]
        data["runs"] = data["runs"][-KEEP_RUNS:]
        data["execution_log"] = data["execution_log"][-KEEP_EXECUTIONS:]
        if len(data["executions"]) > KEEP_EXECUTIONS:
            for k in list(data["executions"])[: len(data["executions"]) - KEEP_EXECUTIONS]:
                del data["executions"][k]
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        with open(self.lock_path, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._load()
                yield data
                self._save(data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def snapshot(self) -> dict[str, Any]:
        with open(self.lock_path, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            try:
                return self._load()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    # --- events and the queue -----------------------------------------------------------------------------
    def known_events(self) -> list[dict[str, Any]]:
        return [{"event_id": k, **v} for k, v in self.snapshot()["events"].items()]

    def register_events(self, events: list[Any]) -> None:
        """Remember each headline event's id, anchor words and links so its id is stable as the window
        slides."""
        with self.transaction() as d:
            for e in events:
                if e.kind != "headline":
                    continue
                rec = d["events"].setdefault(
                    e.event_id, {"anchor": sorted(e.anchor), "urls": [], "title": e.title}
                )
                rec["urls"] = sorted(set(rec["urls"]) | {m.url for m in e.members})

    def enqueue(self, e: Any, priority: float, now: datetime) -> str:
        """Add a flagged event to the queue unless this exact version is already assessed or already waiting.
        Returns 'queued', 'already_assessed' or 'already_queued'. Never drops an event."""
        with self.transaction() as d:
            key = e.key
            if key in d["assessed"]:
                return "already_assessed"
            for item in d["queue"]:
                if item["key"] == key:
                    item["priority"] = max(item["priority"], priority)
                    return "already_queued"
            d["queue"].append(
                {
                    "key": key,
                    "event_id": e.event_id,
                    "version": e.version,
                    "kind": e.kind,
                    "title": e.title,
                    "priority": priority,
                    "rules": sorted({h.rule for h in e.hits}),
                    "flagged_at": stamp(now),
                    "attempts": 0,
                    "state": "pending",
                    "payload": event_payload(e),
                }
            )
            return "queued"

    def _covered(self, item: dict[str, Any], seen: list[tuple[frozenset[str], set[str]]]) -> bool:
        """True when a similar story (same figure and subject, same companies) was assessed lately or is
        already being taken in this batch. The item is kept, marked 'covered', never discarded."""
        from engines import news_importance as ni  # lazy: the ledger itself needs nothing from the rules

        words = ni.content_words(item.get("title", ""))
        cos = set(item.get("payload", {}).get("companies", []))
        for other_words, other_cos in seen:
            if cos and other_cos and not (cos & other_cos):
                continue  # "HBL profit rises 20%" and "MCB profit rises 20%" are two stories
            if ni.similar(words, other_words):
                return True
        return False

    def reserve_batch(
        self,
        exec_id: str,
        now: datetime,
        day: str,
        *,
        cap_day: int = CAP_PER_DAY,
        cap_exec: int = CAP_PER_EXECUTION,
        counted: bool = True,
    ) -> list[dict[str, Any]]:
        """Take up to the caps' worth of queued events, highest priority first. Atomic: concurrent
        callers share
        one count. With counted=False (the 10-headline test) nothing is charged to the daily or execution
        caps."""
        taken: list[dict[str, Any]] = []
        with self.transaction() as d:
            cutoff = stamp(now - timedelta(hours=STALE_RESERVATION_HOURS))
            for item in d["queue"]:  # a reservation whose execution died is released, not lost
                if item["state"] == "reserved" and item.get("reserved_at", "") < cutoff:
                    item["state"] = "pending"
            runs_today = d["days"].setdefault(day, {"runs": 0})
            runs_here = d["executions"].setdefault(exec_id, {"runs": 0, "started_at": stamp(now)})
            order = sorted(
                (i for i in d["queue"] if i["state"] == "pending"),
                key=lambda i: (-i["priority"], i["flagged_at"], i["key"]),
            )
            from engines import news_importance as ni

            recent = stamp(now - timedelta(hours=COVER_HOURS))
            seen = [
                (ni.content_words(i.get("title", "")), set(i.get("payload", {}).get("companies", [])))
                for i in d["queue"]
                if i["state"] == "done" and d["assessed"].get(i["key"], {}).get("at", "") >= recent
            ]
            for item in order:
                if counted and (runs_today["runs"] >= cap_day or runs_here["runs"] >= cap_exec):
                    break
                if item["key"] in d["assessed"]:
                    item["state"] = "already_assessed"
                    continue
                if counted and self._covered(item, seen):
                    item["state"] = "covered"
                    item["note"] = f"a similar story was assessed within {COVER_HOURS} hours"
                    continue
                taken_cos = set(item.get("payload", {}).get("companies", []))
                seen.append((ni.content_words(item.get("title", "")), taken_cos))
                item["state"] = "reserved"
                item["reserved_at"] = stamp(now)
                item["exec_id"] = exec_id
                item["attempts"] += 1
                if counted:
                    runs_today["runs"] += 1
                    runs_here["runs"] += 1
                taken.append(dict(item))
        return taken

    def finish(self, key: str, outcome: str, now: datetime, ok: bool) -> None:
        """Mark a reserved item done (assessed) or failed. A failure goes back to pending for a later
        execution,
        and to needs_review after MAX_ATTEMPTS; it is kept either way."""
        with self.transaction() as d:
            for item in d["queue"]:
                if item["key"] != key:
                    continue
                if ok:
                    item["state"] = "done"
                    d["assessed"][key] = {"at": stamp(now), "outcome": outcome}
                else:
                    item["state"] = "needs_review" if item["attempts"] >= MAX_ATTEMPTS else "pending"
                    item["last_error"] = outcome[:300]
                return

    def pending(self) -> list[dict[str, Any]]:
        return [i for i in self.snapshot()["queue"] if i["state"] in ("pending", "reserved", "needs_review")]

    # --- counters -----------------------------------------------------------------------------------------
    def runs_on(self, day: str) -> int:
        return int(self.snapshot()["days"].get(day, {"runs": 0})["runs"])

    def scan_due(self, name: str, now: datetime, hours: float) -> bool:
        """True when the named scan has not run in the last `hours` hours (or never)."""
        last = self.snapshot().get("scans", {}).get(name)
        if not last:
            return True
        return now - datetime.fromisoformat(last.replace("Z", "+00:00")) >= timedelta(hours=hours)

    def mark_scan(self, name: str, now: datetime) -> None:
        with self.transaction() as d:
            d.setdefault("scans", {})[name] = stamp(now)

    def cursor(self) -> str | None:
        return self.snapshot()["cursor"]

    def set_cursor(self, value: str) -> None:
        with self.transaction() as d:
            d["cursor"] = value

    def log_execution(self, entry: dict[str, Any]) -> None:
        with self.transaction() as d:
            d["execution_log"].append(entry)

    def log_run(self, entry: dict[str, Any]) -> None:
        with self.transaction() as d:
            d["runs"].append(entry)

    # --- individual LLM calls -----------------------------------------------------------------------------
    def record_call(self, entry: dict[str, Any]) -> None:
        with self.transaction() as d:
            d["calls"].append(entry)

    def calls_since(self, vendor: str, account: int, since: datetime, *, counting_only: bool = True) -> int:
        """Calls this vendor account has made since `since`. Not-connected attempts made no request and
        are not
        counted against a quota."""
        cutoff = stamp(since)
        n = 0
        for c in self.snapshot()["calls"]:
            if c["vendor"] == vendor and c["account"] == account and c["ts"] >= cutoff:
                if counting_only and c["outcome"] == "not_connected":
                    continue
                n += 1
        return n


class LedgerError(RuntimeError):
    """The ledger cannot be trusted; the council must not run."""


def event_payload(e: Any) -> dict[str, Any]:
    """Everything needed to run an event later without recomputing it (stored in the queue)."""
    return {
        "title": e.title,
        "kind": e.kind,
        "companies": list(e.companies),
        "sectors": list(e.sectors),
        "macro": list(e.macro),
        "transmission": list(getattr(e, "transmission", [])),  # candidate sectors, not conclusions
        "day": e.day,
        "hits": [{"rule": h.rule, "detail": h.detail, "entities": list(h.entities)} for h in e.hits],
        "members": [
            {
                "source": m.source,
                "url": m.url,
                "title": m.title,
                "published_at": m.published_at,
                "snippet": m.snippet,
            }
            for m in e.members
        ],
    }
