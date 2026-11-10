"""Earnings quality and audit signals: evidence-backed, descriptive, never graded.

Inputs are canonical metric dicts shaped like `engines.fundamentals.metrics` output:
name -> {value, metric_id, basis}. Every number carries its source row and basis.
A missing input is reported as missing, never as zero.
A ratio whose denominator is zero or negative is `not_applicable`, not a strong or weak result.

Audit signals come from sourced document facts. An audit fact without a page and an excerpt is refused, so no
opinion or key audit matter is accepted on trust. A fact the report does not state is `not_reported`, never
assumed clean.

Thresholds are not set here: the owner sets them (fundamentals bands, open item U9). The output states the
numbers and their divergence, and does not grade them.
"""

from __future__ import annotations

from typing import Any

ENGINE_VERSION = "earnings-quality/1"
OPINIONS = ("unqualified", "qualified", "adverse", "disclaimer")
AUDIT_KEYS = ("opinion", "key_audit_matters", "going_concern_uncertainty")


class EvidenceError(ValueError):
    """A sourced fact was supplied without its page and excerpt."""


def _inputs(m: dict[str, dict], keys: tuple[str, ...]) -> tuple[dict, list[str]]:
    used, missing = {}, []
    for k in keys:
        if k in m:
            used[k] = {"value": m[k]["value"], "metric_id": m[k].get("metric_id"), "basis": m[k].get("basis")}
        else:
            missing.append(k)
    return used, missing


def _ratio(name: str, formula: str, cur: dict, num: str, den: str, *, scale: float = 1.0,
           basis_note: str = "") -> dict[str, Any]:
    used, missing = _inputs(cur, (num, den))
    out: dict[str, Any] = {"name": name, "formula": formula, "inputs": used, "missing": missing,
                           "value": None, "state": "ok"}
    if basis_note:
        out["basis_note"] = basis_note
    if missing:
        out["state"] = "insufficient_data"
        return out
    n, d = float(cur[num]["value"]), float(cur[den]["value"])
    if d <= 0:
        out["state"] = "not_applicable"
        out["reason"] = f"{den} is zero or negative"
        return out
    out["value"] = round(n / d * scale, 4)
    return out


def _accruals(cur: dict[str, dict]) -> dict[str, Any]:
    """(profit_after_tax - cfo) / total_assets. Closing assets, so the basis is stated, not averaged."""
    name, formula = "accruals_to_assets", "(profit_after_tax - cfo) / total_assets (closing)"
    basis = "closing total assets, not averaged"
    used, missing = _inputs(cur, ("profit_after_tax", "cfo", "total_assets"))
    out: dict[str, Any] = {"name": name, "formula": formula, "inputs": used, "missing": missing,
                           "value": None, "state": "ok", "basis_note": basis}
    if missing:
        out["state"] = "insufficient_data"
        return out
    assets = float(cur["total_assets"]["value"])
    if assets <= 0:
        out["state"] = "not_applicable"
        out["reason"] = "total_assets is zero or negative"
        return out
    out["value"] = round((float(cur["profit_after_tax"]["value"]) - float(cur["cfo"]["value"])) / assets, 4)
    return out


def ratios(cur: dict[str, dict], prev: dict[str, dict] | None) -> dict[str, dict]:
    """Cash conversion, accruals and receivables against revenue. Closing balances, as in fundamentals."""
    return {
        "cfo_to_profit": _ratio("cfo_to_profit", "cfo / profit_after_tax", cur, "cfo", "profit_after_tax"),
        "receivable_days": _ratio("receivable_days", "trade_receivables / revenue x 365 (closing balance)",
                                  cur, "trade_receivables", "revenue", scale=365.0),
        "accruals_to_assets": _accruals(cur),
        "receivables_vs_revenue": growth_divergence(cur, prev),
    }


