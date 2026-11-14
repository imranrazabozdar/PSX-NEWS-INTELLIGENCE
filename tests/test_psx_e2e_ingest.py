"""End-to-end: a real announceWithSymbol.lis row -> parser -> router -> runner payload -> WSGI receiver ->
a temporary SQLite database migrated with the repository set through 0015. No network access.

The receiver opens and closes a connection per request, as production's connect() does, so the test
hands it a fresh connection each time and reads the results through separate connections.
"""

import io
import json
from datetime import date, time

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.psx_announcements import count_announcements
from engines import document_router as dr
from engines.psx_feed_parser import parse_announcements
from engines.termux_node_runner import build_payload
from services import psx_announcement_receiver as rx

# A real row copied verbatim from announceWithSymbol.lis (the supplied export, 205,970 rows).
REAL_ROW = "OLPL|OLP Financial|29Jan2001|12:36:34|FINANCIAL RESULTS FOR THE HALF YEAR ENDED 31/12/2000|"
TOKEN = "test-ingest-token"  # noqa: S105 - test fixture


@pytest.fixture
def dbpath(tmp_path):
    """A temporary database migrated with 0001 through 0015. The runner requires contiguous versions
    from 1, so 0015 is applied on top of the earlier repository migrations."""
    path = str(tmp_path / "ingest.sqlite3")
    database = SQLiteDatabase(path)
    migrate(database)
    database.close()
    return path


def _opener(path):
    return lambda: SQLiteDatabase(path)


def _count(path):
    database = SQLiteDatabase(path)
    try:
        return count_announcements(database)
    finally:
        database.close()


def _rows(path, symbol):
    database = SQLiteDatabase(path)
    try:
        return [
            dict(r) for r in database.execute("SELECT * FROM psx_announcements WHERE symbol = ?", [symbol])
        ]
    finally:
        database.close()


def _post(app, body: bytes, token: str = TOKEN, path: str = rx.PATH, method: str = "POST"):
    seen = {}

    def start_response(status, headers):
        seen["status"] = int(status.split()[0])

    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    if token is not None:
        env["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    out = json.loads(b"".join(app(env, start_response)))
    return seen["status"], out


def test_real_row_is_routed_stored_with_correct_fields_and_replay_is_a_noop(dbpath):
    ann = parse_announcements(REAL_ROW)[0]
    assert ann.symbol == "OLPL"
    assert ann.date == date(2001, 1, 29) and ann.time == time(12, 36, 34)
    assert ann.doc_id is None  # the export carries no document id

    decision = dr.route(ann, ir_registry={}, mirror_resolver=None)
    assert decision.track is dr.Track.FLASH
    assert decision.url is None  # no feed id and no mirror: no link is invented

    body = json.dumps(build_payload(decision, ann)).encode("utf-8")
    app = rx.make_app(_opener(dbpath), TOKEN)

    status, out = _post(app, body)
    assert status == 201 and out == {"status": "stored"}
    rows = _rows(dbpath, "OLPL")
    assert len(rows) == 1
    stored = rows[0]
    assert stored["track"] == "flash"
    assert stored["source"] == "unresolved"
    assert stored["category"] == "Financial Results"
    assert stored["date"] == "2001-01-29" and stored["time"] == "12:36:34"
    assert stored["title"] == "FINANCIAL RESULTS FOR THE HALF YEAR ENDED 31/12/2000"
    assert stored["doc_id"] is None and stored["target_url"] is None

    # Replay the exact same record: a clean, conflict-free no-op.
    status2, out2 = _post(app, body)
    assert status2 == 200 and out2 == {"status": "already_stored"}
    assert _count(dbpath) == 1
    assert _rows(dbpath, "OLPL") == [stored]  # nothing changed, including ingested_at


def test_wrong_token_is_refused_and_writes_nothing(dbpath):
    ann = parse_announcements(REAL_ROW)[0]
    body = json.dumps(build_payload(dr.route(ann, ir_registry={}), ann)).encode("utf-8")
    status, out = _post(rx.make_app(_opener(dbpath), TOKEN), body, token="wrong")  # noqa: S106
    assert status == 401 and out == {"error": "unauthorised"}
    assert _count(dbpath) == 0


def test_receiver_without_a_configured_token_fails_closed(dbpath):
    status, _ = _post(rx.make_app(_opener(dbpath), None), b"{}")
    assert status == 503
    assert _count(dbpath) == 0


def test_invalid_payloads_are_refused_without_writing(dbpath):
    app = rx.make_app(_opener(dbpath), TOKEN)
    bad_bodies = (
        b"not json",
        b"[]",
        json.dumps(
            {"symbol": "OLPL", "date": "2001-02-30", "title": "x", "track": "flash", "source": "unresolved"}
        ).encode(),  # not a real calendar date
        json.dumps(
            {"symbol": "OLPL", "date": "2001-01-29", "title": "x", "track": "other", "source": "unresolved"}
        ).encode(),  # unknown track
        json.dumps(
            {
                "symbol": "OLPL",
                "date": "2001-01-29",
                "title": "x",
                "track": "flash",
                "source": "unresolved",
                "extra": 1,
            }
        ).encode(),  # unknown field
        json.dumps(
            {
                "symbol": "OLPL",
                "date": "2001-01-29",
                "title": "x",
                "track": "flash",
                "source": "exchange_edge",
                "doc_id": True,
            }
        ).encode(),  # a bool is not an id
    )
    for bad in bad_bodies:
        status, _ = _post(app, bad)
        assert status == 400, bad
    assert _count(dbpath) == 0


def test_wrong_path_method_and_oversized_body_are_refused(dbpath):
    app = rx.make_app(_opener(dbpath), TOKEN)
    assert _post(app, b"{}", path="/elsewhere")[0] == 404
    assert _post(app, b"{}", method="GET")[0] == 405
    assert _post(app, b"{" + b" " * (rx.MAX_BODY + 10) + b"}")[0] == 413
    assert _count(dbpath) == 0


def test_empty_feed_title_round_trips_and_dedups(dbpath):
    app = rx.make_app(_opener(dbpath), TOKEN)
    payload = {
        "symbol": "ABC",
        "date": "2001-01-29",
        "time": None,
        "category": None,
        "title": "",
        "doc_id": None,
        "track": "flash",
        "source": "unresolved",
        "target_url": None,
    }
    body = json.dumps(payload).encode()
    assert _post(app, body)[0] == 201
    assert _post(app, body)[0] == 200
    assert _count(dbpath) == 1
