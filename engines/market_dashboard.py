"""Data for the Streamlit market dashboard. Read only; nothing is invented.

`load` reads the library once (the same engines the daily digest uses) and returns plain data;
the `*_rows` helpers shape it for tables. A missing value is None (shown as blank), never zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engines import daily_digest, move_explainer
from scripts import build_digest, build_radar, explain_moves


def load(db: Any, now: datetime, days: int = 3, top: int = 15) -> dict[str, Any]:
    today = now.date()
    bars = explain_moves.load_bars(db, today, 10)
    moves = move_explainer.daily_moves(bars)
    day = daily_digest.latest_trading_day(moves)
    radar, radar_stats = build_radar.build(db, today, days, top)
    items, universe = explain_moves.build(db, today, days, 40)
    news = db.execute("SELECT MAX(day) AS d FROM news_rollup")[0]["d"]
    return {
        "today": today.isoformat(),
        "price_day": day,
        "news_day": news,
        "breadth": daily_digest.breadth(moves, day) if day else None,
        "radar": radar,
        "radar_stats": radar_stats,
        "moves": items,
        "universe": universe,
        "built_utc": now.strftime("%Y-%m-%d %H:%M"),
    }


def radar_rows(radar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for i, s in enumerate(radar, 1):
        top = max(s["drivers"], key=lambda d: d["points"])
        rows.append(
            {
                "#": i,
                "Symbol": s["symbol"],
                "Score": s["score"],
                "Main evidence": top["text"][:160],
                "Kinds": ", ".join(sorted({d["kind"] for d in s["drivers"]})),
                "Unknown": (s["unknown"] or [""])[0],
            }
        )
    return rows


def explained(moves: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(moves with a candidate cause on file, moves with none)."""
    none = [m for m in moves if m["verdict"].startswith("no identified cause")]
    return [m for m in moves if m not in none], none


def move_rows(moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Symbol": m["symbol"],
            "Day": m["day"],
            "Move %": m["move"],
            "Volume x": m.get("volume_x"),
            "What is on file": m["verdict"],
            "Top evidence": (m["evidence"][0]["text"][:140] if m["evidence"] else ""),
        }
        for m in moves
    ]


def breadth_line(b: dict[str, Any] | None) -> str:
    if not b:
        return "No price data."
    return (
        f"{b['symbols']} symbols: {b['up']} up, {b['down']} down, {b['flat']} unchanged; "
        f"median {b['median']:+.2f}%"
    )


__all__ = ["load", "radar_rows", "explained", "move_rows", "breadth_line", "build_digest"]
