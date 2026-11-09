"""Earnings-quality indicators for review (CFA-style analysis layer, F2).

These functions compare reported numbers and report indicators that merit review. They do not conclude that
a company is manipulating earnings or in financial distress. Every indicator states its evidence, calculation,
period, alternative explanations, confidence and the further evidence needed.

Inputs must be the same period type and scope. Missing inputs are missing (never zero).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

REVIEW_THRESHOLD_PP = (
    0.10  # a 10 percentage-point gap between growth rates prompts review (a parameter, not a finding)
)


@dataclass
class Indicator:
    name: str
    state: str  # flag_for_review | no_flag | insufficient_data
    observed: str
    calculation: str
    period: str
    why_it_matters: str
    alternative_explanations: list[str] = field(default_factory=list)
    confidence: str = "low"
    additional_evidence_needed: list[str] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _growth(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None  # division by zero or a missing input: not computable, never zero
    return cur / prev - 1


def _missing(name: str, period: str, need: list[str]) -> Indicator:
    return Indicator(
        name,
        "insufficient_data",
        "inputs missing",
        "not computed",
        period,
        "Cannot be assessed without the inputs.",
        additional_evidence_needed=need,
    )


def growth_gap_indicator(
    name: str,
    base_label: str,
    rev: tuple[float | None, float | None],
    item: tuple[float | None, float | None],
    period: str,
    scope: str,
) -> Indicator:
    """Flags when an item (receivables or inventory) grows much faster than the revenue it supports."""
    g_rev, g_item = _growth(*rev), _growth(*item)
    if g_rev is None or g_item is None:
        return _missing(name, period, [f"{base_label} for the current and comparable prior period ({scope})"])
    gap = g_item - g_rev
    flag = gap > REVIEW_THRESHOLD_PP
    return Indicator(
        name=name,
        state="flag_for_review" if flag else "no_flag",
        observed=f"{base_label} growth {g_item:+.1%} against revenue growth {g_rev:+.1%} (gap {gap:+.1%})",
        calculation=f"growth({base_label}) - growth(revenue); flag when gap > {REVIEW_THRESHOLD_PP:.0%}",
        period=period,
        why_it_matters=f"{base_label} growing faster than sales can mean slower collection, slower sales, or "
        "provisioning or valuation choices that affect profit.",
        alternative_explanations=[
            "timing of large deliveries or year-end billing",
            "a change in customer mix or credit terms",
            "a classification change or a reclassification between line items",
            "a one-off balance such as a government or subsidy receivable",
        ],
        confidence="medium" if flag else "low",
        additional_evidence_needed=[
            "ageing analysis of the balance",
            "provisioning note",
            "explanation of credit-term changes",
            "comparable prior-period balance",
        ],
        inputs={"revenue": rev, base_label: item, "scope": scope},
    )


def cash_conversion_indicator(pat: float | None, cfo: float | None, period: str, scope: str) -> Indicator:
    """Operating cash flow over profit after tax, same period and scope. A loss is not computable."""
    if pat is None or cfo is None:
        return _missing("cash conversion", period, [f"profit after tax and operating cash flow ({scope})"])
    if pat <= 0:
        return Indicator(
            "cash conversion",
            "insufficient_data",
            f"profit after tax {pat:,.0f} is not positive",
            "cfo / profit after tax is not meaningful for a loss",
            period,
            "A ratio against a loss has no economic meaning.",
            additional_evidence_needed=["multi-period operating cash flow trend"],
            inputs={"pat": pat, "cfo": cfo, "scope": scope},
        )
    ratio = cfo / pat
    flag = ratio < 0.5 and cfo < pat  # a low share of profit in cash: a question, not a conclusion
    return Indicator(
        name="cash conversion",
        state="flag_for_review" if flag else "no_flag",
        observed=f"operating cash flow equals {ratio:.2f} times profit after tax in {period}",
        calculation="cfo / profit_after_tax, same period and scope",
        period=period,
        why_it_matters="Profit that is not converted to cash depends more on accruals and estimates.",
        alternative_explanations=[
            "working-capital build for a growing business",
            "a single-quarter timing effect (not comparable with annual figures)",
            "non-cash income such as share of profit of associates",
        ],
        confidence="medium" if flag else "low",
        additional_evidence_needed=[
            "cash-flow trend across at least three annual periods",
            "reconciliation of non-cash income in the cash-flow statement",
        ],
        inputs={"pat": pat, "cfo": cfo, "ratio": ratio, "scope": scope},
    )


def accrual_indicator(
    pat: float | None, cfo: float | None, avg_assets: float | None, period: str, scope: str
) -> Indicator:
    """(profit after tax - operating cash flow) over average total assets. Not annualised here."""
    if pat is None or cfo is None or avg_assets in (None, 0):
        return _missing(
            "accrual ratio", period, [f"profit, operating cash flow and average assets ({scope})"]
        )
    accrual = (pat - cfo) / avg_assets
    flag = accrual > 0.10
    return Indicator(
        name="accrual ratio",
        state="flag_for_review" if flag else "no_flag",
        observed=f"accrual ratio {accrual:+.1%} of average assets in {period}",
        calculation="(profit_after_tax - cfo) / average total assets (same period; not annualised)",
        period=period,
        why_it_matters="A large positive accrual means profit is mostly non-cash in that period.",
        alternative_explanations=["period-end timing", "non-cash gains on investments or associates"],
        confidence="low",
        additional_evidence_needed=["multi-period accrual trend", "composition of non-cash items"],
        inputs={"pat": pat, "cfo": cfo, "avg_assets": avg_assets, "scope": scope},
    )


def yoy_growth(current: tuple[str, float | None], prior: tuple[str, float | None]) -> dict:
    """Year-over-year growth only between like periods: both must be the same period type."""
    (cp, cv), (pp, pv) = current, prior
    if cp.split(":")[0] != pp.split(":")[0]:
        return {
            "state": "refused",
            "reason": "period types differ: quarterly and annual values are not compared",
        }
    g = _growth(cv, pv)
    if g is None:
        return {"state": "insufficient_data", "period": cp}
    return {"state": "ok", "period": cp, "growth": g}
