import pytest

from database.connection import SQLiteDatabase
from engines import technical_link as tl


def make(allowed=frozenset()):
    db = SQLiteDatabase(":memory:")
    db.execute("CREATE TABLE wyckoff_scan (symbol TEXT, scan_date TEXT, score REAL, "
               "PRIMARY KEY(symbol, scan_date))")
    db.execute("INSERT INTO wyckoff_scan VALUES ('ABC','2026-11-16',50)")
    return tl.TechnicalLink(db=db, host="other.turso.io", allowed=allowed)


def test_discovery_lists_names_not_data():
    link = make()
    assert link.tables() == [("wyckoff_scan", "table")]
    assert [c["name"] for c in link.columns("wyckoff_scan")] == ["symbol", "scan_date", "score"]


def test_writes_are_refused():
    link = make()
    for sql in ("INSERT INTO wyckoff_scan VALUES ('X','d',1)", "DELETE FROM wyckoff_scan",
                "DROP TABLE wyckoff_scan"):
        with pytest.raises(tl.ReadOnlyViolation):
            link._select(sql)
    assert link.db.execute("SELECT COUNT(*) AS n FROM wyckoff_scan")[0]["n"] == 1


def test_data_is_refused_outside_the_allowlist():
    with pytest.raises(tl.NotAllowed):
        make().select_from("predictions", "SELECT * FROM predictions")
    rows = make(frozenset({"wyckoff_scan"})).select_from("wyckoff_scan", "SELECT symbol FROM wyckoff_scan")
    assert rows[0]["symbol"] == "ABC"
    assert "daily_ohlc" in tl.ALLOWED_OBJECTS
    for banned in ("predictions", "runs", "dss_history", "news", "analysis_cache", "intraday_bars"):
        assert banned not in tl.ALLOWED_OBJECTS


def test_unsafe_names_refused():
    with pytest.raises(tl.NotAllowed):
        make().columns("x); DROP TABLE y;--")


def test_library_host_is_refused_and_both_vars_needed():
    with pytest.raises(tl.LinkError):
        tl.check_target("libsql://psx-library-turso202601.aws-us-east-1.turso.io")
    assert tl.check_target("libsql://psx-intelligence-v2-abc.turso.io") == "psx-intelligence-v2-abc.turso.io"
    with pytest.raises(tl.LinkError):
        tl.connect({tl.URL_VAR: "libsql://x.turso.io"})


def test_the_client_sends_no_pragma_and_no_write(monkeypatch):
    sent = []

    def fake_send(self, body):
        sent.append(body)
        return {"results": [{"type": "ok", "response": {"result": {
            "cols": [{"name": "name"}], "rows": [[{"type": "text", "value": "t"}]]}}}, {"type": "ok"}]}

    monkeypatch.setattr(tl.ReadOnlyTurso, "_send", fake_send)
    db = tl.ReadOnlyTurso("libsql://other.turso.io", "tok")
    assert db.execute("SELECT name FROM sqlite_master")[0]["name"] == "t"
    sqls = [r["stmt"]["sql"] for r in sent[0]["requests"] if r["type"] == "execute"]
    assert sqls == ["SELECT name FROM sqlite_master"]
    with pytest.raises(tl.ReadOnlyViolation):
        db.execute("DELETE FROM x")
