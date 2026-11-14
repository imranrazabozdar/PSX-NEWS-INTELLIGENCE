"""The ONLY place the company-library database is opened. Every reader and writer of the library imports
`get_library_connection()` from here. No other module builds a client for the library.

Source of truth: the environment variables PSXNI_LIBRARY_TURSO_DATABASE_URL and
PSXNI_LIBRARY_TURSO_AUTH_TOKEN. Proxy credential injection is NOT used: the token is read from the
environment.

Fail closed: a missing or empty variable raises, naming the variable. No fallback to any other database.
Target guard: the host must name psx-library. Data-capture, archival, production and capture hosts are refused
before any connection is made. Only the host name is logged; the token and the full URL are never printed.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from database.connection import Database, TursoHTTPDatabase

URL_VAR = "PSXNI_LIBRARY_TURSO_DATABASE_URL"
TOKEN_VAR = "PSXNI_LIBRARY_TURSO_AUTH_TOKEN"  # noqa: S105 - a variable name, not a secret
LIBRARY_MARKER = "psx-library"
FORBIDDEN_MARKERS = ("data-capture", "data-archival", "archival", "archive", "production", "prod", "capture")
PROBE_TABLE_DDL = ("CREATE TABLE IF NOT EXISTS library_probe (marker TEXT PRIMARY KEY, source TEXT NOT NULL, "
                   "payload TEXT NOT NULL CHECK (length(payload) < 1024))")


class LibraryConfigError(RuntimeError):
    """A library variable is missing or empty, or the target is refused. Nothing is opened."""


@dataclass(frozen=True)
class LibraryConnection:
    host: str  # the resolved host name only, safe to log
    db: Database


def resolve_host(url: str) -> str:
    """The host name of the library URL, after the target guard. Raises on any refused target."""
    host = url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].strip().lower()
    if not host:
        raise LibraryConfigError(f"{URL_VAR} has no host")
    if any(m in host for m in FORBIDDEN_MARKERS):
        raise LibraryConfigError("refused: the URL resolves to a production, data-capture or archival "
                                 "database")
    if LIBRARY_MARKER not in host:
        raise LibraryConfigError("refused: the URL does not name the psx-library database")
    return host


def _required(environ: Mapping[str, str], name: str) -> str:
    value = (environ.get(name) or "").strip()
    if not value:
        raise LibraryConfigError(f"{name} is not set or empty; set it in the environment, never in chat")
    return value


def get_library_connection(environ: Mapping[str, str] | None = None) -> LibraryConnection:
    """Open the library. Fail-closed. This is the single connection path for the library."""
    env = os.environ if environ is None else environ
    url = _required(env, URL_VAR)
    token = _required(env, TOKEN_VAR)
    host = resolve_host(url)
    return LibraryConnection(host=host, db=TursoHTTPDatabase(url, token))


def auth_check(conn: LibraryConnection) -> list[Any]:
    """SELECT 1. If the token does not authenticate, the error is raised unchanged, to be shown verbatim."""
    return conn.db.execute("SELECT 1 AS ok")


def probe_round_trip(db: Database, *, marker: str | None = None,
                     payload: str | None = None) -> dict[str, Any]:
    """Insert one synthetic record into the approved probe table, read it back by its unique marker, assert
    exactly one row, and delete it in a finally block. The payload is synthetic and under 1 KB."""
    import json

    marker = marker or f"psxni-probe-{uuid.uuid4().hex}"
    body = payload or json.dumps({"synthetic": True, "purpose": "library placement probe", "source": "test"},
                                 sort_keys=True)
    if len(body.encode("utf-8")) >= 1024:
        raise ValueError("probe payload must be under 1 KB")
    db.execute(PROBE_TABLE_DDL)
    try:
        db.execute("INSERT INTO library_probe (marker, source, payload) VALUES (?, ?, ?)",
                   (marker, "test", body))
        rows = db.execute("SELECT marker, source, payload FROM library_probe WHERE marker = ?", (marker,))
        exactly_one = len(rows) == 1
        matched = exactly_one and rows[0]["payload"] == body and rows[0]["source"] == "test"
    finally:
        db.execute("DELETE FROM library_probe WHERE marker = ?", (marker,))
    left = db.execute("SELECT COUNT(*) AS n FROM library_probe WHERE marker = ?", (marker,))[0]["n"]
    return {"inserted": True, "read_back_rows": len(rows), "exactly_one": exactly_one, "matched": matched,
            "deleted": left == 0, "marker": marker}


def main() -> int:
    """The decisive check, run from the environment. Prints the verbatim auth error on failure."""
    try:
        conn = get_library_connection()
    except LibraryConfigError as exc:
        print(f"library connection REFUSED: {exc}")
        return 2
    try:
        auth_check(conn)
    except Exception as exc:  # the exact error is shown, so the cause is visible
        print(f"library auth FAILED: {type(exc).__name__}: {exc}")
        return 3
    print(f"library connection OK -> host={conn.host}")
    result = probe_round_trip(conn.db)
    print(f"probe round trip: {result}")
    ok = result["exactly_one"] and result["matched"] and result["deleted"]
    print("data-capture and archival-test were never opened.")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