def growth_divergence(cur: dict[str, dict], prev: dict[str, dict] | None) -> dict[str, Any]:
    """Receivables growth minus revenue growth, in percentage points. Needs the prior year to be imported."""
    res: dict[str, Any] = {"name": "receivables_vs_revenue",
                           "formula": "growth(trade_receivables) - growth(revenue)",
                           "value": None, "state": "ok", "missing": []}
    if prev is None:
        res["state"], res["missing"] = "insufficient_data", ["prior period"]
        return res
    needed = [("trade_receivables", cur), ("revenue", cur), ("trade_receivables", prev), ("revenue", prev)]
    missing = []
    for key, src in needed:
        if key not in src:
            label = key if src is cur else f"{key} (prior)"
            if label not in missing:
                missing.append(label)
    if missing:
        res["state"], res["missing"] = "insufficient_data", missing
        return res
    rec_c, rev_c = float(cur["trade_receivables"]["value"]), float(cur["revenue"]["value"])
    rec_p, rev_p = float(prev["trade_receivables"]["value"]), float(prev["revenue"]["value"])
    if rec_p <= 0 or rev_p <= 0:
        res["state"] = "not_applicable"
        res["reason"] = "prior-year receivables or revenue is zero or negative"
        return res
    rec_g = (rec_c - rec_p) / rec_p * 100
    rev_g = (rev_c - rev_p) / rev_p * 100
    res["receivables_growth_pct"] = round(rec_g, 2)
    res["revenue_growth_pct"] = round(rev_g, 2)
    res["value"] = round(rec_g - rev_g, 2)
    return res


def audit_signals(facts: dict[str, Any] | None) -> dict[str, Any]:
    """Audit opinion, key audit matters and going-concern uncertainty, as the report states them.

    facts keys (each optional): opinion (one of OPINIONS), key_audit_matters (count),
    going_concern_uncertainty (bool). Every stated fact must carry evidence = {page, excerpt}; otherwise
    EvidenceError."""
    facts = facts or {}
    stated = {k: v for k, v in facts.items() if k in AUDIT_KEYS and v is not None}
    if stated:
        ev = facts.get("evidence") or {}
        page, excerpt = ev.get("page"), str(ev.get("excerpt", "")).strip()
        if not (isinstance(page, int) and page > 0 and excerpt):
            raise EvidenceError("audit facts need the page number and the verbatim excerpt they come from")
    out: dict[str, Any] = {"engine": ENGINE_VERSION, "evidence": facts.get("evidence")}
    if "opinion" not in stated:
        out["opinion"] = {"state": "not_reported"}
    else:
        if stated["opinion"] not in OPINIONS:
            raise EvidenceError(f"unknown audit opinion {stated['opinion']!r}")
        out["opinion"] = {"state": "reported", "value": stated["opinion"],
                          "is_unqualified": stated["opinion"] == "unqualified"}
    if "key_audit_matters" not in stated:
        out["key_audit_matters"] = {"state": "not_reported"}
    else:
        out["key_audit_matters"] = {"state": "reported", "value": int(stated["key_audit_matters"])}
    if "going_concern_uncertainty" not in stated:
        out["going_concern_uncertainty"] = {"state": "not_reported"}
    else:
        out["going_concern_uncertainty"] = {"state": "reported",
                                            "value": bool(stated["going_concern_uncertainty"])}
    return out


def assess(cur: dict[str, dict], prev: dict[str, dict] | None = None,
           audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """One company-period: ratios and audit signals, with reported and calculated values kept apart."""
    reported_keys = [k for k in ("revenue", "profit_after_tax", "cfo", "total_assets", "trade_receivables")
                     if k in cur]
    return {
        "engine": ENGINE_VERSION,
        "reported_inputs": {k: cur[k] for k in reported_keys},
        "ratios": ratios(cur, prev),
        "audit": audit_signals(audit),
        "note": "descriptive; no thresholds applied (owner sets bands, open item U9)",
    }
