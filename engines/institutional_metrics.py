"""Deterministic metrics from verified values. Pure functions: no database, no estimates, no guesses.

Every metric returns a dict {value, inputs, missing}. When an input is missing, value is None and `missing`
names
it. A missing input is NEVER treated as zero. Ratios are unit-independent, so values may be in any one
consistent
unit (the printed unit is fine); growth needs the prior period's value in the same unit.
"""

from __future__ import annotations

from collections.abc import Callable

DAYS = 365.0


def _get(v: dict[str, float | None] | None, keys: tuple[str, ...]) -> tuple[dict[str, float], list[str]]:
    vals, missing = {}, []
    for k in keys:
        x = (v or {}).get(k)
        if x is None:
            missing.append(k)
        else:
            vals[k] = float(x)
    return vals, missing


def _metric(
    name: str,
    keys: tuple[str, ...],
    v,
    fn: Callable[[dict[str, float]], float | None],
    prior: dict | None = None,
    prior_keys: tuple[str, ...] = (),
) -> dict:
    cur, miss = _get(v, keys)
    out = {"metric": name, "value": None, "inputs": cur, "missing": [f"current.{m}" for m in miss]}
    if prior_keys:
        prv, pmiss = _get(prior, prior_keys)
        out["inputs"] = {**cur, **{f"prior.{k}": x for k, x in prv.items()}}
        out["missing"] += [f"prior.{m}" for m in pmiss]
        if pmiss:
            return out
        cur = {**cur, **{f"prior.{k}": x for k, x in prv.items()}}
    if out["missing"]:
        return out
    out["value"] = fn(cur)
    return out


def gross_margin(v):
    return _metric(
        "gross_margin",
        ("gross_profit", "revenue"),
        v,
        lambda x: x["gross_profit"] / x["revenue"] if x["revenue"] else None,
    )


def operating_margin(v):
    return _metric(
        "operating_margin",
        ("operating_profit", "revenue"),
        v,
        lambda x: x["operating_profit"] / x["revenue"] if x["revenue"] else None,
    )


def revenue_growth(v, prior):
    return _metric(
        "revenue_growth",
        ("revenue",),
        v,
        lambda x: x["revenue"] / x["prior.revenue"] - 1 if x["prior.revenue"] else None,
        prior,
        ("revenue",),
    )


def receivables_growth(v, prior):
    return _metric(
        "receivables_growth",
        ("trade_receivables",),
        v,
        lambda x: (
            x["trade_receivables"] / x["prior.trade_receivables"] - 1
            if x["prior.trade_receivables"]
            else None
        ),
        prior,
        ("trade_receivables",),
    )


def receivables_vs_sales_growth(v, prior):
    """Receivables growth minus revenue growth. Positive means receivables are growing faster than sales."""
    rg = receivables_growth(v, prior)
    sg = revenue_growth(v, prior)
    if rg["value"] is None or sg["value"] is None:
        return {
            "metric": "receivables_vs_sales_growth",
            "value": None,
            "inputs": {},
            "missing": sorted(set(rg["missing"] + sg["missing"])),
        }
    return {
        "metric": "receivables_vs_sales_growth",
        "value": rg["value"] - sg["value"],
        "inputs": {**rg["inputs"], **sg["inputs"]},
        "missing": [],
    }


def collection_days(v):
    """Receivable collection period in days: trade receivables over revenue, times 365 (year-end basis).

    Uses closing receivables and the period's revenue, as printed. It is a ratio of reported values,
    not an estimate.
    """
    return _metric(
        "collection_days",
        ("trade_receivables", "revenue"),
        v,
        lambda x: DAYS * x["trade_receivables"] / x["revenue"] if x["revenue"] else None,
    )


def cash_conversion_cycle(v):
    """DSO + DIO - DPO in days. Needs receivables, inventory, payables, revenue and cost of sales."""
    keys = ("trade_receivables", "inventory", "trade_payables", "revenue", "cost_of_sales")
    return _metric(
        "cash_conversion_cycle",
        keys,
        v,
        lambda x: (
            (
                DAYS * x["trade_receivables"] / x["revenue"]
                + DAYS * x["inventory"] / abs(x["cost_of_sales"])
                - DAYS * x["trade_payables"] / abs(x["cost_of_sales"])
            )
            if x["revenue"] and x["cost_of_sales"]
            else None
        ),
    )


def ocf_to_net_income(v):
    """Operating cash flow over profit after tax. Below 1 means profit is not fully backed by cash."""
    return _metric(
        "ocf_to_net_income",
        ("cfo", "profit_after_tax"),
        v,
        lambda x: x["cfo"] / x["profit_after_tax"] if x["profit_after_tax"] > 0 else None,
    )


def accruals_ratio(v):
    """(profit after tax - operating cash flow) / total assets. Higher means lower earnings quality."""
    return _metric(
        "accruals_ratio",
        ("profit_after_tax", "cfo", "total_assets"),
        v,
        lambda x: (x["profit_after_tax"] - x["cfo"]) / x["total_assets"] if x["total_assets"] else None,
    )


def total_borrowings(v) -> tuple[float | None, list[str]]:
    """Long-term plus short-term borrowings. Both must be reported; a single missing part is not zero."""
    vals, missing = _get(v, ("long_term_borrowings", "short_term_borrowings"))
    if missing:
        return None, missing
    return vals["long_term_borrowings"] + vals["short_term_borrowings"], []


def debt_to_equity(v):
    debt, miss = total_borrowings(v)
    eq, emiss = _get(v, ("total_equity",))
    missing = [f"current.{m}" for m in miss] + [f"current.{m}" for m in emiss]
    if missing or debt is None:
        return {"metric": "debt_to_equity", "value": None, "inputs": {}, "missing": missing}
    return {
        "metric": "debt_to_equity",
        "value": debt / eq["total_equity"] if eq["total_equity"] else None,
        "inputs": {"total_borrowings": debt, "total_equity": eq["total_equity"]},
        "missing": [],
    }


def net_debt(v):
    debt, miss = total_borrowings(v)
    cash, cmiss = _get(v, ("cash_and_equivalents",))
    missing = [f"current.{m}" for m in miss + cmiss]
    if missing or debt is None:
        return {"metric": "net_debt", "value": None, "inputs": {}, "missing": missing}
    return {
        "metric": "net_debt",
        "value": debt - cash["cash_and_equivalents"],
        "inputs": {"total_borrowings": debt, "cash_and_equivalents": cash["cash_and_equivalents"]},
        "missing": [],
    }


def interest_coverage(v):
    return _metric(
        "interest_coverage",
        ("operating_profit", "finance_cost"),
        v,
        lambda x: x["operating_profit"] / abs(x["finance_cost"]) if x["finance_cost"] else None,
    )


def free_cash_flow(v):
    """Operating cash flow less capital expenditure (the purchase line, taken as an outflow)."""
    return _metric("free_cash_flow", ("cfo", "capex"), v, lambda x: x["cfo"] - abs(x["capex"]))


def all_metrics(v: dict, prior: dict | None = None) -> list[dict]:
    out = [
        gross_margin(v),
        operating_margin(v),
        cash_conversion_cycle(v),
        collection_days(v),
        ocf_to_net_income(v),
        accruals_ratio(v),
        debt_to_equity(v),
        net_debt(v),
        interest_coverage(v),
        free_cash_flow(v),
    ]
    if prior is not None:
        out += [revenue_growth(v, prior), receivables_growth(v, prior), receivables_vs_sales_growth(v, prior)]
    return out
