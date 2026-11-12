"""Core financial ratios, computed deterministically from extracted line items.

Rules
* Every input is a line item that was extracted and tagged (its line ID is recorded). A missing input is
never zero:
  the ratio is null and the reason says which input is missing.
* A denominator of zero, or a PAT that is not positive where PAT is the numerator of a yield-type ratio,
gives null
  with the reason.
* Frameworks are partitioned: corporate ratios are never computed for a bank report, and bank ratios never
for a
  corporate report.
* Each ratio carries its formula, input line IDs and a validation status. Nothing here changes an extracted
value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Ratio:
    key: str
    name: str
    formula: str
    inputs: tuple[str, ...]
    compute: Callable[[dict[str, float | None]], float | None]
    notes: str = ""
    requires_positive: tuple[str, ...] = ()  # inputs that must be > 0 for the ratio to be meaningful


def _div(a: float, b: float) -> float:
    return a / b


CORPORATE = (
    Ratio(
        "gross_margin",
        "Gross margin",
        "gross_profit / revenue",
        ("gross_profit", "revenue"),
        lambda v: _div(v["gross_profit"], v["revenue"]),
        "revenue is the printed net revenue",
    ),
    Ratio(
        "net_profit_margin",
        "Net profit margin",
        "profit_after_tax / revenue",
        ("profit_after_tax", "revenue"),
        lambda v: _div(v["profit_after_tax"], v["revenue"]),
    ),
    Ratio(
        "ocf_to_pat",
        "Operating cash flow to PAT",
        "cfo / profit_after_tax",
        ("cfo", "profit_after_tax"),
        lambda v: _div(v["cfo"], v["profit_after_tax"]),
        requires_positive=("profit_after_tax",),
    ),
    Ratio(
        "current_ratio",
        "Current ratio",
        "total_current_assets / total_current_liabilities",
        ("total_current_assets", "total_current_liabilities"),
        lambda v: _div(v["total_current_assets"], v["total_current_liabilities"]),
        "current subtotals are printed or inferred from their components and tie to the printed amount",
    ),
    Ratio(
        "trade_debt_days",
        "Trade debt days",
        "trade_receivables / revenue * 365",
        ("trade_receivables", "revenue"),
        lambda v: _div(v["trade_receivables"], v["revenue"]) * 365,
        "trade_receivables is the balance-sheet figure, i.e. NET of the doubtful-debt provision",
    ),
)

BANK = (
    Ratio(
        "cost_to_income",
        "Cost-to-income ratio",
        "non_markup_expenses / (net_interest_income + non_markup_income)",
        ("non_markup_expenses", "net_interest_income", "non_markup_income"),
        lambda v: _div(v["non_markup_expenses"], v["net_interest_income"] + v["non_markup_income"]),
        "net total income = net mark-up income + non-markup income (both printed)",
    ),
    Ratio(
        "adr",
        "Advances-to-deposits ratio",
        "advances_net / deposits",
        ("advances_net", "deposits"),
        lambda v: _div(v["advances_net"], v["deposits"]),
        "advances as printed (net of provisions)",
    ),
    Ratio(
        "roa",
        "Return on assets",
        "profit_after_tax / total_assets",
        ("profit_after_tax", "total_assets"),
        lambda v: _div(v["profit_after_tax"], v["total_assets"]),
        "period-end total assets; the report is a 12-month period, so no annualisation factor",
        requires_positive=(),
    ),
    Ratio(
        "roe",
        "Return on equity",
        "profit_after_tax / total_equity",
        ("profit_after_tax", "total_equity"),
        lambda v: _div(v["profit_after_tax"], v["total_equity"]),
        "period-end total equity; 12-month period, no annualisation factor",
    ),
)

FRAMEWORK_RATIOS = {"corporate": CORPORATE, "bank": BANK}


def _evaluate(r: Ratio, values: dict[str, float | None], line_ids: dict[str, list[str]]) -> dict:
    inputs = {k: {"value": values.get(k), "line_item_ids": line_ids.get(k, [])} for k in r.inputs}
    base = {"key": r.key, "name": r.name, "formula": r.formula, "inputs": inputs, "notes": r.notes}
    missing = [k for k in r.inputs if values.get(k) is None]
    if missing:
        return {
            **base,
            "value": None,
            "status": "NOT_COMPUTED",
            "validation": "MISSING_INPUT",
            "reason": f"missing input(s): {', '.join(missing)}",
        }
    if any(values[k] == 0 for k in r.inputs[1:]):
        return {
            **base,
            "value": None,
            "status": "NOT_COMPUTED",
            "validation": "ZERO_DENOMINATOR",
            "reason": "a denominator is zero",
        }
    bad = [k for k in r.requires_positive if values[k] <= 0]
    if bad:
        return {
            **base,
            "value": None,
            "status": "NOT_COMPUTED",
            "validation": "NOT_MEANINGFUL",
            "reason": f"{', '.join(bad)} is not positive",
        }
    return {
        **base,
        "value": round(r.compute(values), 6),
        "status": "COMPUTED",
        "validation": "VALID",
        "reason": None,
    }


def compute_ratios(
    framework: str, values: dict[str, float | None], line_ids: dict[str, list[str]] | None = None
) -> list[dict]:
    """The ratios for one framework. Nothing is computed for a framework that has no ratio set here."""
    specs = FRAMEWORK_RATIOS.get(framework, ())
    return [_evaluate(r, values, line_ids or {}) for r in specs]
