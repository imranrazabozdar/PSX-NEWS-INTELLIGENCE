"""WSGI receiver for PSX announcement metadata dispatched by engines/termux_node_runner.py.

Standard library only: this is a plain WSGI callable, so any WSGI host can serve it. The repository has no
HTTP server of its own; its cloud writes go through database.connection.connect() with PSXNI_ variables.

Endpoint: POST /ingest/psx-announcement   (JSON object, the keys built by termux_node_runner.build_payload)

Auth: "Authorization: Bearer <PSXNI_ANNOUNCE_INGEST_TOKEN>". If that variable is unset the receiver refuses
every request with 503 (fails closed) rather than accepting unauthenticated writes.

Responses:
  201  stored as a new announcement
  200  already stored with the same dedup key; nothing written (idempotent replay)
  400  payload invalid          401  bad or missing token        404  unknown path
  405  wrong method             413  body too large             415  not JSON
  500  storage unavailable (the runner retries on its next tick)
  503  receiver token not configured
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from database.connection import Database, connect
from database.psx_announcements import exists, upsert_announcement

log = logging.getLogger("psx.receiver")

PATH = "/ingest/psx-announcement"
TOKEN_ENV = "PSXNI_ANNOUNCE_INGEST_TOKEN"  # noqa: S105 - a variable name, not a secret
MAX_BODY = 16_384
TRACKS = frozenset({"flash", "heavy"})
SOURCES = frozenset({"open_mirror", "corporate_ir", "exchange_edge", "unresolved"})
_FIELDS = frozenset(
    {"date", "time", "symbol", "category", "title", "doc_id", "track", "source", "target_url"}
)
_REQUIRED = ("symbol", "date", "title", "track", "source")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Response = tuple[int, dict[str, Any]]


class InvalidPayload(ValueError):
    pass


def validate_payload(obj: Any) -> dict[str, Any]:
    """Return the row for upsert_announcement, or raise InvalidPayload. Unknown keys are refused."""
    if not isinstance(obj, dict):
        raise InvalidPayload("body must be a JSON object")
    unknown = sorted(set(obj) - _FIELDS)
    if unknown:
        raise InvalidPayload(f"unknown field(s): {', '.join(unknown)}")
    missing = [k for k in _REQUIRED if k not in obj]
    if missing:
        raise InvalidPayload(f"missing field(s): {', '.join(missing)}")

    symbol = obj["symbol"]
    if not isinstance(symbol, str) or not symbol.strip():
        raise InvalidPayload("symbol must be a non-empty string")
    date = obj["date"]
    if not isinstance(date, str) or not _DATE.match(date):
        raise InvalidPayload("date must be YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise InvalidPayload("date is not a real calendar date") from exc
    time = obj.get("time")
    if time is not None:
        if not isinstance(time, str):
            raise InvalidPayload("time must be HH:MM:SS or null")
        try:
            datetime.strptime(time, "%H:%M:%S")
        except ValueError as exc:
            raise InvalidPayload("time must be HH:MM:SS or null") from exc
    title = obj["title"]
    if not isinstance(title, str):
        raise InvalidPayload("title must be a string (may be empty)")
    for key in ("category", "target_url"):
        if obj.get(key) is not None and not isinstance(obj[key], str):
            raise InvalidPayload(f"{key} must be a string or null")
    doc_id = obj.get("doc_id")
    if doc_id is not None and (not isinstance(doc_id, int) or isinstance(doc_id, bool) or doc_id < 1):
        raise InvalidPayload("doc_id must be a positive integer or null")
    if obj["track"] not in TRACKS:
        raise InvalidPayload(f"track must be one of {sorted(TRACKS)}")
    if obj["source"] not in SOURCES:
        raise InvalidPayload(f"source must be one of {sorted(SOURCES)}")

    return {
        "symbol": symbol.strip().upper(),
        "company_name": None,  # the runner does not send the company name
        "date": date,
        "time": time,
        "category": obj.get("category"),
        "title": title,
        "doc_id": doc_id,
        "track": obj["track"],
        "source": obj["source"],
        "target_url": obj.get("target_url"),
    }


def _authorised(header: str, token: str) -> bool:
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    supplied = header[len(prefix) :].strip().encode("utf-8")
    return hmac.compare_digest(supplied, token.encode("utf-8"))


def handle_request(
    *,
    method: str,
    path: str,
    authorization: str,
    content_type: str,
    body: bytes,
    token: str,
    open_db: Callable[[], Database],
) -> Response:
    """Pure request handling: returns (status, JSON body). The WSGI wrapper only moves bytes."""
    if path != PATH:
        return 404, {"error": "not found"}
    if method != "POST":
        return 405, {"error": "method not allowed"}
    if not token:
        return 503, {"error": "receiver token is not configured"}
    if not _authorised(authorization, token):
        return 401, {"error": "unauthorised"}
    if content_type.split(";")[0].strip().lower() != "application/json":
        return 415, {"error": "content type must be application/json"}
    if len(body) > MAX_BODY:
        return 413, {"error": "body too large"}
    try:
        row = validate_payload(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "body is not valid JSON"}
    except InvalidPayload as exc:
        return 400, {"error": str(exc)}

    try:
        db = open_db()
    except Exception:  # noqa: BLE001 - never leak connection details
        log.exception("receiver could not open the database")
        return 500, {"error": "storage unavailable"}
    try:
        already = exists(db, row)
        upsert_announcement(db, row)
    except Exception:  # noqa: BLE001 - the runner retries; detail stays in the server log
        log.exception("receiver failed to store an announcement")
        return 500, {"error": "storage unavailable"}
    finally:
        db.close()
    if already:
        return 200, {"status": "already_stored"}
    return 201, {"status": "stored"}


def make_app(open_db: Callable[[], Database], token: str | None) -> Callable:
    """A WSGI application bound to a database opener and a receiver token."""

    def app(environ, start_response):
        length = environ.get("CONTENT_LENGTH") or "0"
        try:
            wanted = min(int(length), MAX_BODY + 1)
        except ValueError:
            wanted = 0
        body = environ["wsgi.input"].read(wanted) if wanted > 0 else b""
        status, payload = handle_request(
            method=environ.get("REQUEST_METHOD", ""),
            path=environ.get("PATH_INFO", ""),
            authorization=environ.get("HTTP_AUTHORIZATION", ""),
            content_type=environ.get("CONTENT_TYPE", ""),
            body=body,
            token=token or "",
            open_db=open_db,
        )
        data = json.dumps(payload).encode("utf-8")
        reason = {
            200: "OK",
            201: "Created",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }[status]
        start_response(
            f"{status} {reason}", [("Content-Type", "application/json"), ("Content-Length", str(len(data)))]
        )
        return [data]

    return app


def application(environ, start_response):
    """Default WSGI entry point. Reads the token on every request, so a rotated token takes effect
    without a restart. Database access uses database.connection.connect() (PSXNI_TURSO_* variables)."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    return make_app(connect, token)(environ, start_response)
