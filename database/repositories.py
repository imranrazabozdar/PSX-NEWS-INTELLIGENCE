"""Read/write functions for the data foundation. All writes are idempotent or append-only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from database.canonical import canonical_url, content_sha256, normalise_name, now_utc
from database.connection import Database, DatabaseError


# ---------------------------------------------------------------- sources & source items
def upsert_source(db: Database, src: dict[str, Any]) -> None:
    """Insert a source or update its descriptive fields. Never enables collection."""
    now = now_utc()
    db.execute(
        """INSERT INTO sources(source_id, name, source_type, domain, platform, owner, reliability_tier,
               access_method, access_status, terms_notes, update_cadence, enabled, notes,
               created_at_utc, updated_at_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET name=excluded.name, domain=excluded.domain,
               platform=excluded.platform, notes=excluded.notes, updated_at_utc=excluded.updated_at_utc""",
        (src["source_id"], src["name"], src["source_type"], src.get("domain"), src.get("platform"),
         src.get("owner"), src.get("reliability_tier", "unrated"),
         src.get("access_method", "pending_review"), src.get("access_status", "unverified"),
         src.get("terms_notes"), src.get("update_cadence"), src.get("notes"), now, now))


@dataclass(frozen=True)
class ItemResult:
    source_item_id: int
    outcome: str  # 'inserted' | 'unchanged' | 'new_version' | 'duplicate_content'


def record_source_item(db: Database, *, source_id: str, collected_at_utc: str,
                       url: str | None = None, external_id: str | None = None,
                       content: str | None = None, content_hash: str | None = None,
                       title: str | None = None, published_at_utc: str | None = None,
                       published_at_raw: str | None = None, published_tz_offset: str | None = None,
                       event_date: str | None = None, language: str | None = None,
                       excerpt: str | None = None, access_status: str = "public") -> ItemResult:
    """Store a source item with deduplication and version history.

    * Same canonical URL / external ID and same content hash -> 'unchanged' (no write).
    * Same URL / ID but different content -> a new row in source_item_versions; the original
      row is never overwritten.
    * New URL but content identical to an existing item from any source -> stored, and linked
      with duplicate_of_item_id so it isn't counted as independent corroboration.
    """
    if content_hash is None:
        if content is None:
            raise ValueError("content or content_hash is required")
        content_hash = content_sha256(content)
    curl = canonical_url(url) if url else None
    if curl is None and external_id is None:
        raise ValueError("url or external_id is required")
    existing = db.execute(
        "SELECT source_item_id, content_sha256 FROM source_items WHERE source_id = ? AND "
        "((? IS NOT NULL AND canonical_url = ?) OR (? IS NOT NULL AND external_id = ?))",
        (source_id, curl, curl, external_id, external_id))
    if existing:
        item_id = existing[0]["source_item_id"]
        versions = db.execute(
            "SELECT content_sha256 FROM source_item_versions WHERE source_item_id = ?", (item_id,))
        known = {existing[0]["content_sha256"]} | {v["content_sha256"] for v in versions}
        if content_hash in known:
            return ItemResult(item_id, "unchanged")
        db.execute(
            "INSERT INTO source_item_versions(source_item_id, version_no, content_sha256, "
            "collected_at_utc, permitted_excerpt) VALUES (?, (SELECT COALESCE(MAX(version_no),1)+1 "
            "FROM source_item_versions WHERE source_item_id = ?), ?, ?, ?)",
            (item_id, item_id, content_hash, collected_at_utc, excerpt))
        return ItemResult(item_id, "new_version")
    dup = db.execute("SELECT MIN(source_item_id) AS id FROM source_items WHERE content_sha256 = ?",
                     (content_hash,))
    dup_id = dup[0]["id"] if dup and dup[0]["id"] is not None else None
    rows = db.batch([
        ("""INSERT INTO source_items(source_id, canonical_url, external_id, title, language,
               published_at_utc, published_at_raw, published_tz_offset, event_date, collected_at_utc,
               content_sha256, permitted_excerpt, access_status, duplicate_of_item_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (source_id, curl, external_id, title, language, published_at_utc, published_at_raw,
          published_tz_offset, event_date, collected_at_utc, content_hash, excerpt, access_status,
          dup_id)),
        ("SELECT last_insert_rowid() AS id", ()),
    ])
    item_id = rows[1][0]["id"]
    db.execute("INSERT INTO source_item_versions(source_item_id, version_no, content_sha256, "
               "collected_at_utc, permitted_excerpt) VALUES (?, 1, ?, ?, ?)",
               (item_id, content_hash, collected_at_utc, excerpt))
    return ItemResult(item_id, "duplicate_content" if dup_id else "inserted")


# ---------------------------------------------------------------- companies
def company_by_ticker(db: Database, ticker: str, as_of: str | None = None) -> dict | None:
    """Resolve a PSX ticker to its company. With as_of (YYYY-MM-DD), resolve point-in-time."""
    if as_of is None:
        sql = ("SELECT c.* FROM company_identifiers i JOIN companies c USING(company_id) "
               "WHERE i.id_type='psx_ticker' AND i.value=? AND i.valid_to IS NULL")
        rows = db.execute(sql, (ticker.upper(),))
    else:
        sql = ("SELECT c.* FROM company_identifiers i JOIN companies c USING(company_id) "
               "WHERE i.id_type='psx_ticker' AND i.value=? "
               "AND (i.valid_from IS NULL OR i.valid_from <= ?) "
               "AND (i.valid_to IS NULL OR i.valid_to >= ?) ORDER BY i.valid_from DESC LIMIT 1")
        rows = db.execute(sql, (ticker.upper(), as_of, as_of))
    return rows[0] if rows else None


