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
    html = " ".join(m.value for m in at.markdown).lower()
    assert "prices to" in html and "market breadth" in html and "pi-card" in html
    assert [t.label for t in at.tabs][:3] == ["Technical setups", "Fundamental setups", "Fund + Tech setups"]


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


def test_cards_carry_every_driver_and_unexplained_moves_are_listed_by_size():
    radar = [
        {
            "symbol": "MARI",
            "score": 52.0,
            "drivers": [
                {"kind": "price", "points": 10, "text": "up", "date": "2026-11-16", "source": "bars"},
                {"kind": "announcement", "points": 25, "text": "big deal", "date": "d", "source": "I"},
            ],
            "unknown": ["no results on file"],
        }
    ]
    card = md.radar_cards(radar)[0]
    assert card["title"].startswith("1. MARI") and "big deal" in card["title"]
    assert len(card["lines"]) == 3 and card["lines"][0].startswith("**announcement**")
    moves = [
        {"symbol": "A", "day": "d", "move": 2.0, "volume_x": None, "verdict": "v", "evidence": []},
        {"symbol": "B", "day": "d", "move": -9.0, "volume_x": 2.0, "verdict": "v", "evidence": []},
    ]
    assert md.unexplained_lines(moves)[0].startswith("- **B**")
    assert md.move_cards(moves)[1]["title"].startswith("B -9.0% on d")


def test_html_is_escaped_and_colours_follow_the_sign():
    from engines import dashboard_html as ui

    movers = [
        {"symbol": "A<b>", "name": "X & Y", "close": 10.0, "move": 5.0, "volume": 2.5e6, "volume_x": 3.0},
        {"symbol": "B", "name": "", "close": 5.0, "move": -2.0, "volume": 900.0, "volume_x": None},
    ]
    html = ui.mover_rows(movers)
    assert "A&lt;b&gt;" in html and "X &amp; Y" in html and "<b>A<b>" not in html
    assert 'class="g"' in html and 'class="r"' in html and "2.50M" in html and "3.0x usual" in html
    b = {"symbols": 10, "up": 5, "down": 4, "flat": 1, "median": 0.1, "top_up": [("A", 9.0)], "top_down": []}
    assert "width:50.0%" in ui.breadth_card(b) and "5 advanced" in ui.breadth_card(b)
    assert md.order_movers(movers, "Losers")[0]["symbol"] == "B"
    assert md.order_movers(movers, "Most active")[0]["symbol"] == "A<b>"
