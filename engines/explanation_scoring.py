"""Do the move explanations tell us anything? A descriptive check of past notable moves. No model.

For every notable move in the stored price history, the explainer is run with only the evidence that
existed on the day of the move (nothing dated later), and the move is filed in one bucket by its verdict.
Each bucket is then described by what the price did in the next sessions, signed so that a positive number
means "it carried on in the direction of the move" and a negative number means "it gave the move back".

This is a description of the past, not a rule and not a forecast. Samples are small, windows overlap,
price limits and illiquid names distort the numbers, and nothing here is tradable advice. Buckets with
fewer than MIN_N moves are marked low-sample.
"""

from __future__ import annotations

import statistics
from typing import Any

HORIZONS = (1, 5)
MIN_N = 30
BUCKETS = (
    ("results", "a result or corporate action on file"),
    ("company", "other company evidence on file (news or a material announcement)"),
    ("shared", "shared with its sector or the market"),
    ("scheduled", "only routine scheduled notices on file"),
    ("unexplained", "no cause on file"),
)


def bucket_of(item: dict[str, Any]) -> str:
    kinds = {e["kind"] for e in item["evidence"]}
    if "company_event" in kinds:
        return "results"
    if kinds & {"company_news", "company_announcement"}:
        return "company"
    if kinds & {"sector", "market"}:
        return "shared"
    if "scheduled_notice" in kinds:
        return "scheduled"
    return "unexplained"


def forward_signed(bars: list[dict[str, Any]], day: str, move: float) -> dict[int, float]:
    """Signed forward return (percent) after `day` for each horizon that has enough later sessions."""
    rows = sorted(bars, key=lambda b: b["trade_date"])
    idx = next((i for i, b in enumerate(rows) if b["trade_date"] == day), None)
    if idx is None or not move:
        return {}
    base = float(rows[idx]["close"])
    sign = 1.0 if move > 0 else -1.0
    out: dict[int, float] = {}
    for k in HORIZONS:
        if idx + k < len(rows) and base > 0:
            out[k] = sign * (float(rows[idx + k]["close"]) / base - 1) * 100
    return out


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "carried_on": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "carried_on": round(100 * sum(1 for v in values if v > 0) / len(values), 1),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: {bucket, move, forward: {horizon: signed percent}}."""
    out: dict[str, Any] = {"total": len(rows), "buckets": {}}
    for key, label in (*BUCKETS, ("all", "all notable moves")):
        part = rows if key == "all" else [r for r in rows if r["bucket"] == key]
        entry: dict[str, Any] = {
            "label": label,
            "n": len(part),
            "share": round(100 * len(part) / len(rows), 1) if rows else None,
            "mean_abs_move": round(statistics.fmean(abs(r["move"]) for r in part), 2) if part else None,
            "low_sample": len(part) < MIN_N,
        }
        for k in HORIZONS:
            entry[f"fwd_{k}d"] = _stats([r["forward"][k] for r in part if k in r["forward"]])
        out["buckets"][key] = entry
    return out


def render_markdown(summary: dict[str, Any], first: str, last: str, symbols: int) -> str:
    lines = [
        "# Do the move explanations tell us anything? (descriptive, past moves only)",
        "",
        f"{summary['total']} notable moves (5% or more, or volume 3x or more) from {first} to {last}, "
        f"{symbols} symbols. Each move was explained using only evidence dated on or before its day. "
        "Forward numbers are signed: positive = the price carried on in the direction of the move, "
        "negative = it gave the move back.",
        "",
        "Not a rule and not a forecast: small samples, overlapping windows, price limits and thin trading "
        "distort these figures. Buckets under 30 moves are marked low-sample.",
        "",
        "| Bucket | Moves | Share | Mean abs move | Next day (mean / median / carried on) "
        "| 5 days (mean / median / carried on) |",
        "|---|---|---|---|---|---|",
    ]
    for b in summary["buckets"].values():
        flag = " (low sample)" if b["low_sample"] else ""
        lines.append(
            f"| {b['label']}{flag} | {b['n']} | {b['share']}% | {b['mean_abs_move']}% | "
            f"{_cell(b['fwd_1d'])} | {_cell(b['fwd_5d'])} |"
        )
    return "\n".join(lines) + "\n"


def _cell(s: dict[str, Any]) -> str:
    if not s["n"]:
        return "n/a"
    return f"{s['mean']:+.2f}% / {s['median']:+.2f}% / {s['carried_on']:.0f}% (n={s['n']})"
