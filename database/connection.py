"""Database access for this project's own Turso database (ADR-0001, ADR-0004).

Two backends run the same SQL:
  * TursoHTTPDatabase - production. It talks to Turso's documented Hrana-over-HTTP API
    (POST /v2/pipeline) using only the standard library, so no driver dependency is needed.
  * SQLiteDatabase - local development and tests (a file or ':memory:').

Every request turns on foreign-key enforcement. Multi-statement writes run as one atomic
batch (BEGIN ... COMMIT, with ROLLBACK if any step fails).
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Row = dict[str, Any]
Statement = tuple[str, Sequence[Any]]


class DatabaseError(RuntimeError):
    """A statement or request failed."""


class DatabaseConfigError(DatabaseError):
    """The database is not configured, or configured incorrectly."""


class DatabaseBudgetError(DatabaseError):
    """The per-run usage budget or the kill switch stopped further database requests."""


# Per-process budgets protect the Turso free-tier quota (spec section 17). Override with
# PSXNI_DB_MAX_ROWS_READ / PSXNI_DB_MAX_ROWS_WRITTEN / PSXNI_DB_MAX_REQUESTS.
DEFAULT_MAX_ROWS_READ = 50_000
DEFAULT_MAX_ROWS_WRITTEN = 5_000
DEFAULT_MAX_REQUESTS = 2_000


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


class Database:
    backend = "abstract"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[Row]:
        return self.batch([(sql, params)], transactional=False)[0]

    def batch(self, statements: Iterable[Statement], *, transactional: bool = True,
              rollback: bool = False) -> list[list[Row]]:
        """Run statements in order and return the rows from each.

        With transactional=True the statements run atomically. With rollback=True the batch is
        always rolled back after running, which lets tests run real reads and writes on the
        production database without leaving any data behind.
        """
        raise NotImplementedError

    def validate(self) -> dict[str, Any]:
        """Check that the connection works and foreign keys are enforced. Raises on failure."""
        rows = self.batch([("SELECT 1 AS ok, sqlite_version() AS sqlite_version", ()),
                           ("PRAGMA foreign_keys", ())], transactional=False)
        ok = rows[0][0]["ok"] == 1
        fk = list(rows[1][0].values())[0] == 1 if rows[1] else False
        if not ok:
            raise DatabaseError("connection check returned an unexpected result")
        if not fk:
            raise DatabaseError("foreign key enforcement is not active")
        return {"backend": self.backend, "sqlite_version": rows[0][0]["sqlite_version"],
                "foreign_keys": fk}

    def usage(self) -> dict[str, int]:
        return {"requests": 0, "rows_read": 0, "rows_written": 0}

    def close(self) -> None:  # pragma: no cover - default no-op
        pass


class SQLiteDatabase(Database):
    backend = "sqlite"

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def batch(self, statements, *, transactional=True, rollback=False):
        statements = list(statements)
        results: list[list[Row]] = []
        cur = self._conn.cursor()
        try:
            if transactional or rollback:
                cur.execute("BEGIN")
            for sql, params in statements:
                cur.execute(sql, tuple(params))
                results.append([dict(r) for r in cur.fetchall()] if cur.description else [])
            if rollback:
                cur.execute("ROLLBACK")
            elif transactional:
                cur.execute("COMMIT")
        except sqlite3.Error as exc:
            if self._conn.in_transaction:
                cur.execute("ROLLBACK")
            raise DatabaseError(str(exc)) from exc
        return results

    def close(self) -> None:
        self._conn.close()


def _encode_arg(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes | bytearray):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode()}
    return {"type": "text", "value": str(value)}


def _decode_value(v: dict[str, Any]) -> Any:
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v["base64"])
    return v.get("value")


def _rows(result: dict[str, Any]) -> list[Row]:
    cols = [c["name"] for c in result.get("cols", [])]
    return [dict(zip(cols, (_decode_value(v) for v in row), strict=True))
            for row in result.get("rows", [])]


@dataclass
class TursoHTTPDatabase(Database):
    url: str
    auth_token: str
    timeout: float = 30.0
    max_attempts: int = 3
    backend = "turso"
    requests: int = 0
    rows_read: int = 0
    rows_written: int = 0

    def __post_init__(self) -> None:
        if self.url.startswith("libsql://"):
            self.url = "https://" + self.url[len("libsql://"):]
        if not self.url.startswith("https://"):
            raise DatabaseConfigError("Turso URL must start with libsql:// or https://")
        if not self.auth_token:
            raise DatabaseConfigError("PSXNI_TURSO_AUTH_TOKEN is not set")
        self.url = self.url.rstrip("/")
        self.max_rows_read = _env_int("PSXNI_DB_MAX_ROWS_READ", DEFAULT_MAX_ROWS_READ)
        self.max_rows_written = _env_int("PSXNI_DB_MAX_ROWS_WRITTEN", DEFAULT_MAX_ROWS_WRITTEN)
        self.max_requests = _env_int("PSXNI_DB_MAX_REQUESTS", DEFAULT_MAX_REQUESTS)

    def usage(self) -> dict[str, int]:
        return {"requests": self.requests, "rows_read": self.rows_read,
                "rows_written": self.rows_written}

    def _check_budget(self) -> None:
        if os.environ.get("PSXNI_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise DatabaseBudgetError("PSXNI_KILL_SWITCH is on: database requests are disabled")
        if (self.requests >= self.max_requests or self.rows_read >= self.max_rows_read
                or self.rows_written >= self.max_rows_written):
            raise DatabaseBudgetError(f"per-run database budget exhausted: {self.usage()}")

    def _meter(self, payload: Any) -> None:
        if isinstance(payload, dict):
            if "rows_read" in payload or "rows_written" in payload:
                self.rows_read += int(payload.get("rows_read") or 0)
                self.rows_written += int(payload.get("rows_written") or 0)
            for v in payload.values():
                self._meter(v)
        elif isinstance(payload, list):
            for v in payload:
                self._meter(v)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        self._check_budget()
        self.requests += 1
        out = self._send(body)
        self._meter(out)
        return out

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode()
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            req = urllib.request.Request(  # noqa: S310 - https enforced in __post_init__
                self.url + "/v2/pipeline", data=data, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.auth_token}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (401, 403):
                    raise DatabaseConfigError(
                        f"Turso rejected the credentials (HTTP {exc.code})") from exc
                if exc.code in (502, 503, 504) and attempt < self.max_attempts:
                    last_error = exc
                else:
                    raise DatabaseError(f"Turso HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
            time.sleep(2 ** (attempt - 1))
        raise DatabaseError(f"Turso request failed after {self.max_attempts} attempts: {last_error}")

    def batch(self, statements, *, transactional=True, rollback=False):
        statements = list(statements)
        stmts = [{"sql": "PRAGMA foreign_keys = ON"}] + [
            {"sql": sql, "args": [_encode_arg(p) for p in params]} for sql, params in statements]
        if not (transactional or rollback):
            body = {"requests": [{"type": "execute", "stmt": s} for s in stmts]
                    + [{"type": "close"}]}
            out = self._post(body)["results"]
            results = []
            for i, r in enumerate(out[:-1]):
                if r["type"] != "ok":
                    raise DatabaseError(r.get("error", {}).get("message", "statement failed"))
                if i > 0:
                    results.append(_rows(r["response"]["result"]))
            return results

        # Atomic: PRAGMA, BEGIN, statements (each only if the previous succeeded),
        # COMMIT (or ROLLBACK when rollback=True), and ROLLBACK if anything failed.
        steps: list[dict[str, Any]] = [{"stmt": stmts[0]}, {"stmt": {"sql": "BEGIN"}}]
        for s in stmts[1:]:
            steps.append({"stmt": s, "condition": {"type": "ok", "step": len(steps) - 1}})
        last = len(steps) - 1
        final = "ROLLBACK" if rollback else "COMMIT"
        steps.append({"stmt": {"sql": final}, "condition": {"type": "ok", "step": last}})
        end = len(steps) - 1
        steps.append({"stmt": {"sql": "ROLLBACK"},
                      "condition": {"type": "not", "cond": {"type": "ok", "step": end}}})
        out = self._post({"requests": [{"type": "batch", "batch": {"steps": steps}},
                                       {"type": "close"}]})
        res = out["results"][0]
        if res["type"] != "ok":
            raise DatabaseError(res.get("error", {}).get("message", "batch failed"))
        b = res["response"]["result"]
        for err in b.get("step_errors", []):
            if err:
                raise DatabaseError(err.get("message", "statement failed"))
        step_results = b.get("step_results", [])
        if step_results[end] is None:
            raise DatabaseError(f"{final} did not run; the batch was rolled back")
        return [_rows(step_results[i]) if step_results[i] else []
                for i in range(2, last + 1)]


def connect(url: str | None = None, auth_token: str | None = None) -> Database:
    """Open the configured database. Never falls back silently to another database.

    url forms: libsql://... or https://... (Turso), sqlite:///path or sqlite://:memory: (local).
    Defaults come from PSXNI_TURSO_DATABASE_URL / PSXNI_TURSO_AUTH_TOKEN.
    """
    url = url if url is not None else os.environ.get("PSXNI_TURSO_DATABASE_URL", "")
    if not url:
        raise DatabaseConfigError("PSXNI_TURSO_DATABASE_URL is not set")
    if url.startswith(("libsql://", "https://")):
        token = auth_token if auth_token is not None else os.environ.get("PSXNI_TURSO_AUTH_TOKEN", "")
        return TursoHTTPDatabase(url, token)
    if url.startswith("sqlite://"):
        path = url[len("sqlite://"):]
        if path in ("", ":memory:", "/:memory:"):
            return SQLiteDatabase(":memory:")
        return SQLiteDatabase(path)  # sqlite:///abs/path.db -> /abs/path.db
    raise DatabaseConfigError("unsupported database URL scheme")


# ---------------------------------------------------------------- dual database: main and archive
# Main (operational): events, news, active company data. Variables: PSXNI_TURSO_DATABASE_URL and
#   PSXNI_TURSO_AUTH_TOKEN (the existing names, used by CI; renaming them would break production secrets).
# Archive (multi-year financial history): PSXNI_ARCHIVE_TURSO_URL and PSXNI_ARCHIVE_TURSO_AUTH_TOKEN.
# Each handler reads only its own variables and never falls back to the other database's token or URL.
MAIN_URL_ENV = "PSXNI_TURSO_DATABASE_URL"
MAIN_TOKEN_ENV = "PSXNI_TURSO_AUTH_TOKEN"  # noqa: S105 (variable name, not a secret)
ARCHIVE_URL_ENV = "PSXNI_ARCHIVE_TURSO_URL"
ARCHIVE_TOKEN_ENV = "PSXNI_ARCHIVE_TURSO_AUTH_TOKEN"  # noqa: S105 (variable name, not a secret)
# Table sets, derived from the migration directories (not hand-maintained). A database holding another
# role's tables is refused (fail closed). The archive set is every table the archive migrations create.
_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
_DATABASE_DIR = Path(__file__).resolve().parent


def tables_created_by(directory: Path) -> frozenset[str]:
    """Every table name created by the .sql files in `directory`. SQL comments are ignored."""
    names: set[str] = set()
    for path in sorted(directory.glob("*.sql")):
        code = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        names |= {m.group(1).lower() for m in _CREATE_TABLE.finditer(code)}
    return frozenset(names)


OPERATIONAL_TABLES = tables_created_by(_DATABASE_DIR / "migrations")
ARCHIVE_TABLES = tables_created_by(_DATABASE_DIR / "archive_migrations")
PORTFOLIO_TABLES = tables_created_by(_DATABASE_DIR / "portfolio_migrations")


def _norm_db_identity(url: str) -> str:
    """Compare database identities, not spellings: libsql:// and https:// name the same Turso database."""
    u = url.strip().rstrip("/").lower()
    for scheme in ("libsql://", "https://", "wss://", "http://"):
        if u.startswith(scheme):
            return "turso:" + u[len(scheme):].split("?")[0]
    return u


