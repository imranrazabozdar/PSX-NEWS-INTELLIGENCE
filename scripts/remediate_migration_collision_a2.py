#!/usr/bin/env python3
"""One-off remediation (Option A2): retire foreign migration version 11 (extraction_reviews).

Why: a migration that is not in this repository was recorded as version 11. This repository's own
migration 0011 is "financial_documents", so `database.migrate` refuses to run
("migration 11 (extraction_reviews) was changed after it was applied") and nothing from 0011-0014 can
be applied. The foreign table holds no data. This script removes its five objects and its
`schema_migrations` row in ONE transaction, so version 11 is free for the repository's own 0011.

Safety:
* Default is a read-only dry run: it checks the pre-conditions and prints the plan.
* `--execute` also needs `--confirm retire-migration-11`, `--backup-sha256 <64 hex>` (the recorded
  SHA-256 of the backup, runbook step 1) and `--approval-id <text>` (the owner's approval reference).
* The transaction starts with an atomic guard: a permanent (non-TEMP) `_a2_guard` table, created and
  dropped inside the transaction, whose CHECK fails unless
  (a) extraction_reviews has 0 rows, (b) version 11 has exactly the expected name and checksum, and
  (c) 11 is the highest version. If the guard fails, the whole transaction rolls back.
* `--target` is required (no default): `disposable` reads PSXNI_TURSO_DISPOSABLE_* and must be a database
  named `psxni-migration-rehearsal-*` (an allow-list on top of the production deny-list); `production` reads
  PSXNI_TURSO_DATABASE_URL / PSXNI_TURSO_AUTH_TOKEN. Run the disposable rehearsal first.
* The pre-flight estimates the rows it will read and refuses if that exceeds the per-run read budget.
* Nothing here is a migration file: the migration runner refuses destructive statements by design.

Exit codes: 0 = pre-conditions met (dry run) or remediation verified; 2 = refused; 3 = failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from database.connection import Database, DatabaseError, connect
from database.migrate import MigrationError, discover, migrate
from engines import integrity

FOREIGN_VERSION = 11
FOREIGN_NAME = "extraction_reviews"
FOREIGN_CHECKSUM = "a9b55ef930503e72fa6cf8ff86f9611683f76c4c60767cdd6ccbb582ebc04c39"
FOREIGN_OBJECTS = (  # (type, name), in drop order
    ("view", "v_review_queue"),
    ("trigger", "trg_extraction_reviews_no_update"),
    ("trigger", "trg_extraction_reviews_no_delete"),
    ("index", "ix_extraction_reviews_extraction"),
    ("table", "extraction_reviews"),
)
CONFIRM_PHRASE = "retire-migration-11"
REPO_VERSIONS_AFTER = (11, 12, 13, 14)
# Full-table reads in one execute run: counts before, counts after, and the foreign-key scan inside
# integrity.check. The script itself runs no other foreign-key scan, to stay inside the per-run budget.
READ_PASSES = 2  # one full count scan in pre-flight, one in post-flight (pre-flight result is reused)
READ_RESERVE_ROWS = 2_000  # ledger/schema reads, runner dry-run and integrity check
READ_HEADROOM = 1.25  # refuse unless the budget covers the estimate with 25% to spare
REHEARSAL_HOST_PREFIX = "psxni-migration-rehearsal-"
# Owner-approved exception: ONE exact host that lacks the prefix. Never overrides the production deny-list.
HOST_OVERRIDE_VAR = "PSXNI_A2_REHEARSAL_HOST_OVERRIDE"

Statement = tuple[str, Sequence[Any]]


def remediation_statements(expected_checksum: str = FOREIGN_CHECKSUM) -> list[Statement]:
    """The exact transaction. The first two statements are the atomic guard."""
    return [
        ("CREATE TABLE _a2_guard(ok INTEGER NOT NULL CHECK (ok = 1))", ()),
        (
            "INSERT INTO _a2_guard SELECT CASE WHEN "
            "(SELECT COUNT(*) FROM extraction_reviews) = 0 "
            "AND (SELECT COUNT(*) FROM schema_migrations WHERE version = 11 "
            "AND name = 'extraction_reviews' AND checksum = ?) = 1 "
            "AND (SELECT MAX(version) FROM schema_migrations) = 11 "
            "THEN 1 ELSE 0 END",
            (expected_checksum,),
        ),
        ("DROP VIEW v_review_queue", ()),
        ("DROP TRIGGER trg_extraction_reviews_no_update", ()),
        ("DROP TRIGGER trg_extraction_reviews_no_delete", ()),
        ("DROP INDEX ix_extraction_reviews_extraction", ()),
        ("DROP TABLE extraction_reviews", ()),
        (
            "DELETE FROM schema_migrations WHERE version = 11 AND name = 'extraction_reviews' "
            "AND checksum = ?",
            (expected_checksum,),
        ),
        ("DROP TABLE _a2_guard", ()),
    ]


def table_counts(db: Database) -> dict[str, int]:
    names = [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    if not names:
        return {}
    results = db.batch(
        [(f'SELECT COUNT(*) AS n FROM "{n}"', ()) for n in names],  # noqa: S608 - names from sqlite_master
        transactional=False)
    return {n: int(rows[0]["n"]) for n, rows in zip(names, results, strict=True)}


def counts_digest(counts: dict[str, int]) -> str:
    """SHA-256 of the counts EXCLUDING the foreign table, so before/after are comparable."""
    kept = {k: v for k, v in counts.items() if k != FOREIGN_NAME}
    return hashlib.sha256(json.dumps(kept, sort_keys=True).encode()).hexdigest()


def expected_post_counts(pre: dict[str, int]) -> dict[str, int]:
    after = {k: v for k, v in pre.items() if k != FOREIGN_NAME}
    after["schema_migrations"] = pre.get("schema_migrations", 0) - 1
    return after


def preflight(db: Database) -> dict[str, Any]:
    """Read-only checks. `problems` must be empty before anything is executed."""
    problems: list[str] = []
    ledger = [dict(r) for r in db.execute(
        "SELECT version, name, checksum, applied_at_utc FROM schema_migrations ORDER BY version")]
    row11 = [r for r in ledger if r["version"] == FOREIGN_VERSION]
    if len(row11) != 1:
        problems.append("schema_migrations has no version 11 row")
    elif row11[0]["name"] != FOREIGN_NAME or row11[0]["checksum"] != FOREIGN_CHECKSUM:
        problems.append("version 11 is not the expected foreign migration (name/checksum differ)")
    if max((r["version"] for r in ledger), default=0) != FOREIGN_VERSION:
        problems.append("the highest applied version is not 11")
    present = {(r["type"], r["name"]) for r in db.execute(
        "SELECT type, name FROM sqlite_master WHERE name LIKE '%extraction_reviews%' "
        "OR name = 'v_review_queue'")}
    if any(r["name"] == "_a2_guard" for r in db.execute(
            "SELECT name FROM sqlite_master WHERE name = '_a2_guard'")):
        problems.append("a leftover _a2_guard table exists: inspect before running")
    present.discard(("table", "_a2_guard"))
    if present != set(FOREIGN_OBJECTS):
        problems.append(f"foreign objects differ from the expected five: {sorted(present)}")
    rows = None
    if ("table", FOREIGN_NAME) in present:
        rows = int(db.execute("SELECT COUNT(*) AS n FROM extraction_reviews")[0]["n"])
        if rows != 0:
            problems.append(f"extraction_reviews holds {rows} row(s): STOP, do not drop data")
    own = {name for _, name in FOREIGN_OBJECTS}
    dependents = [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE sql LIKE '%extraction_reviews%'") if r["name"] not in own]
    if dependents:
        problems.append(f"other objects reference extraction_reviews: {dependents}")
    counts = table_counts(db)
    estimate = READ_PASSES * sum(counts.values()) + READ_RESERVE_ROWS
    limit = getattr(db, "max_rows_read", None)
    if limit is not None and estimate * READ_HEADROOM > limit:
        problems.append(
            f"estimated rows read {estimate} (x{READ_HEADROOM} headroom) exceeds the per-run read budget "
            f"{limit}: raising PSXNI_DB_MAX_ROWS_READ for this run needs the owner's approval "
            "(runbook section 1)")
    used = getattr(db, "usage", None)
    if callable(used) and limit is not None:
        # what the post-COMMIT verification still needs must remain after the pre-flight reads
        remaining = limit - int(used().get("rows_read", 0))
        needed = sum(counts.values()) + READ_RESERVE_ROWS
        if remaining < needed * READ_HEADROOM:
            problems.append(f"only {remaining} rows of read budget remain after pre-flight; the "
                            f"post-flight verification needs about {needed}: refusing")
    return {
        "estimated_rows_read": estimate,
        "ledger_versions": [r["version"] for r in ledger],
        "version_11": row11[0] if row11 else None,
        "extraction_reviews_rows": rows,
        "counts": counts,
        "digest": counts_digest(counts),
        "expected_post_digest": counts_digest(expected_post_counts(counts)),
        "problems": problems,
    }


def postflight(db: Database, pre: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    versions = [r["version"] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
    if versions != list(range(1, 11)):
        problems.append(f"ledger is {versions}, expected 1..10")
    left = [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%extraction_reviews%' "
        "OR name IN ('v_review_queue', '_a2_guard')")]
    if left:
        problems.append(f"foreign objects still present: {left}")
    counts = table_counts(db)
    if pre["counts"] is not None and counts != expected_post_counts(pre["counts"]):
        diff = {k: (pre["counts"].get(k), counts.get(k)) for k in set(pre["counts"]) | set(counts)
                if pre["counts"].get(k) != counts.get(k)}
        problems.append(f"row counts differ beyond the expected change: {diff}")
    try:
        log = migrate(db, dry_run=True)
    except MigrationError as exc:
        log = []
        problems.append(f"migration runner still refuses: {exc}")
    would = [line.split()[2] for line in log if line.startswith("would apply")]
    expected_would = [f"{m.version:04d}_{m.name}" for m in discover() if m.version in REPO_VERSIONS_AFTER]
    if would != expected_would:
        problems.append(f"runner would apply {would}, expected {expected_would}")
    report = integrity.check(db)
    if report["problems"]:
        problems.append(f"integrity check: {report['problems']}")
    digest = counts_digest(counts)
    if digest != pre["expected_post_digest"]:
        problems.append("row-count digest differs from the expected post-remediation digest")
    return {"ledger_versions": versions, "runner_would_apply": would, "integrity_state": report["state"],
            "digest": digest, "digest_matches_expected": digest == pre["expected_post_digest"],
            "problems": problems}


def run(db: Database, *, execute: bool = False, backup_sha256: str = "", approval_id: str = "",
        confirm: str = "", expect_pre_digest: str = "", expect_post_digest: str = "") -> dict[str, Any]:
    report: dict[str, Any] = {"started_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "mode": "execute" if execute else "dry_run"}
    pre = preflight(db)
    report["preflight"] = {k: v for k, v in pre.items() if k != "counts"} | {"tables": len(pre["counts"])}
    if expect_pre_digest and pre["digest"] != expect_pre_digest:
        pre["problems"].append("pre-flight digest differs from the approved snapshot (production changed?)")
    if expect_post_digest and pre["expected_post_digest"] != expect_post_digest:
        pre["problems"].append("expected post-flight digest differs from the approved value")
    report["preflight"]["problems"] = pre["problems"]
    if pre["problems"]:
        report["status"] = "refused"
        return report
    if not execute:
        report["status"] = "dry_run_ok"
        report["plan"] = [sql for sql, _ in remediation_statements()]
        return report
    missing = (confirm != CONFIRM_PHRASE or not re.fullmatch(r"[0-9a-f]{64}", backup_sha256)
               or not approval_id.strip())
    if missing:
        report["status"] = "refused"
        report["preflight"]["problems"].append(
            f"--execute needs --confirm {CONFIRM_PHRASE}, a 64-hex --backup-sha256 and an --approval-id")
        return report
    report["backup_sha256"], report["approval_id"] = backup_sha256, approval_id.strip()
    try:
        db.batch(remediation_statements(), transactional=True)
    except DatabaseError as exc:  # guard or any statement failed: the transaction rolled back
        report["status"] = "failed_rolled_back"
        report["error"] = str(exc)[:200]
        return report
    try:
        post = postflight(db, pre)
    except DatabaseError as exc:  # the transaction COMMITTED; only the verification could not finish
        report["status"] = "remediated_check_failed"
        report["error"] = (
            f"the transaction COMMITTED but post-flight verification did not finish: {str(exc)[:200]}. "
            "Do NOT treat this as verified and do NOT re-run --execute; run --verify-only in a fresh "
            "process with --expect-post-digest")
        return report
    report["postflight"] = post
    report["status"] = "remediated_verified" if not post["problems"] else "remediated_check_failed"
    usage = getattr(db, "usage", None)
    if callable(usage):
        report["usage"] = usage()
    return report


def verify_only(db: Database, expect_post_digest: str) -> dict[str, Any]:
    """Read-only post-remediation verification in a fresh process (fresh read budget)."""
    report: dict[str, Any] = {"mode": "verify_only"}
    if not re.fullmatch(r"[0-9a-f]{64}", expect_post_digest):
        report["status"] = "refused"
        report["problems"] = ["--verify-only needs the 64-hex --expect-post-digest from the approved plan"]
        return report
    try:
        post = postflight(db, {"counts": None, "expected_post_digest": expect_post_digest})
    except DatabaseError as exc:
        report["status"] = "verify_failed"
        report["error"] = str(exc)[:200]
        return report
    report["postflight"] = post
    report["status"] = "verified" if not post["problems"] else "verify_failed"
    return report


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower().rstrip(".")


def target_problem(target: str, env: dict[str, str] | os._Environ[str]) -> str:
    """Reason the chosen target must be refused, or '' if acceptable."""
    prod_url = env.get("PSXNI_TURSO_DATABASE_URL", "").strip()
    if target == "disposable":
        url = env.get("PSXNI_TURSO_DISPOSABLE_DATABASE_URL", "").strip()
        if not url:
            return "PSXNI_TURSO_DISPOSABLE_DATABASE_URL is not set"
        override = env.get(HOST_OVERRIDE_VAR, "").strip().lower()
        if override and override != _host(url):
            return f"{HOST_OVERRIDE_VAR} does not match the disposable host exactly: refusing"
        if not override and not _host(url).startswith(REHEARSAL_HOST_PREFIX):
            return (f"the disposable host must start with {REHEARSAL_HOST_PREFIX!r} "
                    "(the rehearsal database naming convention): refusing")
        same_host = bool(prod_url) and _host(url) == _host(prod_url)
        if "psx-news-intelligence-imranrazabozdar" in url.lower() or same_host:
            return "the disposable URL is the production database: refusing"
        prod_token = env.get("PSXNI_TURSO_AUTH_TOKEN", "").strip()
        if prod_token and prod_token == env.get("PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN", "").strip():
            return "the disposable token equals the production token: refusing"
    elif not prod_url:
        return "PSXNI_TURSO_DATABASE_URL is not set"
    return ""


def _connect(target: str) -> Database:
    problem = target_problem(target, os.environ)
    if problem:
        raise DatabaseError(problem)
    url_var, token_var = {
        "production": ("PSXNI_TURSO_DATABASE_URL", "PSXNI_TURSO_AUTH_TOKEN"),
        "disposable": ("PSXNI_TURSO_DISPOSABLE_DATABASE_URL", "PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN"),
    }[target]
    return connect(os.environ.get(url_var, ""), os.environ.get(token_var, ""),
                   purpose=target)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", choices=["production", "disposable"], required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm", default="")
    p.add_argument("--backup-sha256", default="")
    p.add_argument("--approval-id", default="")
    p.add_argument("--expect-pre-digest", default="")
    p.add_argument("--expect-post-digest", default="")
    p.add_argument("--verify-only", action="store_true",
                   help="read-only post-remediation check in a fresh process (needs --expect-post-digest)")
    a = p.parse_args(argv)
    if a.verify_only:
        report = verify_only(_connect(a.target), a.expect_post_digest)
        report["target"] = a.target
        print(json.dumps(report, indent=1, sort_keys=True, default=str))
        return 0 if report["status"] == "verified" else 3
    report = run(_connect(a.target), execute=a.execute, backup_sha256=a.backup_sha256,
                 approval_id=a.approval_id, confirm=a.confirm, expect_pre_digest=a.expect_pre_digest,
                 expect_post_digest=a.expect_post_digest)
    report["target"] = a.target
    print(json.dumps(report, indent=1, sort_keys=True, default=str))
    return {"dry_run_ok": 0, "remediated_verified": 0, "refused": 2}.get(report["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