def resolve_alias(db: Database, text: str, *, listed_only: bool = True) -> list[dict]:
    """Find companies whose alias matches text exactly after normalisation."""
    sql = ("SELECT DISTINCT c.company_id, c.legal_name, a.alias_type, a.confidence "
           "FROM company_aliases a JOIN companies c USING(company_id) WHERE a.alias_normalized = ?"
           + (" AND c.listing_status = 'listed'" if listed_only else ""))
    return db.execute(sql, (normalise_name(text),))


# ---------------------------------------------------------------- events & evidence
_EVENT_FIELDS = ("event_type", "headline", "summary", "event_date", "event_date_precision",
                 "geography", "status_stage", "verification_state", "direction", "magnitude",
                 "novelty", "horizon", "confidence")


def create_event(db: Database, event: dict[str, Any], *, changed_by: str, reason: str = "created",
                 model_version: str | None = None, prompt_version: str | None = None) -> int:
    """Create an event together with its first revision (atomic)."""
    now = now_utc()
    fields = {k: event.get(k) for k in _EVENT_FIELDS if event.get(k) is not None}
    for required in ("event_type", "headline", "status_stage"):
        if required not in fields:
            raise ValueError(f"event field '{required}' is required")
    cols = list(fields) + ["first_seen_at_utc", "current_revision", "created_at_utc", "updated_at_utc"]
    vals = list(fields.values()) + [event.get("first_seen_at_utc", now), 1, now, now]
    snapshot = json.dumps(fields, sort_keys=True)
    rows = db.batch([
        (f"INSERT INTO events({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals),  # noqa: S608 - column names from _EVENT_FIELDS only
        ("SELECT last_insert_rowid() AS id", ()),
        ("""INSERT INTO event_revisions(event_id, revision_no, recorded_at_utc, status_stage,
               verification_state, headline, summary, snapshot_json, change_reason, changed_by,
               model_version, prompt_version)
            SELECT event_id, 1, ?, status_stage, verification_state, headline, summary, ?, ?, ?, ?, ?
            FROM events WHERE rowid = last_insert_rowid()""",
         (now, snapshot, reason, changed_by, model_version, prompt_version)),
    ])
    return rows[1][0]["id"]


def revise_event(db: Database, event_id: int, changes: dict[str, Any], *, reason: str,
                 changed_by: str, model_version: str | None = None,
                 prompt_version: str | None = None) -> int:
    """Record a new revision, then move the event to it. Earlier revisions stay untouched."""
    bad = set(changes) - set(_EVENT_FIELDS)
    if bad:
        raise ValueError(f"cannot change fields: {sorted(bad)}")
    cur = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    if not cur:
        raise DatabaseError(f"event {event_id} not found")
    current = cur[0]
    new = {k: current[k] for k in _EVENT_FIELDS if current[k] is not None} | changes
    rev = current["current_revision"] + 1
    now = now_utc()
    sets = ", ".join(f"{k} = ?" for k in changes)
    db.batch([
        ("""INSERT INTO event_revisions(event_id, revision_no, recorded_at_utc, status_stage,
               verification_state, headline, summary, snapshot_json, change_reason, changed_by,
               model_version, prompt_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
         (event_id, rev, now, new["status_stage"], new.get("verification_state", "unverified"),
          new["headline"], new.get("summary"), json.dumps(new, sort_keys=True), reason, changed_by,
          model_version, prompt_version)),
        (f"UPDATE events SET {sets}, current_revision = ?, updated_at_utc = ? WHERE event_id = ?",  # noqa: S608 - whitelisted columns
         [*changes.values(), rev, now, event_id]),
    ])
    return rev


def add_evidence(db: Database, *, event_id: int, source_item_id: int, claim: str,
                 claim_type: str, relation: str, excerpt: str, recorded_by: str,
                 is_independent: bool | None = None) -> int:
    """Attach evidence for one claim. Re-adding the same claim from the same item is a no-op."""
    db.execute(
        """INSERT INTO event_evidence(event_id, source_item_id, claim, claim_type, relation, excerpt,
               is_independent, recorded_at_utc, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(event_id, source_item_id, claim) DO NOTHING""",
        (event_id, source_item_id, claim, claim_type, relation, excerpt,
         None if is_independent is None else int(is_independent), now_utc(), recorded_by))
    return db.execute("SELECT evidence_id FROM event_evidence WHERE event_id=? AND source_item_id=? "
                      "AND claim=?", (event_id, source_item_id, claim))[0]["evidence_id"]


def event_history(db: Database, event_id: int) -> list[dict]:
    return db.execute("SELECT * FROM event_revisions WHERE event_id = ? ORDER BY revision_no",
                      (event_id,))


def event_with_evidence(db: Database, event_id: int) -> dict | None:
    ev = db.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    if not ev:
        return None
    evidence = db.execute(
        """SELECT e.*, s.canonical_url, s.external_id, s.published_at_utc, s.collected_at_utc,
                  s.source_id, src.name AS source_name, src.reliability_tier
           FROM event_evidence e JOIN source_items s USING(source_item_id)
           JOIN sources src ON src.source_id = s.source_id
           WHERE e.event_id = ? ORDER BY e.evidence_id""", (event_id,))
    return ev[0] | {"evidence": evidence}
