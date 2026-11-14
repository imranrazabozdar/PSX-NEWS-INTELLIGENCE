"""End to end: an announcement is stored (migration 0015), its statement is reconciled from the real
manufacturing page (tests/fixtures/pucar/), and the normalised PKR figures are read back. No network access.

The announcement row is SYNTHETIC: it links a statement to a test symbol, and it is not a PSX notice.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.psx_announcements import find_announcement_id, upsert_announcement
from database.psx_financial_results import reconciliation_status
from engines.financial_reconciler import reconcile_announcement_statement
from engines.pucar_statement_parser import parse_pucar_text

FIXTURES = Path(__file__).parent / "fixtures" / "pucar"
REAL_MANUFACTURING = (FIXTURES / "real_manufacturing_unconsolidated_pl_pkr000_p39.txt").read_text("utf-8")
REAL_BANK = (FIXTURES / "real_bank_consolidated_pl_usd000_p49.txt").read_text("utf-8")
SYMBOL = "REALMFG"  # a test label for the real manufacturing page; the page does not name its company

ANNOUNCEMENT = {
    "symbol": SYMBOL,
    "company_name": None,
    "date": "2026-08-20",
    "time": "10:00:00",
    "category": "Financial Results",
    "title": "SYNTHETIC LINK ROW: financial results",
    "doc_id": None,
    "track": "flash",
    "source": "unresolved",
    "target_url": None,
}


@pytest.fixture
def dbpath(tmp_path):
    path = str(tmp_path / "recon.sqlite3")
    database = SQLiteDatabase(path)
    migrate(database)
    database.close()
    return path


def _open(path):
    return SQLiteDatabase(path)


def _announcement(path):
    db = _open(path)
    try:
        upsert_announcement(db, ANNOUNCEMENT)
        return find_announcement_id(db, ANNOUNCEMENT)
    finally:
        db.close()


def _reconcile(path, announcement_id, text, symbol=SYMBOL):
    db = _open(path)
    try:
        return reconcile_announcement_statement(announcement_id, text, symbol, db)
    finally:
        db.close()


def _results(path, symbol=SYMBOL):
    db = _open(path)
    try:
        return [dict(r) for r in db.execute("SELECT * FROM psx_financial_results WHERE symbol = ?", [symbol])]
    finally:
        db.close()


def _status(path, announcement_id):
    db = _open(path)
    try:
        return reconciliation_status(db, announcement_id)
    finally:
        db.close()


def test_real_manufacturing_statement_reconciles_to_exact_pkr_figures(dbpath):
    aid = _announcement(dbpath)
    assert aid is not None

    outcome = _reconcile(dbpath, aid, REAL_MANUFACTURING)
    assert outcome.status == "reconciled" and outcome.changed is True

    rows = _results(dbpath)
    assert len(rows) == 1
    row = rows[0]
    assert row["turnover_pkr"] == 136527017000.0  # 136,527,017 PKR thousand
    assert row["profit_after_tax_pkr"] == 46629367000.0
    assert row["cost_of_sales_pkr"] == -85356494000.0
    assert row["gross_profit_pkr"] == 51170523000.0
    assert row["profit_before_tax_pkr"] == 60541979000.0
    assert row["eps"] == 31.83  # per share: not scaled
    assert row["dividend_pkr"] is None  # no dividend printed: absent, not zero
    assert row["scale"] == 1000 and row["currency"] == "PKR"
    assert row["period_ended"] == "2026-06-30" and row["period_type"] == "annual"
    assert isinstance(json.loads(row["warnings"]), list)

    status = _status(dbpath, aid)
    assert status["status"] == "reconciled"
    assert status["result_id"] == outcome.result_id == row["id"]


def test_replaying_the_same_statement_changes_nothing(dbpath):
    aid = _announcement(dbpath)
    _reconcile(dbpath, aid, REAL_MANUFACTURING)
    before = _results(dbpath)
    status_before = _status(dbpath, aid)

    replay = _reconcile(dbpath, aid, REAL_MANUFACTURING)
    assert replay.status == "reconciled" and replay.changed is False
    assert _results(dbpath) == before  # same row, same values, same created_at
    assert _status(dbpath, aid)["result_id"] == status_before["result_id"]


def test_a_changed_figure_is_refreshed_and_reported(dbpath):
    aid = _announcement(dbpath)
    _reconcile(dbpath, aid, REAL_MANUFACTURING)
    revised = REAL_MANUFACTURING.replace("46,629,367", "46,629,368")
    outcome = _reconcile(dbpath, aid, revised)
    assert outcome.changed is True
    assert _results(dbpath)[0]["profit_after_tax_pkr"] == 46629368000.0
    assert len(_results(dbpath)) == 1


def test_a_weaker_reparse_does_not_erase_stored_figures(dbpath):
    aid = _announcement(dbpath)
    _reconcile(dbpath, aid, REAL_MANUFACTURING)
    thinner = "For the year ended June 30, 2026\nRupees in '000\nProfit after taxation    1,000    900\n"
    _reconcile(dbpath, aid, thinner)
    row = _results(dbpath)[0]
    assert row["turnover_pkr"] == 136527017000.0  # not found in the thinner text, kept
    assert row["profit_after_tax_pkr"] == 1000000.0  # the newer printed figure is used


def test_a_statement_without_figures_is_recorded_and_stores_nothing(dbpath):
    aid = _announcement(dbpath)
    outcome = _reconcile(dbpath, aid, "SYNTHETIC: a notice with no financial figures at all.\n")
    assert outcome.status == "no_figures" and outcome.result_id is None
    assert _results(dbpath) == []
    assert _status(dbpath, aid)["status"] == "no_figures"


def test_a_dollar_statement_is_stored_without_pkr_figures(dbpath):
    aid = _announcement(dbpath)
    outcome = _reconcile(dbpath, aid, REAL_BANK, symbol="REALBNK")
    assert outcome.status == "reconciled"
    row = _results(dbpath, symbol="REALBNK")[0]
    assert row["currency"] == "USD"
    assert row["turnover_pkr"] is None and row["profit_after_tax_pkr"] is None
    assert row["eps"] == 0.19


def test_the_same_statement_for_two_symbols_is_stored_twice(dbpath):
    aid = _announcement(dbpath)
    _reconcile(dbpath, aid, REAL_MANUFACTURING, symbol="SYMA")
    _reconcile(dbpath, aid, REAL_MANUFACTURING, symbol="SYMB")
    assert len(_results(dbpath, symbol="SYMA")) == 1 and len(_results(dbpath, symbol="SYMB")) == 1


def test_an_unknown_announcement_is_refused(dbpath):
    db = _open(dbpath)
    try:
        with pytest.raises(ValueError, match="not stored"):
            reconcile_announcement_statement(999999, REAL_MANUFACTURING, SYMBOL, db)
    finally:
        db.close()


def test_the_parsed_statement_matches_the_fixture_expectations():
    r = parse_pucar_text(REAL_MANUFACTURING, SYMBOL)
    assert r.pat_pkr == 46629367000.0 and r.turnover_pkr == 136527017000.0
    assert r.period_ended == date(2026, 6, 30)
