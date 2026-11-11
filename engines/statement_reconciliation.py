"""Deterministic statement reconciliation. Pure functions: no database, no network, no number is ever changed.

Each check returns its exact discrepancy and one of four statuses:
  RECONCILED                exact match (discrepancy 0)
  RECONCILED_WITH_ROUNDING  discrepancy within the rounding allowance, not zero; the exact amount is kept
  UNRECONCILED              discrepancy beyond the allowance
  INSUFFICIENT_DATA         a needed value is missing: never treated as zero

Rounding allowance: `ROUNDING_UNITS` printed units (the statement's own unit, e.g. thousands) per identity
term.
A check whose inputs are not all reported is INSUFFICIENT_DATA.

Document status (`overall`): UNRECONCILED if any check is UNRECONCILED; otherwise INSUFFICIENT_DATA if no
check
could run; otherwise RECONCILED_WITH_ROUNDING if any check needed rounding; otherwise RECONCILED.
"""

from __future__ import annotations

from dataclasses import dataclass

RECONCILED = "RECONCILED"
ROUNDED = "RECONCILED_WITH_ROUNDING"
UNRECONCILED = "UNRECONCILED"
INSUFFICIENT = "INSUFFICIENT_DATA"
ROUNDING_UNITS = 1.0  # printed units per identity term (one printed unit of rounding per term)


@dataclass(frozen=True)
class Check:
    name: str
    column_period_end: str
    reported: float | None
    expected: float | None
    discrepancy: float | None
    allowance: float
    status: str
    missing: tuple[str, ...] = ()


def _allowance(terms: int) -> float:
    """Allowance in the PRINTED unit (the unit the statement is printed in, e.g. thousands). Values are
    compared in
    that unit; scaling to currency units happens only at promotion, never here."""
    return ROUNDING_UNITS * terms


def classify(reported: float, expected: float, allowance: float) -> tuple[float, str]:
    d = reported - expected
    if d == 0:
        return d, RECONCILED
    if abs(d) <= allowance:
        return d, ROUNDED
    return d, UNRECONCILED


def identity(
    name: str,
    period: str,
    total_name: str,
    parts: dict[str, float | None],
    formula,
    *,
    terms: int,
    values: dict[str, float | None],
) -> Check:
    """One identity: total == formula(parts). Missing inputs give INSUFFICIENT_DATA, never a zero."""
    missing = tuple(k for k in (total_name, *parts) if values.get(k) is None)
    if missing:
        return Check(name, period, values.get(total_name), None, None, 0.0, INSUFFICIENT, missing)
    expected = formula({k: values[k] for k in parts})
    allow = _allowance(terms)
    d, status = classify(values[total_name], expected, allow)
    return Check(name, period, values[total_name], expected, d, allow, status)


def balance_sheet(period: str, v: dict[str, float | None]) -> Check:
    """Assets = liabilities + equity. Liabilities are total liabilities as reported."""
    return identity(
        "balance_sheet",
        period,
        "total_assets",
        {"total_liabilities": None, "total_equity": None},
        lambda p: p["total_liabilities"] + p["total_equity"],
        terms=2,
        values=v,
    )


def equity_statement(period: str, closing_total: float | None, bs_total_equity: float | None) -> Check:
    """Cross-statement identity: the statement of changes in equity closes at the balance sheet's total
    equity."""
    return identity(
        "equity_statement",
        period,
        "equity_statement_closing",
        {"total_equity": None},
        lambda p: p["total_equity"],
        terms=2,
        values={"equity_statement_closing": closing_total, "total_equity": bs_total_equity},
    )


def cash_flow(period: str, v: dict[str, float | None]) -> Check:
    """Opening cash + net movement + effect of exchange rate changes on cash = closing cash. The FX line is
    printed separately in banking and multinational statements; when it is present it is part of the identity
    (leaving it out would report a real, printed amount as an unexplained difference)."""
    fx = v.get("fx_effect_on_cash")
    return identity(
        "cash_flow",
        period,
        "closing_cash",
        {"opening_cash": None, "net_change_in_cash": None},
        lambda p: p["opening_cash"] + p["net_change_in_cash"] + (fx or 0.0),
        terms=3 if fx is not None else 2,
        values=v,
    )


def income_statement(period: str, v: dict[str, float | None]) -> Check:
    """Profit before taxation less taxation = profit after taxation.

    The statements print tax either as a bracketed expense or as a plain figure, so the tax is taken as an
    expense of its printed size (its absolute value)."""
    return identity(
        "income_statement",
        period,
        "profit_after_tax",
        {"profit_before_tax": None, "taxation": None},
        lambda p: p["profit_before_tax"] - abs(p["taxation"]),
        terms=2,
        values=v,
    )


def oci_components(period: str, v: dict[str, float | None]) -> Check:
    """The printed other comprehensive income total equals the sum of its printed components."""
    return identity(
        "oci_components",
        period,
        "other_comprehensive_income",
        {"oci_components_total": None},
        lambda p: p["oci_components_total"],
        terms=5,
        values=v,
    )


def comprehensive_income(period: str, v: dict[str, float | None]) -> Check:
    """Total comprehensive income = profit after taxation + other comprehensive income (sum of its
    components)."""
    return identity(
        "comprehensive_income",
        period,
        "total_comprehensive_income",
        {"profit_after_tax": None, "other_comprehensive_income": None},
        lambda p: p["profit_after_tax"] + p["other_comprehensive_income"],
        terms=2,
        values=v,
    )


def comparatives(
    name: str, period: str, prior_reported: float | None, current_comparative: float | None
) -> Check:
    """The prior-period value as printed in the prior report must equal the comparative column of the next
    report.
    Two different printed amounts for the same period are a restatement or an error, and are flagged, not
    chosen."""
    if prior_reported is None or current_comparative is None:
        return Check(
            name,
            period,
            prior_reported,
            current_comparative,
            None,
            0.0,
            INSUFFICIENT,
            tuple(
                n
                for n, x in (("prior_reported", prior_reported), ("current_comparative", current_comparative))
                if x is None
            ),
        )
    allow = _allowance(1)
    d, status = classify(current_comparative, prior_reported, allow)
    return Check(name, period, current_comparative, prior_reported, d, allow, status)


def _status(c) -> str:
    return c["status"] if isinstance(c, dict) else c.status


def overall(checks: list) -> str:
    """Document status from checks given as Check objects or as dicts with a 'status' key. Callers that
    need to
    know whether every identity ran must check the individual statuses (the intake reports checks not run)."""
    statuses = [_status(c) for c in checks]
    if UNRECONCILED in statuses:
        return UNRECONCILED
    if not any(s in (RECONCILED, ROUNDED) for s in statuses):
        return INSUFFICIENT
    if ROUNDED in statuses:
        return ROUNDED
    return RECONCILED
