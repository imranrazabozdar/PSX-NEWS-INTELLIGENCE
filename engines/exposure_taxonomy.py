"""Exposure taxonomy and controlled vocabularies (Phase 4).

Six categories with defined subtypes. Each subtype has a one-line definition used in
explanations and documentation (docs/EXPOSURE_MAPPING.md). Directions use the existing
``event_companies.impact_direction`` vocabulary; the owner-facing label UNCERTAIN maps to
``unknown`` through DIRECTION_LOOKUP. ``neutral`` (evidence says no material effect) and
``unknown`` (direction cannot be determined from evidence) are distinct.
"""

from __future__ import annotations

TAXONOMY: dict[str, dict[str, str]] = {
    "operational": {
        "production_facilities": "Location, capacity or continuity of the company's plants or operations.",
        "raw_material_procurement": "Availability or cost of raw materials the company buys.",
        "imported_inputs": "Inputs the company imports, exposed to prices, duties and supply abroad.",
        "export_markets": "Markets the company sells into abroad.",
        "supply_chain": "Suppliers, contractors and upstream dependencies.",
        "distribution": "Distribution networks and retail channels.",
        "energy_consumption": "Fuel, gas or electricity the company consumes in operations.",
        "logistics": "Transport, ports and freight the company relies on.",
    },
    "financial": {
        "fx_debt": "Borrowings denominated in foreign currency.",
        "imported_machinery": "Capital equipment bought abroad.",
        "fx_revenue": "Revenue earned in or linked to foreign currency.",
        "interest_rate_sensitivity": "Income or costs that move with interest rates.",
        "working_capital": "Inventory, receivables and payables funding needs.",
        "borrowing_costs": "Cost of the company's local-currency debt.",
        "commodity_linked_costs": "Costs contractually or practically linked to commodity prices.",
        "government_receivables": "Amounts owed by or to government or state entities (e.g. circular debt).",
    },
    "regulatory": {
        "government_notification": "A government notification that names the company's activity.",
        "taxes_duties": "Taxes, duties or levies on the company's products, inputs or income.",
        "subsidies": "Subsidies the company receives or competes against.",
        "tariffs": "Regulated tariffs the company charges or pays.",
        "price_controls": "Regulated prices for the company's products.",
        "regulator_decision": "Decisions of OGRA, NEPRA, SBP, SECP or other regulators.",
        "trade_restrictions": "Domestic import or export restrictions affecting the company.",
        "environmental_industrial": "Environmental or industrial regulation.",
    },
    "macroeconomic": {
        "pkr_exchange_rate": "PKR depreciation or appreciation.",
        "inflation": "General price level changes.",
        "interest_rates": "Policy and market interest rates.",
        "oil_gas_prices": "Crude oil, refined product and natural gas prices.",
        "lng_lpg_prices": "LNG and LPG prices.",
        "electricity_tariffs": "Electricity prices paid or received.",
        "fiscal_policy": "Government budget, taxation and spending policy.",
        "imf_programme": "IMF programme conditions and reviews.",
        "government_spending": "Public development and other spending.",
        "demand_growth": "Economic growth and aggregate demand.",
    },
    "geopolitical": {
        "regional_conflict": "Armed conflict or tension affecting the region.",
        "border_closure": "Closure of borders or crossings.",
        "shipping_disruption": "Disruption of shipping routes or chokepoints.",
        "sanctions": "Sanctions on countries, entities or goods.",
        "external_trade_restrictions": "Trade restrictions imposed by other countries.",
        "maritime_risk": "Maritime security risk.",
        "insurance_freight": "Insurance and freight cost changes.",
        "international_supply_disruption": "Disruption of international supply of goods or energy.",
    },
    "sector": {
        "sector_development": "Developments affecting the whole sector.",
        "competitor_development": "A competitor's action or event.",
        "substitution": "Substitution between products or fuels.",
        "market_share": "Changes in market share.",
        "industry_capacity": "Industry capacity additions or closures.",
        "demand_shift": "Shifts in demand for the sector's products.",
    },
}

CATEGORIES = tuple(TAXONOMY)
DIRECTIONS = ("positive", "negative", "mixed", "neutral", "unknown")
DIRECTION_LOOKUP = {"POSITIVE": "positive", "NEGATIVE": "negative", "MIXED": "mixed",
                    "NEUTRAL": "neutral", "UNCERTAIN": "unknown", "UNKNOWN": "unknown"}
EVIDENCE_STATUSES = ("confirmed", "strongly_supported", "potential", "unverified", "rejected")
LEVELS = ("direct", "indirect")


def to_direction(label: str) -> str:
    """Map an owner-facing label (POSITIVE/NEGATIVE/MIXED/UNCERTAIN/NEUTRAL) or a stored value."""
    if label in DIRECTIONS:
        return label
    try:
        return DIRECTION_LOOKUP[label.upper()]
    except KeyError as exc:
        raise ValueError(f"unknown exposure direction {label!r}") from exc


def is_valid(category: str, subtype: str) -> bool:
    return subtype in TAXONOMY.get(category, {})


def combine(signs: list[int]) -> str:
    """Combine per-evidence signs (+1, -1, 0 for neutral, None for unknown) into a direction."""
    known = [s for s in signs if s is not None]
    if not known or len(known) < len(signs):
        return "unknown" if not known else ("mixed" if len({s for s in known if s}) > 1 else "unknown")
    nonzero = {s for s in known if s}
    if not nonzero:
        return "neutral"
    if len(nonzero) > 1:
        return "mixed"
    return "positive" if nonzero.pop() > 0 else "negative"
