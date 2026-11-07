"""Versioned, deterministic exposure rules (Phase 4).

A rule links a *driver* detected in a verified event (for example "crude oil price up") to
the company-specific exposures recorded in ``company_exposures`` that the driver acts on. The
sign of the effect comes from the company's own documented exposure, never from its sector:

* a company that *buys* crude oil (exposure_kind ``input``) is exposed negatively to a rise;
* a company that *produces* crude oil (``product``) is exposed positively;
* evidence the rule cannot sign (for example bank lending versus a rate change) stays unknown.

No rule says "every OMC gains when oil rises" or "every exporter gains from depreciation". When a
company has no documented exposure, a rule may only list its PSX sector as a *sector-level
candidate*: direction unknown, evidence unverified, human review required.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULESET_VERSION = "exposure-rules/1.0.0"

_UP = re.compile(r"\b(rise|rises|rising|rose|increase[sd]?|hike[sd]?|raise[sd]?|surge[sd]?|jump(?:s|ed)?|"
                 r"higher|up|soar(?:s|ed)?|depreciat\w*|weaken\w*)\b", re.I)
_DOWN = re.compile(r"\b(fall|falls|falling|fell|decrease[sd]?|cut|cuts|reduce[sd]?|lower(?:ed)?|"
                   r"drop(?:s|ped)?|decline[sd]?|eas(?:e|ed|ing)|slump(?:s|ed)?|appreciat\w*|"
                   r"strengthen\w*)\b", re.I)


@dataclass(frozen=True)
class Link:
    """How a driver acts on one documented company exposure."""

    exposure_kinds: tuple[str, ...]
    subject_pattern: str            # regex matched against company_exposures.subject
    sign_if_up: int | None          # +1, -1, 0 (neutral) or None (cannot be signed)
    category: str
    subtype: str
    level: str
    mechanism: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    driver: str
    trigger: str                    # regex on headline, summary, claims and indicator names
    event_types: tuple[str, ...]
    links: tuple[Link, ...]
    sector_candidates: tuple[str, ...]   # PSX sector ids, used only when no company evidence exists
    sector_category: str
    sector_subtype: str


RULES: tuple[Rule, ...] = (
    Rule("R-OIL-1", "crude_oil_price", r"\b(crude|brent|wti|oil price)", (
        "commodity_price", "commodity_supply", "geopolitical", "energy_policy", "other"), (
        Link(("input",), r"crude|oil", -1, "operational", "raw_material_procurement", "direct",
             "buys crude oil or oil-linked inputs; a price rise raises input costs"),
        Link(("product",), r"crude|oil", +1, "macroeconomic", "oil_gas_prices", "direct",
             "sells crude oil or oil-linked products; realised prices move with oil"),
        Link(("energy", "logistics"), r"fuel|diesel|furnace oil|oil", -1, "operational", "energy_consumption",
             "indirect", "consumes fuel; a price rise raises operating costs"),
    ), ("psx-refinery", "psx-oil-gas-marketing-companies", "psx-oil-gas-exploration-companies"),
        "macroeconomic", "oil_gas_prices"),
    Rule("R-RATE-1", "policy_rate", r"\b(policy rate|interest rate|discount rate|monetary policy)", (
        "monetary_policy", "economic_indicator"), (
        Link(("debt",), r"floating|kibor|borrow|loan|debt", -1, "financial", "borrowing_costs", "direct",
             "has floating-rate borrowings; a rate rise raises finance costs"),
        Link(("product", "market"), r"lending|deposit|net interest|banking", None, "financial",
             "interest_rate_sensitivity", "direct",
             "earns net interest income; the effect depends on repricing and deposit costs, "
             "so it is not signed"),
    ), ("psx-commercial-banks",), "macroeconomic", "interest_rates"),
    Rule("R-PKR-1", "pkr_depreciation", r"\b(rupee|pkr|exchange rate)", (
        "economic_indicator", "monetary_policy", "imf_program", "other"), (
        Link(("market", "geography", "fx"), r"export|usd revenue|foreign currency revenue", +1, "financial",
             "fx_revenue", "direct", "earns revenue in foreign currency; depreciation raises its PKR value"),
        Link(("input",), r"import", -1, "operational", "imported_inputs", "direct",
             "imports inputs; depreciation raises their PKR cost"),
        Link(("debt", "fx"), r"foreign currency debt|usd debt|fx debt|foreign loan", -1, "financial",
             "fx_debt", "direct", "has foreign-currency debt; depreciation raises its PKR burden"),
    ), (), "macroeconomic", "pkr_exchange_rate"),
    Rule("R-GAS-1", "gas_price", r"\b(gas price|natural gas|rlng|lng price|gas tariff)", (
        "energy_policy", "regulatory_action", "commodity_price"), (
        Link(("input", "energy"), r"natural gas|rlng|gas", -1, "operational", "energy_consumption", "direct",
             "uses natural gas as feedstock or fuel; a price rise raises costs"),
        Link(("product",), r"natural gas|gas", +1, "macroeconomic", "oil_gas_prices", "direct",
             "produces natural gas; regulated or realised prices move with the change"),
    ), ("psx-fertilizer", "psx-power-generation-distribution"), "macroeconomic", "oil_gas_prices"),
    Rule("R-DUTY-1", "duty_or_tax_on_scope", r"\b(duty|tariff|tax|levy|sales tax|customs)", (
        "tax_policy", "trade_policy", "fiscal_policy", "regulatory_action"), (
        Link(("product",), r".+", -1, "regulatory", "taxes_duties", "direct",
             "a tax or duty applies to a product the company sells"),
        Link(("input",), r".+", -1, "regulatory", "taxes_duties", "direct",
             "a tax or duty applies to an input the company buys"),
    ), (), "regulatory", "taxes_duties"),
)


def event_text(event: dict) -> str:
    parts = [event.get("headline") or "", event.get("summary") or ""]
    parts += [c.get("claim", "") for c in event.get("claims", [])]
    parts += [i.get("name", "") for i in event.get("indicators", [])]
    return " ".join(parts)


def change_of(text: str, driver: str) -> int | None:
    """+1 if the text says the driver went up, -1 if down, None if unclear or contradictory."""
    up, down = bool(_UP.search(text)), bool(_DOWN.search(text))
    if driver == "pkr_depreciation":
        up = bool(re.search(r"\b(depreciat\w*|weaken\w*|falls?|fell|drops?|dropped|slump\w*)\b", text, re.I))
        down = bool(re.search(r"\b(appreciat\w*|strengthen\w*|gains?|gained)\b", text, re.I))
    if up == down:
        return None
    return 1 if up else -1


def matching_rules(event: dict) -> list[tuple[Rule, int | None]]:
    text = event_text(event)
    out = []
    for rule in RULES:
        if event.get("event_type") in rule.event_types and re.search(rule.trigger, text, re.I):
            out.append((rule, change_of(text, rule.driver)))
    return out


def scope_terms(event: dict) -> str:
    """Text a scope-limited rule (taxes, duties) must find the company's exposure subject in."""
    return event_text(event).casefold()
