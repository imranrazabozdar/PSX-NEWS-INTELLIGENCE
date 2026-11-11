"""The archive status vocabulary (migration 0007) and the rules that choose a status. Pure functions.

Precedence for a statement: unreconciled > not_verifiable_from_disclosure > requires_review >
insufficient_data > unmapped > reconciled_with_rounding > reconciled. A failed identity is never hidden by a
weaker status.
"""

from __future__ import annotations

VOCABULARY = (
    "reconciled",
    "reconciled_with_rounding",
    "unreconciled",
    "insufficient_data",
    "not_verifiable_from_disclosure",
    "unmapped",
    "requires_review",
)
LEGACY_CHECK_STATUS = {
    "RECONCILED": "reconciled",
    "RECONCILED_WITH_ROUNDING": "reconciled_with_rounding",
    "UNRECONCILED": "unreconciled",
    "INSUFFICIENT_DATA": "insufficient_data",
}
IAS7_NOT_VERIFIABLE = "NOT_VERIFIABLE_FROM_DISCLOSURE"


def from_check_status(status: str) -> str:
    """A reconciliation check's status (legacy upper-case code) as a vocabulary code."""
    if status not in LEGACY_CHECK_STATUS:
        raise ValueError(f"unknown check status {status!r}")
    return LEGACY_CHECK_STATUS[status]


def statement_status(
    check_statuses: list[str],
    *,
    not_verifiable: str | None = None,
    requires_review: list[str] | None = None,
    unmapped: int = 0,
) -> tuple[str, str]:
    """(status, reason) for one statement. check_statuses are legacy codes from its identity checks."""
    codes = [from_check_status(s) for s in check_statuses]
    if not codes:
        return "insufficient_data", "no identity check could be run for this statement"
    if "unreconciled" in codes:
        return "unreconciled", "an identity fails; the discrepancy is stored"
    if not_verifiable:
        return "not_verifiable_from_disclosure", not_verifiable
    if requires_review:
        return "requires_review", "; ".join(requires_review)
    if "insufficient_data" in codes:
        return "insufficient_data", "an input needed for an identity is not extracted"
    if unmapped:
        return "unmapped", f"{unmapped} printed line(s) have no canonical mapping"
    if "reconciled_with_rounding" in codes:
        return "reconciled_with_rounding", "every identity holds within the printed rounding allowance"
    return "reconciled", "every identity holds exactly, from the disclosure"


def fact_status(
    canonical_code: str | None, statement: str | None, *, ias7: str | None = None
) -> tuple[str, str]:
    """(status, reason) for one stored fact, given its statement status is decided separately."""
    if canonical_code is None:
        return "unmapped", "printed line has no canonical mapping"
    if ias7 == IAS7_NOT_VERIFIABLE and canonical_code == "cash_and_equivalents":
        return "not_verifiable_from_disclosure", (
            "cash-equivalent classification not provable from the disclosure")
    return "reconciled", f"statement {statement} reconciles; the fact is part of it"