def same_database(a: str, b: str) -> bool:
    if not a or not b or "memory" in a or "memory" in b:
        return False
    return _norm_db_identity(a) == _norm_db_identity(b)


def _tables_present(db: Database) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r["name"] for r in rows}


def assert_role(db: Database, role: str) -> None:
    """Refuse a handle whose tables belong to the other role. Called by every connect_* function."""
    present = _tables_present(db)
    if role == "main":
        if present & ARCHIVE_TABLES:
            raise DatabaseConfigError(f"refusing: the main database holds archive tables "
                                      f"{sorted(present & ARCHIVE_TABLES)}")
        if present & PORTFOLIO_TABLES:
            raise DatabaseConfigError(f"refusing: the main database holds portfolio tables "
                                      f"{sorted(present & PORTFOLIO_TABLES)}")
    if role == "archive":
        if present & OPERATIONAL_TABLES:
            raise DatabaseConfigError(f"refusing: the archive database holds operational tables "
                                      f"{sorted(present & OPERATIONAL_TABLES)}; it must be separate")
        if present & PORTFOLIO_TABLES:
            raise DatabaseConfigError(f"refusing: the archive database holds portfolio tables "
                                      f"{sorted(present & PORTFOLIO_TABLES)}; it must be separate")


def connect_main(url: str | None = None, auth_token: str | None = None) -> Database:
    """Operational database handle. Refuses the archive URL and any database holding archive tables."""
    url = url if url is not None else os.environ.get(MAIN_URL_ENV, "")
    if not url:
        raise DatabaseConfigError(f"{MAIN_URL_ENV} is not set")
    archive_url = os.environ.get(ARCHIVE_URL_ENV, "")
    if archive_url and same_database(url, archive_url):
        raise DatabaseConfigError("the main database URL is the archive database URL; they must be separate")
    token = auth_token if auth_token is not None else os.environ.get(MAIN_TOKEN_ENV, "")
    db = connect(url, token)
    try:
        assert_role(db, "main")
    except DatabaseConfigError:
        db.close()
        raise
    db.role = "main"
    return db


def connect_archive(url: str | None = None, auth_token: str | None = None) -> Database:
    """Archive database handle. Requires its own URL and token; refuses the main database."""
    url = url if url is not None else os.environ.get(ARCHIVE_URL_ENV, "")
    if not url:
        raise DatabaseConfigError(f"{ARCHIVE_URL_ENV} is not set: the archive database is not configured")
    main_url = os.environ.get(MAIN_URL_ENV, "")
    if main_url and same_database(url, main_url):
        raise DatabaseConfigError("the archive database URL is the main database URL; they must be separate")
    # never fall back to the main token: a missing archive token is an error, not a reuse
    token = auth_token if auth_token is not None else os.environ.get(ARCHIVE_TOKEN_ENV, "")
    if url.startswith(("libsql://", "https://")) and not token:
        raise DatabaseConfigError(f"{ARCHIVE_TOKEN_ENV} is not set")
    db = connect(url, token)
    try:
        assert_role(db, "archive")
    except DatabaseConfigError:
        db.close()
        raise
    db.role = "archive"
    return db
