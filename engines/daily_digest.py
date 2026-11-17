"""The daily digest: one short page of what changed and what to look at. Deterministic, no model, read only.

It assembles pieces that already exist (market breadth from price_daily, the company radar, the move
explanations) and says how fresh the data underneath is. It carries no buy or sell view and no forecast.
Unknowns stay unknown.
"""

from __future__ import annotations

import statistics
from typing import Any


def breadth(moves: dict[tuple[str, str], dict[str, Any]], day: str) -> dict[str, Any] | None:
    """Advancers, decliners and the median move across tracked symbols on `day`; None if nothing traded."""
    vals = {s: m["move"] for (s, d), m in moves.items() if d == day}
    if not vals:
        return None
    ranked = sorted(vals.items(), key=lambda kv: kv[1])
    return {
        "day": day,
        "symbols": len(vals),
        "up": sum(1 for v in vals.values() if v > 0),
        "down": sum(1 for v in vals.values() if v < 0),
        "flat": sum(1 for v in vals.values() if v == 0),
        "median": round(statistics.median(vals.values()), 2),
        "top_up": [(s, round(v, 1)) for s, v in ranked[::-1][:3]],
        "top_down": [(s, round(v, 1)) for s, v in ranked[:3]],
    }


def latest_trading_day(moves: dict[tuple[str, str], dict[str, Any]]) -> str | None:
    days = {d for (_s, d) in moves}
    return max(days) if days else None


def render(
    today: str,
    day: str | None,
    br: dict[str, Any] | None,
    radar: list[dict[str, Any]],
    moves: list[dict[str, Any]],
    fresh: dict[str, str | None],
    universe: int,
) -> str:
    lines = [
        f"# PSX daily digest, {today}",
        "",
        "A summary of evidence on file. Scores and explanations order attention only: they are not "
        "forecasts, "
        "not proof of cause and not recommendations.",
        "",
    ]
    lines.append("## Data freshness")
    for label, value in fresh.items():
        lines.append(f"- {label}: {value or 'unknown'}")
    lines.append("")
    lines.append(f"## Market on {day or 'unknown'}")
    if br:
        lines.append(
            f"- {br['symbols']} symbols traded: {br['up']} up, {br['down']} down, {br['flat']} unchanged; "
            f"median move {br['median']:+.2f}%."
        )
        lines.append("- Biggest rises: " + ", ".join(f"{s} {v:+.1f}%" for s, v in br["top_up"]))
        lines.append("- Biggest falls: " + ", ".join(f"{s} {v:+.1f}%" for s, v in br["top_down"]))
    else:
        lines.append("- No price data for that day.")
    lines.append("")
    lines.append("## Companies to look at (radar)")
    if not radar:
        lines.append("- Nothing scored in the window.")
    for i, s in enumerate(radar, 1):
        top = max(s["drivers"], key=lambda d: d["points"])
        kinds = ", ".join(sorted({d["kind"] for d in s["drivers"]}))
        lines.append(f"{i}. {s['symbol']} (score {s['score']}): {top['text'][:140]} [{kinds}]")
        for u in s["unknown"][:1]:
            lines.append(f"   - unknown: {u}")
    lines.append("")
    lines.append("## Notable moves and what is on file")
    explained = [m for m in moves if not m["verdict"].startswith("no identified cause")]
    unexplained = [m for m in moves if m["verdict"].startswith("no identified cause")]
    for m in explained[:8]:
        vol = f", volume {m['volume_x']:.1f}x" if m.get("volume_x") else ""
        why = m["evidence"][0]["text"][:120] if m["evidence"] else m["verdict"]
        lines.append(f"- {m['symbol']} {m['move']:+.1f}% on {m['day']}{vol}: {m['verdict']} ({why})")
    lines.append("")
    lines.append(f"## Unexplained (no cause on file): {len(unexplained)} of {len(moves)} notable moves")
    for m in sorted(unexplained, key=lambda m: -abs(m["move"]) * (m.get("volume_x") or 1))[:8]:
        vol = f", volume {m['volume_x']:.1f}x" if m.get("volume_x") else ""
        lines.append(f"- {m['symbol']} {m['move']:+.1f}% on {m['day']}{vol}")
    lines.append("")
    lines.append(f"{universe} symbols have a price series; others are not covered.")
    return "\n".join(lines) + "\n"
