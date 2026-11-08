"""X account watchlist: honest status and owner-authorised manual import of posts (master plan M1).

Access position (MASTER_DATA_SOURCE_REGISTER.md row 15): there is NO authorised automated access to X. The
official API needs a plan decision and no paid plan is authorised, so this module never fetches from X, never
scrapes and never imitates a browser. Accounts are kept as an explicit owner-supplied watchlist; posts enter
only through `import_posts`, from records the owner obtained lawfully and attests to.

Rules enforced here:
* Only handles already in the watchlist are accepted (no discovery, no silent additions).
* A post URL must be https://x.com/<that handle>/status/<digits>; its timestamp must be explicit.
* A post is a CLAIM by its account, never a verified fact: claim types are news_report,
  analyst_interpretation, personal_opinion, rumour, prediction or unclear. `official_statement` only when the
  importer marks it, and it is still unverified. Posts never write event evidence and never count as
  independent corroboration.
* Copies of an earlier post's text (same normalised text, other account or same account) are flagged as
  repost/syndicated, not as independent.
* Predictions are stored in media_predictions with result NULL for later evaluation.
* An account is reported as monitored only if its monitoring_status is 'active' (which the schema allows only
  for a verified identity); otherwise it is reported as not monitored, whatever was imported.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from database.seed_loader import load_json
from engines.event_classification import classify, entity_mentions, has, norm

SOURCE_ID = "x_platform"
JOB = "x_manual_import"
ACCESS_NOTE = (
    "no authorised automated access: the official X API needs an owner plan decision and no paid plan is "
    "authorised; posts arrive only by owner-attested manual import"
)
_URL = re.compile(r"^https://x\.com/([A-Za-z0-9_]{1,15})/status/([0-9]{1,25})$")
_TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
AVAILABILITY = ("available", "edited", "deleted", "inaccessible")
ANALYSIS = ("analysis", "thread", "chart", "valuation", "target price", "support", "resistance", "breakout",
            "bullish", "bearish", "accumulate", "undervalued", "overvalued")
POSITIVE = ("bullish", "upside", "rally", "breakout", "undervalued", "accumulate")
NEGATIVE = ("bearish", "downside", "crash", "sell-off", "selloff", "overvalued")
EXCERPT_MAX = 1000


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def owner_groups() -> dict[str, str]:
    wl = load_json("media_watchlist.json")
    return {a["handle"]: a["owner_group"] for a in wl["accounts"]
            if a["platform"] == "x" and a.get("owner_group")}


def status(db) -> list[dict]:
    """One row per X account; last retrieval and post counts come from stored imports only."""
    groups = owner_groups()
    rows = db.execute(
        "SELECT a.account_id, a.handle, a.supplied_url, a.display_name, a.category, a.identity_verification, "
        "a.monitoring_status, a.access_status, MAX(i.collected_at_utc) AS last_retrieved_at_utc, "
        "COUNT(i.media_item_id) AS posts FROM media_accounts a LEFT JOIN media_items i "
        "ON i.account_id = a.account_id WHERE a.platform = 'x' GROUP BY a.account_id ORDER BY a.account_id"
    )
    out = []
    for r in rows:
        monitored = r["monitoring_status"] == "active"
        out.append({
            **dict(r),
            "owner_group": groups.get(r["handle"]),
            "monitored": monitored,
            "access_method": "manual_import" if not monitored else "authorised",
            "authorisation": ACCESS_NOTE if r["access_status"] != "authorised" else "authorised",
            "state": "monitored" if monitored else ("pending_handle" if r["handle"] is None else
                                                     ("unverified_not_monitored")),
            "last_retrieval_method": "manual_import" if r["posts"] else None,
        })
    return out


def _text_hash(text: str) -> str:
    return hashlib.sha256(norm(text).strip().encode()).hexdigest()


def claim_type(text: str, *, official: bool = False) -> str:
    if official:
        return "official_statement"  # importer-marked; still unverified
    c = classify(text)
    if c.claim_nature in ("rumour", "prediction", "personal_opinion"):
        return c.claim_nature
    n = norm(text)
    if any(has(n, w) for w in ANALYSIS):
        return "analyst_interpretation"
    return "news_report" if c.primary_type != "other" else "unclear"


def _direction(text: str) -> str | None:
    n = norm(text)
    pos, neg = any(has(n, w) for w in POSITIVE), any(has(n, w) for w in NEGATIVE)
    return "mixed" if pos and neg else "positive" if pos else "negative" if neg else None


def _validate(rec: dict, accounts: dict[str, int]) -> str | None:
    m = _URL.match(rec.get("post_url") or "")
    if not m:
        return "post_url must be https://x.com/<handle>/status/<id>"
    if m.group(1) != rec.get("handle"):
        return "post_url handle differs from the record's handle"
    if rec.get("handle") not in accounts:
        return "handle is not in the X watchlist (no automatic additions)"
    if not _TS.match(rec.get("published_at_utc") or ""):
        return "published_at_utc must be an explicit UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)"
    if rec.get("availability", "available") not in AVAILABILITY:
        return f"availability must be one of {AVAILABILITY}"
    live = rec.get("availability", "available") in ("available", "edited")
    if live and not (rec.get("text") or "").strip():
        return "text is required for an available post"
    return None


def import_posts(db, records: list[dict], *, importer: str, rights_attestation: str, tagger=None) -> dict:
    """Import owner-supplied post records. Idempotent on the post id. Writes nothing for rejected records."""
    if not importer.strip() or not rights_attestation.strip():
        raise ValueError("importer and rights_attestation are required")
    from engines.news_tagging import NewsTagger

    tagger = tagger or NewsTagger(db)
    sectors = [r["name"] for r in db.execute("SELECT name FROM sectors")]
    accounts = {r["handle"]: r["account_id"] for r in db.execute(
        "SELECT account_id, handle FROM media_accounts WHERE platform = 'x' AND handle IS NOT NULL")}
    now = _now()
    db.execute(
        "INSERT INTO collector_runs(job, source_id, started_at_utc, status, quota_usage_json) "
        "VALUES (?,?,?,'running',?)",
        (JOB, SOURCE_ID, now, json.dumps({"importer": importer, "rights_attestation": rights_attestation})),
    )
    run_id = db.execute("SELECT MAX(run_id) AS r FROM collector_runs WHERE job = ?", (JOB,))[0]["r"]
    result = {"run_id": run_id, "accepted": [], "duplicates": [], "rejected": [], "needs_verification": []}
    for rec in records:
        err = _validate(rec, accounts)
        if err:
            result["rejected"].append({"post_url": rec.get("post_url"), "reason": err})
            continue
        post_id = _URL.match(rec["post_url"]).group(2)
        if db.execute("SELECT 1 FROM media_items WHERE platform = 'x' AND external_id = ?", (post_id,)):
            result["duplicates"].append(rec["post_url"])
            continue
        availability = rec.get("availability", "available")
        text = (rec.get("text") or "").strip()
        digest = _text_hash(text) if text else hashlib.sha256(rec["post_url"].encode()).hexdigest()
        copy_of = db.execute(
            "SELECT canonical_url FROM media_items WHERE platform = 'x' AND content_sha256 = ? "
            "AND published_at_utc <= ? ORDER BY published_at_utc LIMIT 1", (digest, rec["published_at_utc"]),
        ) if text else []
        ctype = claim_type(text, official=bool(rec.get("official_statement"))) if text else "unclear"
        reason = (f"copy of {copy_of[0]['canonical_url']} (repost/syndicated, not independent)"
                  if copy_of else None)
        db.execute(
            "INSERT INTO media_items(platform, external_id, account_id, canonical_url, published_at_utc, "
            "published_at_raw, collected_at_utc, content_sha256, text_pointer, permitted_excerpt, "
            "relevance_reason, rejection_reason) VALUES ('x',?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, accounts[rec["handle"]], rec["post_url"], rec["published_at_utc"],
             rec.get("published_at_raw"), now, digest, f"collector_run:{run_id}",
             text[:EXCERPT_MAX] or None, reason, None if availability == "available" else availability),
        )
        item_id = db.execute("SELECT media_item_id FROM media_items WHERE platform = 'x' AND external_id = ?",
                             (post_id,))[0]["media_item_id"]
        companies = tagger.tag(text).companies if text else []
        for c in companies:
            db.execute(
                "INSERT INTO media_mentions(media_item_id, company_id, entity, mention_type, claim_type, "
                "context_excerpt) VALUES (?,?,?,'company',?,?)",
                (item_id, c["company_id"], c["ticker"], ctype, c["evidence"][:200]),
            )
        for e in entity_mentions(text, sectors) if text else []:
            db.execute(
                "INSERT INTO media_mentions(media_item_id, company_id, entity, mention_type, claim_type, "
                "context_excerpt) VALUES (?,NULL,?,?,?,?)",
                (item_id, e["name"], f"{e['entity_type']}:{e['relation']}", ctype, e["evidence"][:200]),
            )
        if ctype == "prediction":
            for c in companies or [{"company_id": None}]:
                db.execute(
                    "INSERT INTO media_predictions(account_id, media_item_id, company_id, direction, "
                    "prediction_date) VALUES (?,?,?,?,?)",
                    (accounts[rec["handle"]], item_id, c["company_id"], _direction(text),
                     rec["published_at_utc"][:10]),
                )
        entry = {"post_url": rec["post_url"], "media_item_id": item_id, "claim_type": ctype,
                 "companies": [c["ticker"] for c in companies], "copy_of": copy_of[0]["canonical_url"]
                 if copy_of else None, "availability": availability}
        result["accepted"].append(entry)
        if ctype != "unclear" and (companies or ctype in ("news_report", "official_statement", "rumour")):
            result["needs_verification"].append(
                {"post_url": rec["post_url"],
                 "reason": "account claim: needs a primary or independent source"})
    db.execute(
        "UPDATE collector_runs SET status = 'succeeded', finished_at_utc = ?, items_fetched = ?, "
        "items_accepted = ?, items_rejected = ? WHERE run_id = ?",
        (_now(), len(records), len(result["accepted"]), len(result["rejected"]), run_id),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    from database.connection import connect

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    imp = sub.add_parser("import")
    imp.add_argument("file", help="JSON list of post records")
    imp.add_argument("--importer", required=True)
    imp.add_argument("--rights-attestation", required=True)
    a = p.parse_args(argv)
    db = connect()
    try:
        if a.cmd == "status":
            out = status(db)
        else:
            out = import_posts(db, json.loads(Path(a.file).read_text(encoding="utf-8")),
                               importer=a.importer, rights_attestation=a.rights_attestation)
        print(json.dumps(out, indent=1, ensure_ascii=False))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
