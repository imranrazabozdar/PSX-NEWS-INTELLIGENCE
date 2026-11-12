"""Repository layer for parsed PUCAR results and reconciliation status (migration 0016).

Idempotent. Re-storing the same statement changes nothing. A later parse of the same statement fills in
figures that were missing and overwrites figures that changed. A figure the later parse did not find keeps
its stored value, so a weaker re-parse cannot erase data.
"""

from __future__ import annotations

import json
from typing import Any

from database.connection import Database
from engines.pucar_statement_parser import PucarFinancialResult

_FIGURE_COLUMNS = (
    "currency",
    "turnover_pkr",
    "cost_of_sales_pkr",
    "gross_profit_pkr",
    "operating_profit_pkr",
    "profit_before_tax_pkr",
    "profit_after_tax_pkr",
    "eps",
    "dividend_pkr",
)
# A figure the new parse did not find (NULL) keeps the stored value; scale and warnings are replaced.
_VALUE_COLUMNS = (*_FIGURE_COLUMNS, "scale", "warnings")
_UPDATE_CLAUSE = ",\n".join(
    [f"    {c} = COALESCE(excluded.{c}, psx_financial_results.{c})" for c in _FIGURE_COLUMNS]
    + ["    scale = excluded.scale", "    warnings = excluded.warnings"]
)
UPSERT_SQL = (
    "INSERT INTO psx_financial_results\n"
    "    (symbol, period_ended, period_type, currency, turnover_pkr, cost_of_sales_pkr, gross_profit_pkr,\n"
    "     operating_profit_pkr, profit_before_tax_pkr, profit_after_tax_pkr, eps, dividend_pkr,"
    " scale, warnings)\n"
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n"
    "ON CONFLICT (symbol, COALESCE(period_ended, ''), COALESCE(period_type, '')) DO UPDATE SET\n"
    + _UPDATE_CLAUSE
)

STATUS_SQL = """
INSERT INTO psx_reconciliation_status (announcement_id, status, result_id, warnings, updated_at)
VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT (announcement_id) DO UPDATE SET
    status     = excluded.status,
    result_id  = excluded.result_id,
    warnings   = excluded.warnings,
    updated_at = excluded.updated_at
"""


def _values(result: PucarFinancialResult) -> dict[str, Any]:
    """The stored form of a result: the normalised PKR figures, the scale and the serialised warnings."""
    return {
        "currency": result.currency,
        "turnover_pkr": result.turnover_pkr,
        "cost_of_sales_pkr": result.cost_of_sales_pkr,
        "gross_profit_pkr": result.gross_profit_pkr,
        "operating_profit_pkr": result.operating_profit_pkr,
        "profit_before_tax_pkr": result.profit_before_tax_pkr,
        "profit_after_tax_pkr": result.profit_after_tax_pkr,
        "eps": result.eps,
        "dividend_pkr": result.dividend_pkr,
        "scale": result.scale,
        "warnings": json.dumps(list(result.warnings), ensure_ascii=False),
    }


def find_result_id(
    db: Database, symbol: str, period_ended: str | None, period_type: str | None
) -> int | None:
    found = db.execute(
        "SELECT id FROM psx_financial_results WHERE symbol = ? "
        "AND COALESCE(period_ended, '') = ? AND COALESCE(period_type, '') = ?",
        [symbol, period_ended or "", period_type or ""],
    )
    return int(found[0]["id"]) if found else None


def _stored(db: Database, result_id: int) -> dict[str, Any] | None:
    rows = db.execute("SELECT * FROM psx_financial_results WHERE id = ?", [result_id])
    return dict(rows[0]) if rows else None


def upsert_financial_result(db: Database, result: PucarFinancialResult) -> bool:
    """Store or refresh one parsed statement. Returns True when a row was created or its values changed."""
    period_ended = result.period_ended.isoformat() if result.period_ended else None
    before_id = find_result_id(db, result.symbol, period_ended, result.period_type)
    before = _stored(db, before_id) if before_id is not None else None
    values = _values(result)
    db.execute(
        UPSERT_SQL,
        [
            result.symbol,
            period_ended,
            result.period_type,
            values["currency"],
            values["turnover_pkr"],
            values["cost_of_sales_pkr"],
            values["gross_profit_pkr"],
            values["operating_profit_pkr"],
            values["profit_before_tax_pkr"],
            values["profit_after_tax_pkr"],
            values["eps"],
            values["dividend_pkr"],
            values["scale"],
            values["warnings"],
        ],
    )
    result_id = find_result_id(db, result.symbol, period_ended, result.period_type)
    if result_id is None:  # cannot happen after the upsert; fail loudly rather than report a false state
        raise RuntimeError("financial result was not stored")
    after = _stored(db, result_id)
    if before is None:
        return True
    return any(before[c] != after[c] for c in _VALUE_COLUMNS)


def upsert_reconciliation_status(
    db: Database, announcement_id: int, status: str, result_id: int | None, warnings: list[str]
) -> None:
    db.execute(
        STATUS_SQL, [announcement_id, status, result_id, json.dumps(list(warnings), ensure_ascii=False)]
    )


def reconciliation_status(db: Database, announcement_id: int) -> dict[str, Any] | None:
    rows = db.execute("SELECT * FROM psx_reconciliation_status WHERE announcement_id = ?", [announcement_id])
    return dict(rows[0]) if rows else None
