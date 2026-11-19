# ruff: noqa: E501
"""Forward (out-of-sample) tracking of the live setups rankings. Deterministic, no model, private.

Each trading day the live top 10 of every ranking is recorded BEFORE anything is known about what follows,
together with the whole eligible group. Later, once enough sessions have passed, each snapshot is scored: the
average return of its top 10 against the average of the whole group over the next 1, 5 and 10 sessions.

Tracks: technical, fundamental, combined (the three tabs as shown), and technical_novol (price items only, the
volume item removed: the variant the back-test hinted at, now followed forward instead of adopted). Nothing is
written to the library; the snapshots live in a private file carried between runs.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from engines import setups

HORIZONS = (1, 5, 10)
TRACKS = ("technical", "fundamental", "combined", "technical_novol")
MIN_TOP = 8
MIN_GROUP = 20


def novol_top(
    rows: dict[str, dict[str, Any]], bars: dict[str, list[dict[str, Any]]], day: str, top: int = setups.TOP
):
    """Top symbols by the price-only technical score with the volume item removed."""
    scored = []
    when = date.fromisoformat(day)
    for sym in rows:
        window = sorted(bars[sym], key=lambda r: r["trade_date"])[-38:]
        pts, _ = setups.technical_items(window, [], when)
        if pts.get("volume") is not None:
            pts["volume"] = 0.0  # the same variant the back-test used (weight 0): every stock gets the same share
        score = setups.pillar(pts, setups.TECH_ITEMS, setups.MIN_TECH_POINTS)
        if score is not None:
            scored.append((score, sym))
    return [s for _sc, s in sorted(scored, key=lambda x: (-x[0], x[1]))[:top]]


def snapshot(result: dict[str, Any], bars: dict[str, list[dict[str, Any]]], day: str) -> dict[str, Any]:
    """One day's record from setups.build()'s output: the symbols in each top 10 and the eligible group."""
    rows = result["rows"]
    tracks = {t: [r["symbol"] for r in result[t]] for t in ("technical", "fundamental", "combined")}
    tracks["technical_novol"] = novol_top(rows, bars, day)
    return {"day": day, "group": sorted(rows), "tracks": tracks}


def _forward(bars: dict[str, list[dict[str, Any]]], sym: str, day: str, h: int) -> float | None:
    rows = sorted(bars.get(sym, []), key=lambda r: r["trade_date"])
    for i, r in enumerate(rows):
        if r["trade_date"] == day:
            if i + h < len(rows) and float(r["close"]) > 0:
                return (float(rows[i + h]["close"]) / float(r["close"]) - 1) * 100
            return None
    return None


def evaluate(snaps: list[dict[str, Any]], bars: dict[str, list[dict[str, Any]]], horizons=HORIZONS):
    """{track: {h: [ {day, top, group, excess} ]}} for every snapshot old enough to be scored."""
    out: dict[str, dict[int, list[dict[str, Any]]]] = {t: {h: [] for h in horizons} for t in TRACKS}
    for snap in snaps:
        for h in horizons:
            grp = [v for s in snap["group"] if (v := _forward(bars, s, snap["day"], h)) is not None]
            if len(grp) < MIN_GROUP:
                continue
            gmean = statistics.fmean(grp)
            for t in TRACKS:
                tops = [
                    v
                    for s in snap["tracks"].get(t, [])
                    if (v := _forward(bars, s, snap["day"], h)) is not None
                ]
                if len(tops) >= MIN_TOP:
                    tm = statistics.fmean(tops)
                    out[t][h].append({"day": snap["day"], "top": tm, "group": gmean, "excess": tm - gmean})
    return out


def report(snaps: list[dict[str, Any]], scored: dict[str, dict[int, list[dict[str, Any]]]]) -> str:
    days = sorted(s["day"] for s in snaps)
    lines = [
        "# Setups forward tracking (out of sample, private)",
        "",
        f"{len(snaps)} daily snapshots recorded"
        + (f" ({days[0]} to {days[-1]})" if days else "")
        + ". Each day's live top 10 is compared with the whole eligible group over the next sessions, "
        "using only what happened after the snapshot. Excess = top-10 average return minus group average "
        "return, in percentage points. Few snapshots mean the numbers mean little: wait for at least 20 per horizon.",
        "",
        "| track | horizon | snapshots scored | top-10 avg | group avg | avg excess | beat the group |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in TRACKS:
        for h, rows in scored[t].items():
            if not rows:
                lines.append(f"| {t} | {h} | 0 | n/a | n/a | n/a | n/a |")
                continue
            ex = statistics.fmean(r["excess"] for r in rows)
            beat = 100 * statistics.fmean(1.0 if r["excess"] > 0 else 0.0 for r in rows)
            lines.append(
                f"| {t} | {h} | {len(rows)} | {statistics.fmean(r['top'] for r in rows):+.2f}% | "
                f"{statistics.fmean(r['group'] for r in rows):+.2f}% | {ex:+.2f}pp | {beat:.0f}% |"
            )
    lines += ["", "Not advice, not a forecast. No costs or slippage; closes only."]
    return "\n".join(lines) + "\n"


SCHEMA_VERSION = 1
METHOD = (
    "Each weekday the live top 10 of every ranking is recorded with the whole eligible group. A snapshot is "
    "scored against the next 1, 5 and 10 sessions: top-10 average return minus group average return. "
    "Scoring weights are not changed while the tracker runs."
)


def results_payload(snaps: list[dict[str, Any]], scored: dict[str, dict[int, list[dict[str, Any]]]], now: str) -> dict:
    """A small, versioned results file for the data branch (no credentials, no personal data)."""
    days = sorted(s["day"] for s in snaps)
    summary = []
    for t in TRACKS:
        for h, rows in scored[t].items():
            summary.append(
                {
                    "track": t,
                    "horizon": h,
                    "snapshots_scored": len(rows),
                    "top_avg": round(statistics.fmean(r["top"] for r in rows), 3) if rows else None,
                    "group_avg": round(statistics.fmean(r["group"] for r in rows), 3) if rows else None,
                    "avg_excess": round(statistics.fmean(r["excess"] for r in rows), 3) if rows else None,
                    "beat_rate": round(statistics.fmean(1.0 if r["excess"] > 0 else 0.0 for r in rows), 3)
                    if rows
                    else None,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "method": METHOD,
        "generated_utc": now,
        "snapshots": len(snaps),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "checkpoints": {"initial": 20, "early": 30, "preliminary": "60-90 days", "meaningful": "6 months"},
        "summary": summary,
        "snapshot_days": days,
    }


def validate_snapshots(snaps: list[dict[str, Any]]) -> list[str]:
    """Problems that would make the file untrustworthy: duplicate days, malformed days or symbols."""
    problems: list[str] = []
    seen: set[str] = set()
    for s in snaps:
        d = s.get("day", "")
        if len(d) != 10 or d[4] != "-" or d[7] != "-":
            problems.append(f"malformed day {d!r}")
        if d in seen:
            problems.append(f"duplicate snapshot for {d}")
        seen.add(d)
        for t, syms in s.get("tracks", {}).items():
            if t not in TRACKS or any(not str(x).replace("-", "").isalnum() for x in syms):
                problems.append(f"{d}: bad track or symbol in {t}")
    return problems
