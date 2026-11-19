# ruff: noqa: E501
"""A structured starting point for indirect (sector) effects. Deterministic, no model, no claim of impact.

The seven-day council evaluation found that sector impact appeared in only 1 of 18 runs, and that a model asked
to invent relationships proposes many unsupported ones. This layer lists, for a macro or commodity story, the
sectors that are USUALLY exposed to the named driver and why. It never says an effect is positive or negative
for a company: the direction depends on the company's own exposure, which the analysts must establish from
evidence ("oil up" helps producers and hurts fuel importers). The council uses it as candidates to test, not as
conclusions. Each entry: the driver, the sector, and the mechanism in a sentence.
"""

from __future__ import annotations

import re
from typing import Any

# (trigger pattern, driver, [(sector, mechanism)])
RULES: tuple[tuple[re.Pattern[str], str, tuple[tuple[str, str], ...]], ...] = (
    (
        re.compile(r"\b(crude|brent|wti|oil prices?|oil (?:slips?|rises?|falls?|jumps?|climbs?))\b", re.I),
        "crude oil price",
        (
            ("exploration and production", "realised prices move with crude, subject to lags and pricing formulas"),
            ("refineries", "margins depend on product prices against crude cost and inventory timing"),
            ("oil marketing", "inventory gains or losses and working-capital needs follow price moves"),
            ("power generation", "fuel cost and its pass-through under tariff rules"),
            ("transport and autos", "fuel costs and demand"),
        ),
    ),
    (
        re.compile(r"\b(petrol|diesel|hsd|ogra)\b.*\b(price|rs\d|per litre)\b|\bprices?\b.*\b(petrol|diesel)\b", re.I),
        "domestic petrol and diesel prices",
        (
            ("oil marketing", "margins are regulated; inventory valuation follows the price change"),
            ("refineries", "pricing formula and deemed duty affect realisation"),
            ("transport and autos", "running costs and consumer demand"),
        ),
    ),
    (
        re.compile(r"\b(lng|gas (?:prices?|supply|supplies|shortage|tariff|curtailment)|sngp|ssgc)\b", re.I),
        "natural gas price or availability",
        (
            ("fertiliser", "feedstock and fuel gas supply and price"),
            ("power generation", "fuel availability for gas-fired plants"),
            ("textile and industrial users", "captive power and process gas costs"),
            ("gas utilities", "allocation, unaccounted-for gas and tariff determinations"),
        ),
    ),
    (
        re.compile(r"\b(policy rate|interest rate|kibor|monetary policy|sbp (?:holds?|cuts?|raises?|keeps?))\b", re.I),
        "interest rates",
        (
            ("banks", "net interest margin and the value of government securities"),
            ("leveraged industrials (cement, steel, autos)", "finance costs on borrowings"),
            ("consumer-financed sectors", "demand for loans and big-ticket purchases"),
        ),
    ),
    (
        re.compile(r"\b(rupee|pkr|exchange rate|dollar (?:peak|hits|gains?|strength)|devalu\w+)\b", re.I),
        "rupee exchange rate",
        (
            ("exporters (textile, leather)", "rupee revenue on dollar sales against local costs"),
            ("importers and import-dependent manufacturers", "landed cost of inputs"),
            ("companies with foreign-currency debt", "revaluation of liabilities and debt service"),
            ("oil marketing and refineries", "dollar-linked product prices"),
        ),
    ),
    (
        re.compile(r"\b(cement (?:despatches|dispatches|prices?|sales|exports?)|coal prices?)\b", re.I),
        "cement demand or coal cost",
        (
            ("cement", "volumes, prices and coal cost move margins"),
            ("construction and building materials", "infrastructure and housing demand"),
        ),
    ),
    (
        re.compile(r"\b(circular debt|power tariff|nepra|capacity payments?|ipps?)\b", re.I),
        "power-sector payments and tariffs",
        (
            ("power generation", "receivables and capacity payments"),
            ("banks", "lending exposure to the power chain"),
            ("exploration and production, oil marketing", "receivables from power producers"),
        ),
    ),
    (
        re.compile(r"\b(sales tax|federal excise|super tax|levy|duty|budget|finance bill|imf)\b", re.I),
        "tax and fiscal measures",
        (("the sector the measure names", "the measure's own scope decides who bears it; read the notification"),),
    ),
    (
        re.compile(r"\b(urea|dap|fertili[sz]er)\b", re.I),
        "fertiliser prices and offtake",
        (
            ("fertiliser", "volumes, prices, gas feedstock and subsidies"),
            ("agriculture-linked sectors", "input costs and farm incomes"),
        ),
    ),
)


def candidates(title: str) -> list[dict[str, Any]]:
    """Drivers named in the headline and the sectors usually exposed to them. Empty when none matches."""
    out: list[dict[str, Any]] = []
    for pattern, driver, sectors in RULES:
        if pattern.search(title):
            out.append(
                {
                    "driver": driver,
                    "sectors": [{"sector": s, "mechanism": m} for s, m in sectors],
                    "direction": "depends on each company's exposure; not asserted",
                }
            )
    return out
