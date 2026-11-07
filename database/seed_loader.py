"""Load the validated reference data (sources, company master, watchlist) into the database.

Idempotent: re-running changes nothing. Validation runs first, and nothing is written if any
check fails.

Usage: python -m database.seed_loader [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from database.canonical import normalise_name, now_utc, short_name, to_utc
from database.connection import Database, connect
from database.repositories import record_source_item, upsert_source
from database.validation import (
    MONTHS,
    validate_company_seed,
    validate_media_watchlist,
    validate_source_registry,
)

SEED_DIR = Path(__file__).resolve().parent / "seed"
FFBL_MERGER_NOTE = ("PSX lists FFBL as DELISTED; its announcements include 'Notice of Final Book "
                    "Closure of FFBL Shares in accordance with Scheme of Arrangement for merger of "
                    "FFBL with and into FFC' (Dec 2024). Last PSX quote observed: 2024-12-20.")


def load_json(name: str) -> dict:
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def sector_id(name: str) -> str:
    return "psx-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def validate_all() -> list[str]:
    return (validate_source_registry(load_json("sources.json"))
            + validate_company_seed(load_json("companies.json"))
            + validate_media_watchlist(load_json("media_watchlist.json")))


def load(db: Database) -> dict[str, int]:
    errors = validate_all()
    if errors:
        raise ValueError("reference data failed validation:\n  " + "\n  ".join(errors))
    now = now_utc()
    for src in load_json("sources.json")["sources"]:
        upsert_source(db, src)

    seed = load_json("companies.json")
    k = seed["kse30_source"]
    kse_item = record_source_item(
        db, source_id="psx_dps", url=k["url"], content_hash=k["page_sha256"],
        collected_at_utc=k["fetched_at_utc"] + ("T00:00:00Z" if len(k["fetched_at_utc"]) == 10 else ""),
        title="KSE-30 index constituents")
    tickers = {c["ticker"]: c for c in seed["companies"]}
    company_ids: dict[str, str] = {}
    for c in seed["companies"]:
        src = c["source"]
        fetched, _, _ = to_utc(src["fetched_at_utc"])
        item = record_source_item(db, source_id="psx_dps", url=src["url"],
                                  content_hash=src["page_sha256"], collected_at_utc=fetched,
                                  title=f"PSX company profile: {c['ticker']}",
                                  excerpt=c["business_summary"] or None)
        cid = "cmp-" + c["ticker"].lower()
        company_ids[c["ticker"]] = cid
        sid = sector_id(c["psx_sector"])
        current = c["listing_status"] == "listed"
        valid_to = None if current else "2024-12-20"
        stmts = [
            ("INSERT INTO sectors(sector_id, scheme, name, created_at_utc) VALUES (?, 'PSX', ?, ?) "
             "ON CONFLICT DO NOTHING", (sid, c["psx_sector"], now)),
            ("""INSERT INTO companies(company_id, legal_name, listing_status, fiscal_year_end_month,
                   business_summary, profile_source_item_id, created_at_utc, updated_at_utc)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(company_id) DO NOTHING""",
             (cid, c["legal_name"], c["listing_status"], MONTHS[c["fiscal_year_end_month"]],
              c["business_summary"] or None, item.source_item_id, now, now)),
            ("""INSERT INTO company_identifiers(company_id, id_type, value, valid_from, valid_to,
                   verified_at_utc, source_item_id)
                SELECT ?, 'psx_ticker', ?, NULL, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM
                   company_identifiers WHERE company_id = ? AND id_type = 'psx_ticker' AND value = ?)""",
             (cid, c["ticker"], valid_to, fetched, item.source_item_id, cid, c["ticker"])),
            ("""INSERT INTO company_classifications(company_id, sector_id, valid_from, valid_to,
                   verified_at_utc, source_item_id)
                SELECT ?, ?, NULL, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM company_classifications
                   WHERE company_id = ? AND sector_id = ?)""",
             (cid, sid, valid_to, fetched, item.source_item_id, cid, sid)),
        ]
        aliases = [(c["ticker"], "ticker", "verified"), (c["legal_name"], "legal_name", "verified")]
        sn = short_name(c["legal_name"])
        if sn and sn != normalise_name(c["legal_name"]):
            aliases.append((sn, "short_name", "derived"))
        for alias, atype, conf in aliases:
            stmts.append((
                """INSERT INTO company_aliases(company_id, alias, alias_normalized, alias_type,
                       confidence, source_item_id, evidence) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT DO NOTHING""",
                (cid, alias, normalise_name(alias), atype, conf, item.source_item_id,
                 "derived from the PSX legal name by removing generic legal words"
                 if conf == "derived" else "PSX company page")))
        if c.get("kse30_member_observed"):
            stmts.append((
                "INSERT INTO index_memberships(index_code, company_id, observed_at_utc, source_item_id) "
                "VALUES ('KSE30', ?, ?, ?) ON CONFLICT DO NOTHING",
                (cid, k["fetched_at_utc"] + ("T00:00:00Z" if len(k["fetched_at_utc"]) == 10 else ""),
                 kse_item.source_item_id)))
        db.batch(stmts)

    # Delisting / merger history: append once, never edited.
    if "FFBL" in tickers and "FFC" in tickers:
        ffbl_item = db.execute("SELECT profile_source_item_id AS id FROM companies WHERE company_id=?",
                               (company_ids["FFBL"],))[0]["id"]
        for status, related in (("merged_into", company_ids["FFC"]), ("delisted", None)):
            db.execute(
                """INSERT INTO company_status_history(company_id, status, effective_date, date_precision,
                       related_company_id, details, source_item_id, recorded_at_utc)
                   SELECT ?, ?, '2024-12-20', 'observed', ?, ?, ?, ? WHERE NOT EXISTS (
                       SELECT 1 FROM company_status_history WHERE company_id = ? AND status = ?)""",
                (company_ids["FFBL"], status, related, FFBL_MERGER_NOTE, ffbl_item, now,
                 company_ids["FFBL"], status))

    wl = load_json("media_watchlist.json")
    for a in wl["accounts"]:
        source_id = "x_platform" if a["platform"] == "x" else "youtube_platform"
        if a["handle"]:
            db.execute(
                """INSERT INTO media_accounts(platform, handle, supplied_url, display_name,
                       monitoring_purpose, identity_verification, monitoring_status, source_id, notes,
                       created_at_utc) VALUES (?,?,?,?,?,'unverified','disabled',?,?,?)
                   ON CONFLICT DO NOTHING""",
                (a["platform"], a["handle"], a["supplied_url"], a.get("display_name"),
                 a["monitoring_purpose"], source_id, a.get("notes"), now))
        else:
            db.execute(
                """INSERT INTO media_accounts(platform, handle, display_name, monitoring_purpose,
                       identity_verification, monitoring_status, source_id, notes, created_at_utc)
                   SELECT ?, NULL, ?, ?, 'pending_confirmation', 'pending_handle', ?, ?, ?
                   WHERE NOT EXISTS (SELECT 1 FROM media_accounts WHERE platform = ? AND
                       handle IS NULL AND display_name = ?)""",
                (a["platform"], a["display_name"], a["monitoring_purpose"], source_id,
                 a.get("notes"), now, a["platform"], a["display_name"]))
    return counts(db)


def counts(db: Database) -> dict[str, int]:
    tables = ["sources", "source_items", "sectors", "companies", "company_identifiers",
              "company_aliases", "company_classifications", "company_status_history",
              "index_memberships", "media_accounts"]
    rows = db.batch([(f"SELECT COUNT(*) AS n FROM {t}", ()) for t in tables], transactional=False)  # noqa: S608
    return {t: r[0]["n"] for t, r in zip(tables, rows, strict=True)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load reference data")
    ap.add_argument("--dry-run", action="store_true", help="validate only; write nothing")
    args = ap.parse_args(argv)
    errors = validate_all()
    if errors:
        print("Validation FAILED:\n  " + "\n  ".join(errors))
        return 1
    print("Reference data validation passed.")
    if args.dry_run:
        return 0
    print(load(connect()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
