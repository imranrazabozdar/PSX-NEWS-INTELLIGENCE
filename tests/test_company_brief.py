"""The company brief: data assembly and the page. In-memory SQLite and SYNTHETIC rows only."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from database.connection import SQLiteDatabase
from engines import company_brief

LIB = Path(__file__).resolve().parents[1] / "database" / "library"
TODAY = date(2026, 11, 17)


def schema(db):
    for name in ("0002_research_fact.sql", "0009_news_rollup.sql", "0012_price_daily.sql"):
        body = "\n".join(ln.split("--", 1)[0] for ln in (LIB / name).read_text("utf-8").splitlines())
        for stmt in body.split(";"):
            if stmt.strip():
                db.execute(stmt)


def fact(db, company, topic, text, day, value=None, unit=None, period=None, source="synthetic"):
    db.execute(
        "INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name, source_url, "
        "source_date, as_of, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (company, topic, text, value, unit, period, source, None, day, day, "fact", "2026-11-17T00:00:00Z"),
    )


def seeded():
    db = SQLiteDatabase(":memory:")
    schema(db)
    first = TODAY - timedelta(days=26)
    for sym, last in (("AAA", 110.0), ("P1", 100.0), ("P2", 100.0), ("P3", 100.0), ("P4", 100.0)):
        for i in range(26):
            close = last if i == 25 else 100.0
            db.execute(
                "INSERT INTO price_daily VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    sym,
                    (first + timedelta(days=i)).isoformat(),
                    close,
                    close,
                    close,
                    close,
                    100.0,
                    "synthetic",
                    "x",
                ),
            )
        fact(db, sym, "profile.sector", "Sector: Test Sector", "2026-11-12")
    fact(
        db,
        "AAA",
        "results.quarterly",
        "Financial result, first quarter ended 2026-09-30 (consolidated): EPS 5.",
        "2026-11-15",
        5.0,
        "PKR/share",
        "first quarter ended 2026-09-30",
    )
    fact(
        db,
        "AAA",
        "results.quarterly",
        "Financial result, first quarter ended 2025-09-30 (consolidated): EPS 4.",
        "2025-11-15",
        4.0,
        "PKR/share",
        "first quarter ended 2025-09-30",
    )
    fact(db, "AAA", "technical.wyckoff", "AAA Wyckoff scan: score 80/100 (heuristic)", "2026-11-16", 80.0)
    fact(db, "AAA", "fundamentals.annual_p_e", "Annual P/E: 6.1", "2026-11-16", 6.1)
    db.execute(
        "INSERT INTO news_rollup VALUES (?,?,?,?,?,?,?)",
        ("2026-11-15", "AAA", 2, "{}", "AAA posts results", "http://x/y", "x"),
    )
    return db


def test_the_brief_holds_prices_moves_results_news_signals_and_fundamentals():
    db = seeded()
    ctx = company_brief.market_context(db, TODAY)
    b = company_brief.load(db, "aaa", TODAY, ctx)
    assert b["symbol"] == "AAA" and b["sector"] == "Test Sector"
    assert b["price"]["close"] == 110.0 and round(b["price"]["change_1d"], 1) == 10.0
    assert b["moves"] and b["moves"][0]["verdict"].startswith("evidence on file about this company")
    assert round(b["eps_change"]["pct"]) == 25
    assert b["news"][0]["top_title"] == "AAA posts results" and b["technical"] and b["fundamentals"]
    assert b["unknown"] == []


def test_a_symbol_without_prices_or_facts_says_what_is_missing_not_zero():
    db = seeded()
    b = company_brief.load(db, "ZZZ", TODAY, company_brief.market_context(db, TODAY))
    assert b["price"] is None and b["moves"] == [] and b["results"] == []
    for text in (
        "no facts on file",
        "no price series",
        "sector unknown",
        "no results on file",
        "no technical-engine signals",
        "no fundamentals snapshot",
    ):
        assert any(text in u for u in b["unknown"]), text


def _page_script():
    import app

    app._brief_page()


def test_the_page_renders_for_a_symbol_and_gives_no_advice(monkeypatch):
    db = seeded()
    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_DATABASE_URL", "libsql://psx-library-test.turso.io")
    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_AUTH_TOKEN", "x")
    from engines import library_db

    monkeypatch.setattr(library_db, "get_library_connection", lambda *a, **k: SimpleNamespace(db=db))
    import app

    app._brief_context.clear()
    app._brief_company.clear()
    at = AppTest.from_function(_page_script, default_timeout=30).run()
    assert not at.exception
    assert any("Pick one above" in m.value for m in at.markdown) or any(
        "Pick one above" in m.value for m in at.text
    )
    at.text_input[0].set_value("aaa").run()
    assert not at.exception
    page = " ".join([m.value for m in at.markdown] + [c.value for c in at.caption]).lower()
    assert "aaa" in page and "not proof of cause" in page
    content = " ".join(m.value for m in at.markdown).lower()  # the disclaimer caption names the words
    for word in ("buy ", "sell ", "stop loss"):
        assert word not in content
    assert any("What we do not know" in e.label for e in at.expander)
