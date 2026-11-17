"""Read-only link to the owner's technical engine database (ADR-0008, signed 2026-11-17).

Rules (all enforced here, not by convention):
* READ ONLY: only SELECT/WITH statements pass; anything else raises before a request is made.
* SCHEMA DISCOVERY FIRST: until the owner approves Schedule A, only schema questions are allowed
  (table names and column names from sqlite_master / pragma_table_info). Data tables are not read.
* ALLOWLIST: once approved, only the objects in `ALLOWED_OBJECTS` may be queried. It is empty until the
  owner signs Schedule A, so no data read is possible yet.
* FAIL CLOSED: the target must not be the psx-library host and must be named explicitly in the environment.
* Per-run caps: rows read and requests (see DISCOVERY_ROW_CAP / MAX_REQUESTS).
Nothing is imported or copied from the technical engine's repository; only its database is read.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from database.connection import TursoHTTPDatabase

URL_VAR = "PSXNI_TECH_LINK_URL"
TOKEN_VAR = "PSXNI_TECH_LINK_TOKEN"  # noqa: S105 - a variable name, not a secret
LIBRARY_MARKER = "psx-library"

# Schedule A of ADR-0008. Empty until the owner approves the data tables; discovery needs none.
ALLOWED_OBJECTS: frozenset[str] = frozenset()

DISCOVERY_ROW_CAP = 5_000
MAX_REQUESTS = 60

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LinkError(RuntimeError):
    """The link refused to act."""


class ReadOnlyViolation(LinkError):
    pass


class NotAllowed(LinkError):
    pass


def host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].strip().lower()


def check_target(url: str) -> str:
    """Fail closed. Returns the host name only when it is clearly a different database from the library."""
    host = host_of(url)
    if not host:
        raise LinkError(f"{URL_VAR} has no host")
    if LIBRARY_MARKER in host:
        raise LinkError("refused: the link URL names the psx-library database, not the technical engine's")
    return host


@dataclass
class TechnicalLink:
    db: Any
    host: str
    allowed: frozenset[str] = ALLOWED_OBJECTS

    def _select(self, sql: str, params: tuple = ()) -> list[Any]:
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in ("SELECT", "WITH"):
            raise ReadOnlyViolation(f"refused a non-read statement: {sql.strip()[:60]!r}")
        return self.db.execute(sql, params)

    # --- discovery: names only, no data ------------------------------------------------------------
    def tables(self) -> list[tuple[str, str]]:
        rows = self._select(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [(str(r["name"]), str(r["type"])) for r in rows]

    def columns(self, table: str) -> list[dict[str, Any]]:
        if not _IDENT.match(table):
            raise NotAllowed(f"refused an unsafe object name: {table!r}")
        rows = self._select("SELECT name, type, pk FROM pragma_table_info(?)", (table,))
        return [{"name": str(r["name"]), "type": str(r["type"]), "pk": int(r["pk"] or 0)} for r in rows]

    # --- data: only allowlisted objects, none until the owner approves Schedule A -------------------
    def select_from(self, obj: str, sql: str, params: tuple = ()) -> list[Any]:
        if obj not in self.allowed:
            raise NotAllowed(f"{obj!r} is not in the owner-approved allowlist (ADR-0008 Schedule A)")
        return self._select(sql, params)


def connect(environ: Mapping[str, str] | None = None) -> TechnicalLink:
    env = os.environ if environ is None else environ
    url = (env.get(URL_VAR) or "").strip()
    token = (env.get(TOKEN_VAR) or "").strip()
    if not url or not token:
        raise LinkError(f"{URL_VAR} and {TOKEN_VAR} must both be set")
    host = check_target(url)
    db = TursoHTTPDatabase(url, token)
    db.max_rows_read = min(db.max_rows_read, DISCOVERY_ROW_CAP)
    db.max_requests = min(db.max_requests, MAX_REQUESTS)
    return TechnicalLink(db=db, host=host)
