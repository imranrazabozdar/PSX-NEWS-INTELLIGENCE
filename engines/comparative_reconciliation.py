"""Comparative-period reconciliation: the prior period as printed in the current filing vs the prior filing.

Pure functions. Nothing is overwritten. Each finding says what it is:
  match                          same amount, same unit
  unit_presentation_difference   same amount in currency units, printed in a different unit (not a
  restatement)
  rounding_difference            within one printed unit of the coarser unit
  unit_scale_suspected           the ratio is an exact power of 1000 (possible wrong unit on one side)
  restatement_candidate          the amounts differ: a restatement or reclassification; the owner decides
  period_mismatch                the comparative column is not the period the prior filing reports
  not_compared                   one side is missing; no difference is invented

Discrepancies are reported in the CURRENT filing's printed unit, so a unit change does not look like a
restatement.
"""

from __future__ import annotations

import math

MATCH = "match"
UNIT_PRESENTATION = "unit_presentation_difference"
ROUNDING = "rounding_difference"
UNIT_SUSPECTED = "unit_scale_suspected"
RESTATEMENT = "restatement_candidate"
PERIOD_MISMATCH = "period_mismatch"
NOT_COMPARED = "not_compared"

POWERS = (1000.0, 1_000_000.0, 1_000_000_000.0)


def _is_power_ratio(ratio: float) -> bool:
    if ratio == 0 or not math.isfinite(ratio):
        return False
    for p in POWERS:
        for r in (ratio, 1 / ratio):
            if abs(r / p - 1) <= 0.005:
                return True
    return False


def compare(
    prior_own: dict[str, float | None],
    comparative: dict[str, float | None],
    *,
    prior_period: str,
    printed_period: str,
    prior_unit: int,
    current_unit: int,
) -> list[dict]:
    """One finding per canonical code present on either side."""
    codes = sorted(set(prior_own) | set(comparative))
    findings = []
    for code in codes:
        p, c = prior_own.get(code), comparative.get(code)
        base = {
            "code": code,
            "prior_period": prior_period,
            "printed_period": printed_period,
            "prior_unit": prior_unit,
            "current_unit": current_unit,
            "prior_printed": p,
            "comparative_printed": c,
        }
        if printed_period != prior_period:
            findings.append({**base, "classification": PERIOD_MISMATCH, "discrepancy": None})
            continue
        if p is None or c is None:
            findings.append(
                {
                    **base,
                    "classification": NOT_COMPARED,
                    "discrepancy": None,
                    "missing": "prior" if p is None else "comparative",
                }
            )
            continue
        p_cur = (
            p * prior_unit / current_unit
        )  # the prior value expressed in the current filing's printed unit
        disc = c - p_cur
        allow = 1.0  # one printed unit of the current filing
        if prior_unit == current_unit and c == p:
            cls = MATCH
        elif abs(c * current_unit - p * prior_unit) == 0:
            cls = UNIT_PRESENTATION
        elif abs(disc) <= allow:
            cls = ROUNDING
        elif p != 0 and _is_power_ratio(c / p_cur if p_cur else 0.0):
            cls = UNIT_SUSPECTED
        else:
            cls = RESTATEMENT
        findings.append(
            {
                **base,
                "classification": cls,
                "discrepancy": disc,
                "expected": p_cur,
                "reported": c,
                "allowance": allow,
            }
        )
    return findings


STATUS = {
    MATCH: "RECONCILED",
    UNIT_PRESENTATION: "RECONCILED",
    ROUNDING: "RECONCILED_WITH_ROUNDING",
    UNIT_SUSPECTED: "UNRECONCILED",
    RESTATEMENT: "UNRECONCILED",
    PERIOD_MISMATCH: "UNRECONCILED",
    NOT_COMPARED: "INSUFFICIENT_DATA",
}


def to_checks(findings: list[dict]) -> list[dict]:
    """Recon-compatible checks for storage. The finding's classification is kept in the check name's
    suffix."""
    checks = []
    for f in findings:
        checks.append(
            {
                "check": f"comparative:{f['code']}",
                "column_period_end": f["printed_period"],
                "reported": f.get("reported"),
                "expected": f.get("expected"),
                "discrepancy": f.get("discrepancy"),
                "allowance": f.get("allowance", 0.0),
                "status": STATUS[f["classification"]],
                "classification": f["classification"],
            }
        )
    return checks
