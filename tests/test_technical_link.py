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


def test_data_is_refused_until_the_owner_allowlists_it():
    with pytest.raises(tl.NotAllowed):
        make().select_from("wyckoff_scan", "SELECT * FROM wyckoff_scan")
    rows = make(frozenset({"wyckoff_scan"})).select_from("wyckoff_scan", "SELECT symbol FROM wyckoff_scan")
    assert rows[0]["symbol"] == "ABC"
    assert tl.ALLOWED_OBJECTS == frozenset()


def test_unsafe_names_refused():
    with pytest.raises(tl.NotAllowed):
        make().columns("x); DROP TABLE y;--")


def test_library_host_is_refused_and_both_vars_needed():
    with pytest.raises(tl.LinkError):
        tl.check_target("libsql://psx-library-turso202601.aws-us-east-1.turso.io")
    assert tl.check_target("libsql://psx-intelligence-v2-abc.turso.io") == "psx-intelligence-v2-abc.turso.io"
    with pytest.raises(tl.LinkError):
        tl.connect({tl.URL_VAR: "libsql://x.turso.io"})
