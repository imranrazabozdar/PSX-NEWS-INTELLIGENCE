"""Dashboard pages for M2-M9 render honestly: 'awaiting migration' without tables, real tables with data.

In-memory SQLite and SYNTHETIC fixtures only.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _missing_tables_script():
    from database.connection import SQLiteDatabase
    from engines import research_views as rv

    db = SQLiteDatabase()  # no migrations: like production before 0011-0014 are approved
    for view in (rv.financials_view, rv.fundamentals_view, rv.valuation_view, rv.market_behaviour_view,
                 rv.macro_view, rv.integrated_report_view):
        view(db)


def _data_script():
    from database.connection import SQLiteDatabase
    from database.migrate import migrate
    from database.seed_loader import load
    from engines import financials as fin
    from engines import macro
    from engines import research_views as rv
    from tests.test_m2_m3_financials import _corp

    db = SQLiteDatabase()
    migrate(db)
    load(db)
    fin.load_mappings(db)
    macro.load_registry(db)
    older = _corp(period="2024-06-30", prev="2023-06-30", sha="b" * 64, filed_at_utc="2025-09-30T00:00:00Z")
    for rec in (older, _corp(filed_at_utc="2026-09-30T00:00:00Z")):
        r = fin.import_report(db, rec, importer="test", rights_attestation="synthetic")
        fin.promote(db, r["report_id"])
    import streamlit as st
    st.session_state.setdefault("fin_company", "cmp-ogdc")
    for k in ("fu_company", "va_company", "mi_company", "rep_company"):
        st.session_state.setdefault(k, "cmp-ogdc")
    for view in (rv.financials_view, rv.fundamentals_view, rv.valuation_view, rv.market_behaviour_view,
                 rv.macro_view, rv.integrated_report_view):
        view(db)
    before = db.execute("SELECT extraction_status FROM financial_reports ORDER BY report_id")
    st.session_state["statuses"] = [r["extraction_status"] for r in before]


def test_pages_say_awaiting_migration_without_tables():
    at = AppTest.from_function(_missing_tables_script, default_timeout=30).run()
    assert not at.exception
    warnings = [w.value for w in at.warning]
    assert len(warnings) == 6 and all("Awaiting migration" in w for w in warnings)


def test_pages_render_with_data_and_do_not_write():
    at = AppTest.from_function(_data_script, default_timeout=60).run()
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 6
    assert at.session_state["statuses"] == ["reconciled", "reconciled"]
    texts = " ".join(c.value for c in at.caption)
    assert "fiscal year(s) filed by" in texts and "needs the prior year" in texts
    assert "not evidence about fundamentals" in texts
    assert any("filed by then" in t.label for t in at.text_input)
    assert not any("Awaiting migration" in w.value for w in at.warning)
