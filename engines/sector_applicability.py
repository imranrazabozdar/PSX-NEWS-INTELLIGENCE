"""Sector applicability matrix for ratios (M3 multi-sector architecture).

A ratio is calculated only when its sector applicability allows it AND its inputs are present. Classes:

* applicable: meaningful for the sector; calculated when the inputs are present.
* conditional: meaningful only when a stated condition holds (for example the item is reported or material).
* not_applicable: the ratio has no economic meaning for the sector; it is never calculated.
* insufficient_data: the sector is applicable but the required inputs are not reported.

The matrix is a judgement encoded as data. It is not a claim that any sector has been validated on real
documents; see docs/MASTER_VALIDATION_STRATEGY.md for the validation status of each sector.
"""

from __future__ import annotations

from dataclasses import dataclass

# PSX sector labels, exactly as stored in database/seed/companies.json (psx_sector)
SECTORS = {
    "COMMERCIAL BANKS": "bank",
    "INSURANCE": "insurer",
    "OIL & GAS EXPLORATION COMPANIES": "corporate",
    "OIL & GAS MARKETING COMPANIES": "corporate",
    "POWER GENERATION & DISTRIBUTION": "corporate",
    "CEMENT": "corporate",
    "TECHNOLOGY & COMMUNICATION": "corporate",
    "FERTILIZER": "corporate",
    "TEXTILE COMPOSITE": "corporate",
}
# Sectors with no company in the current seed: their rules are specified, not validated.
SECTORS_WITHOUT_SEED_COMPANIES = {"INSURANCE", "TEXTILE COMPOSITE"}

APPLICABLE, CONDITIONAL, NOT_APPLICABLE = "applicable", "conditional", "not_applicable"

# Ratio -> {sector: (class, condition or reason)}. Default for a corporate sector is APPLICABLE unless set.
_GENERAL_CORPORATE = {
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "roe_average_balance",
    "roa_average_assets",
    "asset_turnover_average",
    "asset_turnover",
    "liabilities_to_assets",
    "cash_conversion",
    "payout_ratio",
    "current_ratio",
    "debt_to_equity",
    "interest_cover",
    "receivable_days",
    "inventory_days",
}

MATRIX: dict[str, dict[str, tuple[str, str]]] = {}


def _set(ratio: str, sectors: list[str], klass: str, note: str) -> None:
    for s in sectors:
        MATRIX.setdefault(ratio, {})[s] = (klass, note)


_CORP = [s for s, fw in SECTORS.items() if fw == "corporate"]
_BANK = ["COMMERCIAL BANKS"]
_INS = ["INSURANCE"]

for r in _GENERAL_CORPORATE:
    _set(r, _CORP, APPLICABLE, "general corporate measure")
_set(
    "liabilities_to_assets", _BANK, CONDITIONAL, "deposits dominate liabilities: read as a funding ratio only"
)
_set("roe", _BANK + _INS, APPLICABLE, "primary bank/insurer return measure")
_set("roa", _BANK + _INS, APPLICABLE, "return on the balance sheet")
for r in ("roe_average_balance", "roa_average_assets"):
    _set(r, _BANK + _INS, APPLICABLE, "average balances, when opening balance is promoted")
for r in (
    "gross_margin",
    "operating_margin",
    "asset_turnover",
    "asset_turnover_average",
    "cash_conversion",
    "payout_ratio",
    "current_ratio",
    "debt_to_equity",
    "interest_cover",
    "receivable_days",
    "inventory_days",
    "net_margin",
):
    _set(
        r,
        _BANK + _INS,
        NOT_APPLICABLE,
        "no gross margin, inventory or current classification for banks and insurers"
        if r in ("gross_margin", "operating_margin", "current_ratio", "inventory_days")
        else "not meaningful for a financial institution",
    )
_set("receivable_days", _INS, NOT_APPLICABLE, "premium and reinsurance receivables are not trade debtors")
_set("current_ratio", _INS, NOT_APPLICABLE, "insurers do not report a current/non-current split")
_set("cash_conversion", _INS, CONDITIONAL, "meaningful only with a stated operating cash flow definition")
_set("interest_cover", _CORP, APPLICABLE, "needs operating profit and finance cost")
_set(
    "inventory_days",
    ["OIL & GAS EXPLORATION COMPANIES"],
    CONDITIONAL,
    "inventory is small for upstream: meaningful only when inventory is material",
)
_set(
    "inventory_days",
    ["TECHNOLOGY & COMMUNICATION"],
    CONDITIONAL,
    "low inventory: meaningful only if material",
)
_set(
    "receivable_days",
    ["POWER GENERATION & DISTRIBUTION"],
    APPLICABLE,
    "power receivables are a key quality measure; circular-debt exposure is a separate conditional item",
)
_set("receivable_days", ["FERTILIZER"], CONDITIONAL, "subsidy or GoP receivables distort the proxy")

