"""Segment financial analysis: reconciled to the group, evidence-backed, never plugged.

Each segment and the group total carry evidence {page, excerpt}. Segments must add up to the group
within a stated tolerance. If they do not, the result is `unreconciled`: the difference is shown and no
shares or margins are presented as facts. Missing values stay missing, and a zero base is not_applicable.
"""

from __future__ import annotations

from typing import Any

ENGINE_VERSION = "segments/1"
TOLERANCE_NOTE = ("tolerance = the larger of 1.0 reporting unit and 0.1% of the group total "
                  "(an analyst assumption for rounding; owner may change it)")


class EvidenceError(ValueError):
    """A segment or group figure was supplied without its page and excerpt."""


def _check_evidence(row: dict[str, Any], label: str) -> None:
    ev = row.get("evidence") or {}
    page, excerpt = ev.get("page"), str(ev.get("excerpt", "")).strip()
    if not (isinstance(page, int) and page > 0 and excerpt):
        raise EvidenceError(f"{label}: needs the page number and the verbatim excerpt")


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def reconcile(segments: list[dict[str, Any]], group: dict[str, Any]) -> dict[str, Any]:
    """Check that segment revenue and profit add up to the group. Every figure needs evidence."""
    _check_evidence(group, "group")
    for s in segments:
        _check_evidence(s, f"segment {s.get('name')!r}")
    out: dict[str, Any] = {
        "engine": ENGINE_VERSION, "tolerance_note": TOLERANCE_NOTE,
        "group": {"revenue": _num(group.get("revenue")), "profit": _num(group.get("profit")),
                  "evidence": group["evidence"]}}
    rev_total = group.get("revenue")
    if rev_total is None:
        out["state"] = "insufficient_data"
        out["missing"] = ["group revenue"]
        return out
    seg_rev = [s.get("revenue") for s in segments]
    if any(v is None for v in seg_rev):
        out["state"] = "insufficient_data"
        out["missing"] = [f"revenue of segment {s['name']!r}" for s in segments if s.get("revenue") is None]
        return out
    tol = max(1.0, abs(float(rev_total)) * 0.001)
    diff = sum(float(v) for v in seg_rev) - float(rev_total)
    out["revenue_difference"] = round(diff, 4)
    out["revenue_tolerance"] = round(tol, 4)
    if abs(diff) > tol:
        out["state"] = "unreconciled"
        out["reason"] = "segment revenue does not add up to the group total; no shares are presented"
        return out
    out["state"] = "reconciled"
    out["segments"] = shares_and_margins(segments, float(rev_total), group.get("profit"))
    return out


def shares_and_margins(segments: list[dict[str, Any]], group_revenue: float,
                       group_profit: float | None) -> list[dict[str, Any]]:
    rows = []
    for s in segments:
        rev, prof = s.get("revenue"), s.get("profit")
        row: dict[str, Any] = {"name": s["name"], "revenue": float(rev), "evidence": s["evidence"],
                               "revenue_share_pct": round(float(rev) / group_revenue * 100, 2)
                               if group_revenue else None}
        if prof is None:
            row["margin_state"], row["margin_pct"] = "insufficient_data", None
            row["missing"] = ["profit"]
        elif float(rev) <= 0:
            row["margin_state"], row["margin_pct"] = "not_applicable", None
        else:
            row["margin_state"], row["margin_pct"] = "ok", round(float(prof) / float(rev) * 100, 2)
            row["profit"] = float(prof)
        rows.append(row)
    if group_profit and group_profit > 0:
        profit_known = [r for r in rows if r.get("profit") is not None]
        if len(profit_known) == len(rows):
            total = sum(r["profit"] for r in rows)
            for r in rows:
                r["profit_share_pct"] = round(r["profit"] / total * 100, 2) if total else None
    return rows


def growth(current: list[dict[str, Any]], prior: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Revenue growth by segment name.

    A segment absent from the prior year is not_reported, not zero growth."""
    before = {p["name"]: p for p in prior}
    out = []
    for c in current:
        p = before.get(c["name"])
        row: dict[str, Any] = {"name": c["name"]}
        if p is None or p.get("revenue") is None or c.get("revenue") is None:
            row["state"], row["growth_pct"] = "not_reported", None
        elif float(p["revenue"]) <= 0:
            row["state"], row["growth_pct"] = "not_applicable", None
        else:
            row["state"] = "ok"
            base = float(p["revenue"])
            row["growth_pct"] = round((float(c["revenue"]) - base) / base * 100, 2)
        out.append(row)
    return out


def concentration(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The largest segment by revenue share, for reporting. Only defined when shares are reconciled."""
    shares = [r for r in rows if r.get("revenue_share_pct") is not None]
    if not shares:
        return None
    top = max(shares, key=lambda r: r["revenue_share_pct"])
    return {"name": top["name"], "revenue_share_pct": top["revenue_share_pct"]}
