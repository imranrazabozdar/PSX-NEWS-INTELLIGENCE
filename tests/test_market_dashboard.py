from engines import market_dashboard as md


def test_rows_shape_radar_and_moves_and_missing_values_stay_blank():
    radar = [
        {
            "symbol": "MARI",
            "score": 52.0,
            "drivers": [
                {"kind": "announcement", "points": 25, "text": "big deal"},
                {"kind": "price", "points": 10, "text": "up"},
            ],
            "unknown": [],
        }
    ]
    r = md.radar_rows(radar)[0]
    assert r["Symbol"] == "MARI" and r["Main evidence"] == "big deal" and r["Unknown"] == ""
    moves = [
        {
            "symbol": "A",
            "day": "2026-11-16",
            "move": 5.1,
            "volume_x": None,
            "verdict": "no identified cause",
            "evidence": [],
        },
        {
            "symbol": "B",
            "day": "2026-11-16",
            "move": -4.0,
            "volume_x": 3.2,
            "verdict": "x",
            "evidence": [{"text": "e"}],
        },
    ]
    with_cause, none = md.explained(moves)
    assert [m["symbol"] for m in with_cause] == ["B"] and [m["symbol"] for m in none] == ["A"]
    assert md.move_rows(none)[0]["Volume x"] is None
    assert md.breadth_line(None) == "No price data."
    assert "3 up" in md.breadth_line({"symbols": 5, "up": 3, "down": 1, "flat": 1, "median": 0.5})


def _page():
    import app

    app._market_dashboard()


def test_the_dashboard_page_renders_from_a_seeded_library(monkeypatch):
    from types import SimpleNamespace

    from streamlit.testing.v1 import AppTest

    from engines import library_db
    from tests.test_company_brief import seeded

    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_DATABASE_URL", "libsql://psx-library-test.turso.io")
    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_AUTH_TOKEN", "x")
    monkeypatch.setattr(
        library_db, "get_library_readonly_connection", lambda *a, **k: SimpleNamespace(db=seeded())
    )
    import app

    app._dashboard_data.clear()
    at = AppTest.from_function(_page, default_timeout=60).run()
    assert not at.exception
    text = " ".join([m.value for m in at.markdown] + [c.value for c in at.caption]).lower()
    assert "not a buy or sell view" in text or "nothing here is a buy or sell view" in text
    assert [m.label for m in at.metric][:2] == ["Latest price day", "Latest news day"]


def test_the_readonly_client_sends_no_pragma_and_refuses_writes(monkeypatch):
    import pytest

    from database.connection import DatabaseError, TursoReadOnlyDatabase

    db = TursoReadOnlyDatabase("https://x.turso.io", "t")
    sent = []

    def fake_post(body):
        sent.append(body)
        return {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "result": {
                            "cols": [{"name": "n"}],
                            "rows": [[{"type": "integer", "value": "1"}]],
                        }
                    },
                },
                {"type": "ok"},
            ]
        }

    monkeypatch.setattr(db, "_post", fake_post)
    assert db.execute("SELECT 1 AS n")[0]["n"] == 1
    assert all("PRAGMA" not in str(r) for r in sent[0]["requests"])
    for bad in ("PRAGMA foreign_keys = ON", "INSERT INTO t VALUES (1)", "CREATE TABLE t (a)"):
        with pytest.raises(DatabaseError):
            db.execute(bad)