# Sector-specific measures
_set("nim", _BANK, APPLICABLE, "net interest margin: needs interest income and expense")
_set("cost_to_income", _BANK, APPLICABLE, "operating expense over total income")
_set("advances_to_deposits", _BANK, APPLICABLE, "liquidity and lending intensity")
_set("npl_to_advances", _BANK, APPLICABLE, "infection ratio: needs reported non-performing loans")
_set("provision_coverage", _BANK, CONDITIONAL, "only where provisions and NPLs are both reported")
_set("car_pct", _BANK, CONDITIONAL, "capital adequacy: only as reported by the bank")
_set("claims_ratio", _INS, APPLICABLE, "net claims over net premium")
_set("expense_ratio", _INS, APPLICABLE, "underwriting expenses over net premium")
_set("combined_ratio", _INS, APPLICABLE, "claims plus expense ratio (underwriting)")
_set("investment_income_share", _INS, APPLICABLE, "investment income over total income")
_set("solvency_ratio", _INS, CONDITIONAL, "only with a reported solvency figure and its definition")
_set(
    "production_growth",
    ["OIL & GAS EXPLORATION COMPANIES"],
    CONDITIONAL,
    "only where production volumes are reported",
)
_set(
    "realised_price_sensitivity",
    ["OIL & GAS EXPLORATION COMPANIES"],
    CONDITIONAL,
    "only with reported realised prices",
)
_set(
    "capex_intensity",
    ["OIL & GAS EXPLORATION COMPANIES", "POWER GENERATION & DISTRIBUTION", "CEMENT", "FERTILIZER"],
    APPLICABLE,
    "capital expenditure over revenue",
)
_set("net_debt_to_ebitda", _CORP, CONDITIONAL, "needs EBITDA and a net debt definition")
_set("dispatch_volume_growth", ["CEMENT"], CONDITIONAL, "only where dispatches are reported")
_set(
    "fuel_cost_share",
    ["CEMENT", "POWER GENERATION & DISTRIBUTION", "FERTILIZER"],
    CONDITIONAL,
    "only where the fuel or gas cost is disclosed",
)
_set("capacity_utilisation", ["CEMENT", "FERTILIZER"], CONDITIONAL, "only where disclosed")
_set(
    "employee_cost_intensity", ["TECHNOLOGY & COMMUNICATION"], CONDITIONAL, "only where payroll is disclosed"
)
_set(
    "fx_exposure_share",
    ["TECHNOLOGY & COMMUNICATION"],
    CONDITIONAL,
    "only where a currency split is disclosed",
)
_set("client_concentration", ["TECHNOLOGY & COMMUNICATION"], CONDITIONAL, "only where disclosed")
_set("export_share", ["TEXTILE COMPOSITE"], CONDITIONAL, "only where export revenue is disclosed")
_set(
    "subsidy_receivable_share",
    ["FERTILIZER"],
    CONDITIONAL,
    "only where GoP or subsidy receivables are disclosed",
)
_set("circular_debt_exposure", ["POWER GENERATION & DISTRIBUTION"], CONDITIONAL, "only where disclosed")


@dataclass(frozen=True)
class Classification:
    ratio: str
    sector: str
    applicability: str
    note: str
    state: str  # calculable | insufficient_data | not_applicable | conditional_unverified
    missing_inputs: tuple[str, ...] = ()


def applicability(ratio: str, sector: str) -> tuple[str, str]:
    """Applicability class and note for a ratio in a sector. A ratio not in the matrix is not applicable
    by default: no ratio is computed where its meaning has not been defined."""
    if sector not in SECTORS:
        raise ValueError(f"unknown sector: {sector!r}")
    if ratio in MATRIX and sector in MATRIX[ratio]:
        return MATRIX[ratio][sector]
    if SECTORS[sector] == "corporate" and ratio in _GENERAL_CORPORATE:
        return APPLICABLE, "general corporate measure"
    return NOT_APPLICABLE, "no defined meaning for this sector"


def classify(ratio: str, sector: str, present_inputs: set[str], required_inputs: set[str]) -> Classification:
    """Final state for one ratio: applicability first, then the inputs. A conditional ratio is never
    reported as calculable without its condition, so it is marked conditional_unverified."""
    klass, note = applicability(ratio, sector)
    if klass == NOT_APPLICABLE:
        return Classification(ratio, sector, klass, note, "not_applicable")
    missing = tuple(sorted(required_inputs - present_inputs))
    if missing:
        return Classification(ratio, sector, klass, note, "insufficient_data", missing)
    if klass == CONDITIONAL:
        return Classification(ratio, sector, klass, note, "conditional_unverified")
    return Classification(ratio, sector, klass, note, "calculable")


def matrix_rows() -> list[dict]:
    """The full applicability matrix, one row per (ratio, sector), for review and documentation."""
    ratios = sorted(set(MATRIX) | _GENERAL_CORPORATE)
    rows = []
    for r in ratios:
        for s in SECTORS:
            k, n = applicability(r, s)
            rows.append({"ratio": r, "sector": s, "class": k, "note": n})
    return rows


def company_sector(db, company_id: str) -> str | None:
    """The company's current PSX sector label, from the classification table, or None if unknown."""
    rows = db.execute(
        "SELECT s.name FROM company_classifications cc JOIN sectors s USING(sector_id) "
        "WHERE cc.company_id = ? AND cc.valid_to IS NULL", (company_id,))
    names = sorted({r["name"] for r in rows if r["name"] in SECTORS})
    if len(names) > 1:
        return None  # conflicting classifications: refuse to guess a sector
    return names[0] if names else None


def company_applicability(db, company_id: str, ratios: list[str]) -> dict:
    """Applicability of each ratio for a company's own sector. An unknown sector applies nothing."""
    sector = company_sector(db, company_id)
    if sector is None:
        return {"sector": None, "state": "unknown_sector", "ratios": {}}
    return {"sector": sector, "state": "ok",
            "ratios": {r: applicability(r, sector)[0] for r in ratios}}
