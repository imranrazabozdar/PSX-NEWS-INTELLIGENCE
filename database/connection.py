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
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

Row = dict[str, Any]
Statement = tuple[str, Sequence[Any]]


class DatabaseError(RuntimeError):
    """A statement or request failed."""


class DatabaseConfigError(DatabaseError):
    """The database is not configured, or configured incorrectly."""


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

    def __post_init__(self) -> None:
        if self.url.startswith("libsql://"):
            self.url = "https://" + self.url[len("libsql://"):]
        if not self.url.startswith("https://"):
            raise DatabaseConfigError("Turso URL must start with libsql:// or https://")
        if not self.auth_token:
            raise DatabaseConfigError("PSXNI_TURSO_AUTH_TOKEN is not set")
        self.url = self.url.rstrip("/")

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
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
