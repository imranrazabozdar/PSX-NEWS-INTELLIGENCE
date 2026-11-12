"""Reconciliation coordinator: a PUCAR statement attached to one announcement.

The coordinator has no I/O of its own. It parses the statement text, stores the result through the
repository layer, and records the status against the announcement.
"""

from __future__ import annotations

from dataclasses import dataclass

from database.connection import Database
from database.psx_financial_results import (
    find_result_id,
    upsert_financial_result,
    upsert_reconciliation_status,
)
from engines.pucar_statement_parser import parse_pucar_text

FIGURE_FIELDS = (
    "turnover",
    "cost_of_sales",
    "gross_profit",
    "operating_profit",
    "profit_before_tax",
    "profit_after_tax",
    "eps",
    "dividend_pkr",
)


@dataclass(frozen=True)
class ReconciliationOutcome:
    announcement_id: int
    status: str  # "reconciled" or "no_figures"
    result_id: int | None
    changed: bool  # True when a stored result was created or its values changed


def reconcile_announcement_statement(
    announcement_id: int, raw_text: str, symbol: str, conn: Database
) -> ReconciliationOutcome:
    """Parse one statement, store it, and record the reconciliation status for the announcement."""
    known = conn.execute(
        "SELECT 1 AS hit FROM psx_announcements WHERE announcement_id = ?", [announcement_id]
    )
    if not known:
        raise ValueError(f"announcement {announcement_id} is not stored")
    result = parse_pucar_text(raw_text, symbol)
    if all(getattr(result, field) is None for field in FIGURE_FIELDS):
        upsert_reconciliation_status(conn, announcement_id, "no_figures", None, list(result.warnings))
        return ReconciliationOutcome(announcement_id, "no_figures", None, changed=False)
    changed = upsert_financial_result(conn, result)
    period_ended = result.period_ended.isoformat() if result.period_ended else None
    result_id = find_result_id(conn, result.symbol, period_ended, result.period_type)
    upsert_reconciliation_status(conn, announcement_id, "reconciled", result_id, list(result.warnings))
    return ReconciliationOutcome(announcement_id, "reconciled", result_id, changed)
